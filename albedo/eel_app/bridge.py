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
    return {
        "ok":          True,
        "version":     version,
        "uptime_s":    round(time.time() - _started_at, 1),
        "ui":          "eel",
    }


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
        v = os.environ.get(k, "").strip() if "os" in dir() else ""
        if v:
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

    This is intentionally synchronous (blocks until the LLM finishes) —
    the JS side calls it inside an async wrapper and shows a spinner.
    For streaming responses, the next session can swap this for a
    coroutine that pushes chunks via eel.append_chat_chunk(...).
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

    try:
        from albedo.pipeline import run as pipeline_run
        reply = pipeline_run(text, use_web=use_web)
        set_swarm_state("ALBEDO_CORE", "standby")
        if use_web:
            set_swarm_state("WEB_SCRAPER", "standby")
        return {"ok": True, "reply": reply, "used_web": use_web}
    except Exception as exc:                                        # noqa: BLE001
        set_swarm_state("ALBEDO_CORE", "error")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


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
    Update one settings.json field. Read-merge-write so we don't clobber
    other keys (incl. those Tk gui or comm_mode may have set).
    """
    if not key:
        return {"ok": False, "error": "missing key"}
    try:
        data = _read_settings_dict()
        data[key] = value
        ok = _write_settings_dict(data)
        if not ok:
            return {"ok": False, "error": "settings file not writable"}
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
