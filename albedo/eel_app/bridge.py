"""
bridge.py — Python ↔ JS boundary for the Eel UI.

Every function the JavaScript layer calls lives here, decorated with
@eel.expose. The bridge is intentionally THIN: it routes to the
already-tested backend modules built in Phases 1–6 + 4. Anything heavy
(LLM dispatch, telemetry probing, safety_catch approval) is implemented
in those modules; this layer just type-coerces, JSON-serializes, and
swallows exceptions so a buggy backend can't crash the websocket bridge.

Every exposed function returns a JSON-serializable value. Errors are
reported as ``{"ok": False, "error": "..."}`` rather than raising so the
JS side can render a friendly message without parsing tracebacks.

Importable without eel installed
--------------------------------
The @eel.expose decorator is applied conditionally — if eel isn't on
the path, the functions stay plain callables. This lets unit tests
import the module and exercise the routing logic without spinning up a
websocket server.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

# Soft import: if eel is missing, define a no-op decorator so the module
# still loads. The launcher in app.py refuses to start when eel is gone.
try:
    import eel as _eel
    _expose = _eel.expose
except ImportError:
    def _expose(fn):                                                # type: ignore[misc]
        return fn


# ---------------------------------------------------------------------------
# Active persona — tracks which wake word last fired and drives the chat label
# ---------------------------------------------------------------------------

_persona_lock = threading.Lock()
_persona_name = "ALBEDO"   # display name: "CORTANA", "JARVIS", or "ALBEDO"

# Mapping: bare wake word → display label shown in chat / topbar.
# "jarvis" is the OWW trigger (hey_jarvis model) but maps to CORTANA
# display because that's the persona identity of this assistant.
_PERSONA_LABELS: dict[str, str] = {
    "cortana": "CORTANA",
    "jarvis":  "CORTANA",   # hey_jarvis OWW model → Cortana persona
}


def _word_to_label(word: str) -> str:
    """Normalise a bare wake word to its display label."""
    return _PERSONA_LABELS.get(word.strip().lower(), word.strip().upper() or "ALBEDO")


def notify_persona_change(word: str) -> None:
    """
    Called (from the wake-word listener callback or wakeword detection code)
    when a specific wake word fires. Updates the module-level persona name,
    swaps the active Ollama model (albedo-cortana / albedo-jarvis), and
    pushes the new label to the JS layer via eel if available.

    Safe to call from any thread.
    """
    global _persona_name
    label = _word_to_label(word)
    with _persona_lock:
        _persona_name = label
    # Swap the Ollama model + system prompt in the inference bridge.
    # Pass the display label (e.g. "CORTANA") normalised to lowercase so
    # set_active_persona routes to the correct model regardless of which
    # OWW wake word triggered (e.g. "hey_jarvis" maps to CORTANA display).
    try:
        from albedo.bridge import set_active_persona
        set_active_persona(label.lower())
    except Exception:
        pass
    # Push display label to JS — _albedo_persona_push is registered by chat.js
    try:
        import eel as _eel
        _eel._albedo_persona_push(label)()  # noqa: SLF001
    except Exception:
        pass


@_expose
def get_active_persona_name() -> dict:
    """Return the display name of the currently active persona (e.g. 'CORTANA')."""
    with _persona_lock:
        return {"ok": True, "name": _persona_name}


# ---------------------------------------------------------------------------
# Diagnostics + lifecycle
# ---------------------------------------------------------------------------

_started_at = time.time()


@_expose
def get_version() -> dict:
    """App version, uptime, branch state — shown in the drawer."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent.parent
    try:
        version = (root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        version = "unknown"

    # Seed persona name + active Ollama model from settings.json on first call
    global _persona_name
    try:
        s = _read_settings_dict()
        persona_key = s.get("active_persona", "").strip().lower()
        if persona_key:
            with _persona_lock:
                _persona_name = _word_to_label(persona_key)
            # Also swap the inference model so the right Ollama model is used
            try:
                from albedo.bridge import set_active_persona
                set_active_persona(persona_key)
            except Exception:
                pass
    except Exception:
        pass

    return {
        "ok":          True,
        "version":     version,
        "uptime_s":    round(time.time() - _started_at, 1),
        "ui":          "eel",
        "persona":     _persona_name,
    }


@_expose
def check_for_update() -> dict:
    """
    Compare the local VERSION file against the latest GitHub release.
    Returns {ok, current, latest, up_to_date, release_url, error}.
    """
    from pathlib import Path
    import json
    import urllib.request

    root = Path(__file__).resolve().parent.parent.parent
    try:
        current = (root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        current = "unknown"

    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/Dracon420/The-Albedo-AI-Project/releases/latest",
            headers={"User-Agent": "Albedo-UpdateChecker/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        latest      = data.get("tag_name", "").lstrip("v")
        release_url = data.get("html_url", "")
        up_to_date  = (latest == current)

        return {
            "ok":          True,
            "current":     current,
            "latest":      latest,
            "up_to_date":  up_to_date,
            "release_url": release_url,
        }
    except Exception as exc:
        return {
            "ok":      False,
            "current": current,
            "error":   str(exc),
        }


@_expose
def get_config_values(keys: list) -> dict:
    """Return a subset of config values by key name for the UI."""
    try:
        from albedo import config
        data = {k: getattr(config, k, None) for k in keys}
        return {"ok": True, "data": data}
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@_expose
def get_hardware_profile() -> dict:
    """Cached CPU/GPU/RAM info from Phase 1 hardware_profile.json."""
    try:
        from albedo import hardware_profile
        return {"ok": True, "data": hardware_profile.get_hardware()}
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@_expose
def get_resource_map() -> dict:
    """Effective device assignments for each ML component (Phase 6)."""
    try:
        from albedo import resource_policy
        return {"ok": True, "data": resource_policy.detect()}
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Telemetry — driven by JS poller, 1–4 Hz
# ---------------------------------------------------------------------------

@_expose
def get_telemetry() -> dict:
    """Live host stats — CPU/RAM/GPU/disk/network deltas (Phase 3)."""
    try:
        from albedo.telemetry import get_full_telemetry
        return {"ok": True, "data": get_full_telemetry()}
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Swarm status — three indicator lights in the status bar
# ---------------------------------------------------------------------------

# Single source of truth for swarm LED state. The chat pipeline updates
# this as agents activate / complete. Each entry is one of:
#   "standby" (orange)   "active" (cyan)   "error" (red)
_swarm_state: dict[str, str] = {
    "ALBEDO_CORE":        "standby",
    "WEB_SCRAPER":        "standby",
    "EXECUTION_OVERRIDE": "standby",
}
_swarm_lock = threading.Lock()


def set_swarm_state(agent: str, state: str) -> None:
    """
    Update one agent's LED. Backend code calls this when an agent
    starts/finishes work. Idempotent.
    """
    if state not in ("standby", "active", "error"):
        state = "standby"
    with _swarm_lock:
        if agent in _swarm_state:
            _swarm_state[agent] = state


@_expose
def get_swarm_status() -> dict:
    """Snapshot of the three swarm-agent LEDs."""
    with _swarm_lock:
        return {"ok": True, "data": dict(_swarm_state)}


# ---------------------------------------------------------------------------
# Neural links — status grid in the centre HUD
#
# A "neural link" is any backend subsystem the operator might want at-a-glance
# visibility into: the three swarm LLM clients (Gemini/Groq/Together), the
# local Ollama runtime, the ChromaDB vector store, the active STT engine
# (Vosk or Deepgram or whisper), the active TTS engine (Piper or Kokoro),
# the wake-word arm state, and the loopback webhook.
#
# Each link reports {status, label, detail}. status drives the LED colour
# in the CSS grid via [data-status]:
#   "ready"   cyan      configured and available
#   "active"  bright    currently in use (set via update_neural_link)
#   "standby" orange    configured but idle / waiting
#   "off"     dim       not configured (no key / not installed)
#   "error"   red       configured but failing health check
# ---------------------------------------------------------------------------

# Live override map — backend code calls update_neural_link("GEMINI", "active")
# to flip a dot from its static state to a live state. The values here OVERRIDE
# whatever get_neural_links() would compute from configuration.
_live_states: dict[str, str] = {}
_live_lock = threading.Lock()


def update_neural_link(name: str, status: str) -> None:
    """
    Push a live status change for one neural-link. Called from pipeline /
    swarm / STT / TTS code when a subsystem starts or finishes work.

    Pass status=None or "" to clear the override and fall back to the
    config-detected state.
    """
    if status not in (None, "", "ready", "active", "standby", "off", "error"):
        status = "standby"
    with _live_lock:
        if not status:
            _live_states.pop(name, None)
        else:
            _live_states[name] = status


def _is_configured_env(*keys: str) -> bool:
    """True if at least one of the given env keys is set to a non-empty value."""
    for k in keys:
        if os.environ.get(k, "").strip():
            return True
    return False


def _detect_neural_links() -> dict:
    """
    Snapshot the configuration of every tracked neural-link. Pure read —
    no network calls, no model loads, runs in <5 ms.
    """
    import os
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent.parent
    links: dict[str, dict] = {}

    def link(name: str, status: str, label: str, detail: str = "") -> None:
        links[name] = {"status": status, "label": label, "detail": detail}

    # --- Swarm LLM clients ---
    for key, name in (("GEMINI_API_KEY", "GEMINI"),
                      ("GROQ_API_KEY",   "GROQ"),
                      ("TOGETHER_API_KEY","TOGETHER")):
        if os.environ.get(key, "").strip():
            link(name, "ready", "READY", "API key configured")
        else:
            link(name, "off", "OFF", "no API key")

    # --- Ollama (local LLM runtime) ---
    base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
    link("OLLAMA", "ready", "READY", f"{model} @ {base}")

    # --- Vector store (ChromaDB) ---
    if (root / "chroma_db").exists() or (root / "albedo_memory_db").exists():
        link("VEC_DB", "ready", "ONLINE", "Chroma index present")
    else:
        link("VEC_DB", "standby", "EMPTY", "no index built yet")

    # --- STT engine (dispatched by AUDIO_STT) ---
    stt_engine = (os.environ.get("AUDIO_STT", "vosk") or "vosk").strip().lower()
    if stt_engine == "deepgram":
        if os.environ.get("DEEPGRAM_API_KEY", "").strip():
            link("STT", "ready", "DEEPGRAM", "cloud + whisper fallback")
        else:
            link("STT", "error", "DEEPGRAM", "no DEEPGRAM_API_KEY")
    elif stt_engine == "whisper":
        link("STT", "ready", "WHISPER", "offline, lazy-loaded")
    else:
        # Vosk default
        vosk_path = os.environ.get("VOSK_MODEL_PATH", "")
        if vosk_path and Path(vosk_path).exists():
            link("STT", "ready", "VOSK", "offline, 40 MB")
        else:
            link("STT", "standby", "VOSK", "model not cached yet")

    # --- TTS engine (dispatched by AUDIO_TTS) ---
    tts_engine = (os.environ.get("AUDIO_TTS", "piper") or "piper").strip().lower()
    if tts_engine == "kokoro":
        kokoro_model = Path(os.environ.get("KOKORO_MODEL_PATH",
                                           str(root / "voices" / "kokoro-v1.0.onnx")))
        if kokoro_model.exists():
            link("TTS", "ready", "KOKORO", "offline ONNX")
        else:
            link("TTS", "standby", "KOKORO", "model missing — using Piper")
    else:
        link("TTS", "ready", "PIPER", "offline + Edge-TTS primary")

    # --- Wake-word listener (Phase 4 N+3) ---
    try:
        from albedo.audio.comm_mode import get_wake_state, WakeState
        if get_wake_state() == WakeState.ARMED:
            link("WAKE", "active", "ARMED", "listening for wake word")
        else:
            link("WAKE", "standby", "OFF", "press WAKE to arm")
    except Exception:
        link("WAKE", "off", "OFF", "module unavailable")

    # --- Dream cycle ---
    try:
        from albedo.dream import orchestrator as _dream
        state = _dream.get_state()
        if state == "DREAMING":
            link("DREAM", "active", "DREAMING", "autonomous cycle running")
        elif state in ("COOLDOWN", "INTERRUPTED"):
            link("DREAM", "standby", state, "")
        else:
            from albedo.config import IDLE_THRESHOLD_MINUTES
            link("DREAM", "ready", "WATCHING", f"idle → {IDLE_THRESHOLD_MINUTES}m")
    except Exception:
        link("DREAM", "off", "OFF", "module unavailable")

    # --- Phase 5 webhook ---
    try:
        from albedo import webhook
        if webhook.is_running():
            link("WEBHOOK", "ready", "LISTENING", "127.0.0.1:5000")
        else:
            link("WEBHOOK", "off", "OFF", "not started")
    except Exception:
        link("WEBHOOK", "off", "OFF", "module unavailable")

    # Apply any live overrides pushed via update_neural_link()
    with _live_lock:
        for name, status in _live_states.items():
            if name in links:
                links[name]["status"] = status

    return links


@_expose
def get_neural_links() -> dict:
    """Snapshot of every tracked subsystem for the centre HUD status grid."""
    try:
        return {"ok": True, "data": _detect_neural_links()}
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@_expose
def get_app_state() -> dict:
    """
    Coarse single-word state for the big STANDBY / LISTENING / SPEAKING
    indicator under the logo. Right now this just reflects whether any
    swarm agent is "active" — a richer state machine can wire here later.
    """
    with _swarm_lock:
        any_active = any(s == "active" for s in _swarm_state.values())
        any_error  = any(s == "error"  for s in _swarm_state.values())
    if any_error:  return {"ok": True, "state": "ERROR"}
    if any_active: return {"ok": True, "state": "ACTIVE"}
    return {"ok": True, "state": "STANDBY"}


# ---------------------------------------------------------------------------
# Comm mode + wake state — Phase 4 N+3
# ---------------------------------------------------------------------------

@_expose
def get_comm_mode() -> dict:
    try:
        from albedo.audio import comm_mode
        return {"ok": True, "mode": comm_mode.get_mode().value}
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@_expose
def set_comm_mode(mode: str) -> dict:
    try:
        from albedo.audio import comm_mode
        applied = comm_mode.set_mode(mode)
        return {"ok": True, "mode": applied.value}
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@_expose
def get_wake_state() -> dict:
    try:
        from albedo.audio import comm_mode
        return {"ok": True, "state": comm_mode.get_wake_state().value}
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@_expose
def set_wake_state(state: str) -> dict:
    try:
        from albedo.audio import comm_mode
        applied = comm_mode.set_wake_state(state)
        return {"ok": True, "state": applied.value}
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Chat — the main interaction
# ---------------------------------------------------------------------------

@_expose
def send_query(text: str, use_web: bool = False) -> dict:
    """
    Submit a chat query through the LLM pipeline and return the response.

    The pipeline runs on a dedicated background thread so Eel's websocket
    thread is never blocked. The JS side calls this inside an async wrapper
    and shows a spinner; the reply is returned when the thread finishes.
    """
    if not text or not text.strip():
        return {"ok": False, "error": "empty query"}
    text = text.strip()

    # Strip web: prefix the same way the Tk path does
    if text.lower().startswith("web:"):
        use_web = True
        text = text[4:].strip()

    set_swarm_state("ALBEDO_CORE", "active")
    if use_web:
        set_swarm_state("WEB_SCRAPER", "active")

    result: dict = {}

    def _run() -> None:
        try:
            from albedo.pipeline import run as pipeline_run
            result["reply"] = pipeline_run(text, use_web=use_web)
            result["ok"] = True
            set_swarm_state("ALBEDO_CORE", "standby")
            if use_web:
                set_swarm_state("WEB_SCRAPER", "standby")
        except Exception as exc:                                    # noqa: BLE001
            result["ok"] = False
            result["error"] = f"{type(exc).__name__}: {exc}"
            set_swarm_state("ALBEDO_CORE", "error")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=120)

    if t.is_alive():
        set_swarm_state("ALBEDO_CORE", "error")
        return {"ok": False, "error": "pipeline timeout (120 s)"}

    result["used_web"] = use_web
    return result


@_expose
def trigger_mic_capture() -> dict:
    """
    One-shot voice capture for the MIC button in the Eel UI.
    Records until silence, transcribes via Vosk/Whisper, returns the text.
    """
    try:
        from albedo.audio.stt import transcribe_once
        text = transcribe_once()
        if text and text.strip():
            return {"ok": True, "text": text.strip()}
        return {"ok": True, "text": None, "error": "nothing transcribed"}
    except ImportError:
        return {"ok": False, "error": "STT not available — check AUDIO_STT setting"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@_expose
def trigger_scan_capture() -> dict:
    """
    Screenshot + vision analysis for the SCAN button in the Eel UI.
    Captures the screen and describes it using the configured vision model.
    """
    try:
        import tempfile, os
        from PIL import ImageGrab
        # Capture screen
        img = ImageGrab.grab()
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_path = f.name
        img.save(tmp_path)
        # Route through vision pipeline if available
        try:
            from albedo.vision import describe_image
            description = describe_image(tmp_path)
        except ImportError:
            # Fallback: just confirm screenshot was taken
            description = f"Screenshot captured ({img.width}x{img.height}). Vision model not configured."
        finally:
            try: os.unlink(tmp_path)
            except Exception: pass
        return {"ok": True, "description": description}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Webhook bridge — drained by the JS poller
# ---------------------------------------------------------------------------

@_expose
def pop_webhook_updates() -> dict:
    """Drain any pending remote commands queued by the Phase 5 webhook."""
    try:
        from albedo import webhook
        return {"ok": True, "updates": webhook.pop_pending_updates()}
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Settings — read + write the install-root settings.json shared with Tk gui
# ---------------------------------------------------------------------------

_SETTINGS_FILE = Path(__file__).resolve().parent.parent.parent / "settings.json"
_settings_lock = threading.Lock()

_PERSONAS = ["cortana", "jarvis"]

_AUTO_UPDATE_OPTIONS = [
    "Never", "Every 6 hours", "Every 12 hours",
    "Every 24 hours", "Every 7 days",
]


def _read_settings_dict() -> dict:
    try:
        import json
        return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_settings_dict(data: dict) -> bool:
    import json
    try:
        with _settings_lock:
            _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            _SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True
    except OSError:
        return False


@_expose
def get_settings() -> dict:
    """
    Snapshot of the install-root settings.json plus the enumerated choices
    each setting accepts. Drawer Settings panel uses this to render
    dropdowns and sliders on first open.
    """
    try:
        current = _read_settings_dict()
        # Sensible defaults for fields that may be missing on a fresh install
        current.setdefault("active_persona",      "cortana")
        current.setdefault("vision_temperature",  0.2)
        current.setdefault("auto_update",         "Every 24 hours")
        current.setdefault("background",          "Albedo 2")
        current.setdefault("audio_input_device",  None)
        current.setdefault("audio_output_device", None)
        return {
            "ok":       True,
            "settings": current,
            "choices":  {
                "active_persona":      list(_PERSONAS),
                "auto_update":         list(_AUTO_UPDATE_OPTIONS),
                "background":          ["bg1", "bg2", "bg3", "bg4"],
                "vision_temperature":  {"min": 0.0, "max": 1.0, "step": 0.05},
            },
        }
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@_expose
def set_setting(key: str, value: Any) -> dict:
    """
    Update one settings.json field. Read-merge-write under the settings lock
    so concurrent calls from the Eel JS layer don't corrupt each other.
    """
    if not key:
        return {"ok": False, "error": "missing key"}
    try:
        import json
        with _settings_lock:
            try:
                data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            data[key] = value
            try:
                _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
                _SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
            except OSError:
                return {"ok": False, "error": "settings file not writable"}
        # Live-swap inference model when persona changes via settings panel
        if key == "active_persona" and isinstance(value, str):
            notify_persona_change(value)
        return {"ok": True, "key": key, "value": value}
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@_expose
def get_audio_devices() -> dict:
    """
    Enumerate sounddevice input/output devices for the Settings drop-downs.
    Returns:
        {ok, inputs:  [{index, name, channels, default}],
             outputs: [{index, name, channels, default}]}
    """
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        try:
            default_in, default_out = sd.default.device
        except Exception:
            default_in = default_out = None
        inputs, outputs = [], []
        for i, d in enumerate(devices):
            entry = {
                "index":    i,
                "name":     d.get("name", f"device {i}"),
                "channels": int(d.get("max_input_channels", 0)
                                if d.get("max_input_channels", 0) > 0
                                else d.get("max_output_channels", 0)),
            }
            if d.get("max_input_channels", 0) > 0:
                inputs.append({**entry, "default": i == default_in})
            if d.get("max_output_channels", 0) > 0:
                outputs.append({**entry, "default": i == default_out})
        return {"ok": True, "inputs": inputs, "outputs": outputs}
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Backgrounds
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Obsidian vault + REM dream cycle (background memory consolidation)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Dream cycle — autonomous idle-triggered, no manual button
# ---------------------------------------------------------------------------

def _dream_status_push(state: str, detail: str) -> None:
    """
    Called by the dream orchestrator when phase/state changes.
    Pushes the new state to the DREAM neural link AND the #dreamStatus readout.
    """
    status_map = {
        "DREAMING":     "active",
        "COOLDOWN":     "standby",
        "INTERRUPTED":  "standby",
        "IDLE":         "ready",
    }
    update_neural_link("DREAM", status_map.get(state, "standby"))
    # Push text to the drawer readout element
    try:
        label = f"// dream: {state.lower()}"
        if detail:
            label += f"\n// {detail}"
        eel._albedo_dream_push(label)()  # noqa: SLF001
    except Exception:  # noqa: BLE001
        pass


@_expose
def get_dream_state() -> dict:
    """Current dream cycle state + last report summary."""
    try:
        from albedo.dream import orchestrator as _dream
        return {
            "ok":     True,
            "state":  _dream.get_state(),
            "report": _dream.get_last_report(),
        }
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@_expose
def force_dream_cycle() -> dict:
    """
    Manually trigger a dream cycle from the UI (debug / on-demand use).
    Respects the interrupt flag — returns immediately if already dreaming.
    """
    try:
        from albedo.dream import orchestrator as _dream
        if _dream.get_state() == "DREAMING":
            return {"ok": False, "error": "Dream cycle already active."}
        threading.Thread(
            target=_dream.start_dream,
            kwargs={"status_cb": _dream_status_push, "forced": True},
            daemon=True,
            name="dream-manual",
        ).start()
        return {"ok": True, "status": "Dream cycle initiated."}
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@_expose
def index_obsidian_vault() -> dict:
    """
    Trigger memory.index_obsidian_vault() — re-scans the configured
    OBSIDIAN_VAULT_PATH and rebuilds the ChromaDB index used by the RAG
    pipeline. Returns the human-readable status string from the indexer
    (e.g. "Indexed 42 documents across 7 folders.").
    """
    try:
        import sys, importlib
        _root = str(Path(__file__).resolve().parent.parent.parent)
        if _root not in sys.path:
            sys.path.insert(0, _root)
        _mem = importlib.import_module("memory")
        status = _mem.index_obsidian_vault()
        return {"ok": True, "status": str(status)}
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@_expose
def initiate_dream_cycle() -> dict:
    """
    Trigger operative_dream.initiate_rem_cycle() — the background
    memory-consolidation agent. Reads the daily interaction traces,
    runs them through the local LLM for reflection, and appends the
    generated markdown insight report to the Obsidian vault.

    Returns the dream-cycle's status string so the UI can show a
    "Dream complete: 12 traces consolidated" toast.
    """
    try:
        import sys, importlib
        _root = str(Path(__file__).resolve().parent.parent.parent)
        if _root not in sys.path:
            sys.path.insert(0, _root)
        _dream = importlib.import_module("operative_dream")
        status = _dream.initiate_rem_cycle()
        return {"ok": True, "status": str(status) if status else "Dream cycle complete."}
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@_expose
def get_backgrounds() -> dict:
    """
    Filenames for the four <body> background images. Frontend cycles
    through them via the drawer's background toggle.
    """
    return {"ok": True, "files": [
        "Albedo-mission-control-background-1.png",
        "albedo-mission-control-background-2.png",
        "albedo-mission-control-background-3.png",
        "albedo-mission-control-background-4.png",
    ]}
