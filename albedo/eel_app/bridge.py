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
_PERSONA_LABELS: dict[str, str] = {
    "cortana": "CORTANA",
    "jarvis":  "JARVIS",
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
    # Swap the Ollama model + system prompt in the inference bridge
    try:
        from albedo.bridge import set_active_persona
        set_active_persona(word)
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
        any_active = any(s == "active" for s in _swarm_state.values())
        any_error  = any(s == "error"  for s in _swarm_state.values())
    # Push the derived orb state immediately so it doesn't lag the 1.5s poll.
    orb = "ERROR" if any_error else ("ACTIVE" if any_active else "STANDBY")
    try:
        import eel as _eel_mod  # noqa: PLC0415
        _eel_mod._albedo_state_push(orb)
    except Exception:
        pass


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

    # --- Reasoning-brain providers (agent team + swarm tier 0) ---
    if os.environ.get("AZURE_OPENAI_KEY", "").strip() and \
       os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip():
        link("AZURE", "ready", "READY",
             os.environ.get("AZURE_OPENAI_DEPLOYMENT", "azure"))
    else:
        link("AZURE", "off", "OFF", "no Azure OpenAI key/endpoint")

    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        link("ANTHROPIC", "ready", "CLAUDE", "API key configured")
    else:
        link("ANTHROPIC", "off", "OFF", "no API key")

    # --- Computation + web-search tools ---
    if os.environ.get("WOLFRAM_API_KEY", "").strip():
        link("WOLFRAM", "ready", "READY", "computation interceptor")
    else:
        link("WOLFRAM", "off", "OFF", "no WOLFRAM_API_KEY")

    if os.environ.get("TAVILY_API_KEY", "").strip():
        link("TAVILY", "ready", "READY", "primary web search")
    else:
        link("TAVILY", "standby", "DDG", "no key — DuckDuckGo fallback")

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
def get_app_inventory(limit: int = 25) -> dict:
    """Structured installed-apps list for the app chooser popup."""
    try:
        from albedo.app_inventory import list_installed_apps as _li
        return {"ok": True, "data": _li(limit=min(int(limit or 25), 60))}
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@_expose
def uninstall_apps(names: list) -> dict:
    """Uninstall a list of apps by name (each gated by the approval modal via the
    agent tool's safety_catch path is bypassed here — so confirm in the UI first)."""
    from albedo.app_inventory import uninstall_app as _u
    results = []
    for nm in (names or []):
        try:
            results.append({"name": nm, "result": _u(str(nm))})
        except Exception as exc:                                    # noqa: BLE001
            results.append({"name": nm, "result": f"error: {exc}"})
    return {"ok": True, "results": results}


@_expose
def get_perf_timings(n: int = 12) -> dict:
    """
    Recent per-turn latency breakdowns (newest last) from albedo.perf — used by
    the Tactical Drawer to show where query time actually goes (rag/web/wiki/llm).
    """
    try:
        from albedo import perf
        return {"ok": True, "data": perf.get_recent(n)}
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
# TTS control — stop / mute
# ---------------------------------------------------------------------------

_audio_muted = False   # when True, speak() calls are skipped entirely

@_expose
def stop_tts() -> dict:
    """Immediately halt any active TTS playback. Called by the STOP button."""
    try:
        from albedo.audio.tts import stop_audio
        stop_audio()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@_expose
def set_audio_muted(muted: bool) -> dict:
    """Toggle backend audio mute. When muted, speak() is a no-op."""
    global _audio_muted
    _audio_muted = bool(muted)
    return {"ok": True, "muted": _audio_muted}


def is_audio_muted() -> bool:
    return _audio_muted


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
def run_agent_query(text: str, history: list | None = None) -> dict:
    """
    Run a query through the AGENTIC loop (plan→act→observe over the tool
    catalog), using the user-selected brain provider. Destructive tool calls
    are gated through the safety_catch approval modal per the agent_autonomy
    setting. Returns {ok, answer, steps, provider, model, iterations, error}.

    Runs on a background thread so the Eel websocket isn't blocked; the loop
    can take a while (multiple LLM round-trips + tool execution).
    """
    if not text or not text.strip():
        return {"ok": False, "error": "empty query"}

    set_swarm_state("ALBEDO_CORE", "active")
    out: dict = {}

    def _run() -> None:
        try:
            from albedo.agent import run_agent
            res = run_agent(text.strip(), history=history)
            out.update(res)
            out["ok"] = res.get("error") is None
            set_swarm_state("ALBEDO_CORE",
                            "standby" if out["ok"] else "error")
        except Exception as exc:                                    # noqa: BLE001
            out["ok"] = False
            out["error"] = f"{type(exc).__name__}: {exc}"
            set_swarm_state("ALBEDO_CORE", "error")

    t = threading.Thread(target=_run, daemon=True, name="agent-query")
    t.start()
    # Cooperative wait so eel's gevent hub keeps delivering UI pushes (see the
    # send_chat direct-path note — a hard join() freezes the hub).
    try:
        import gevent as _gvt  # noqa: PLC0415
        _w = 0.0
        while t.is_alive() and _w < 300:
            _gvt.sleep(0.1)
            _w += 0.1
    except Exception:
        t.join(timeout=300)

    if t.is_alive():
        set_swarm_state("ALBEDO_CORE", "error")
        return {"ok": False, "error": "agent timeout (300 s)"}
    return out


# Server-side conversation memory — authoritative so continuity works even if a
# frontend forgets to pass history. Last _HISTORY_MAX messages (user+assistant).
_chat_history: list[dict] = []
_HISTORY_MAX = 20
_history_lock = threading.Lock()

# Phase timing → logs/chat_timing.log (console is hidden, so log to a file we
# can read back to see exactly where a slow turn spent its time).
import time as _time_mod  # noqa: E402


def _tlog(msg: str) -> None:
    try:
        from pathlib import Path as _P
        root = _P(__file__).resolve().parent.parent.parent
        logd = root / "logs"
        logd.mkdir(exist_ok=True)
        with open(logd / "chat_timing.log", "a", encoding="utf-8") as f:
            f.write(f"{_time_mod.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


def _remember(user_msg: str, assistant_msg: str) -> None:
    if not user_msg or not assistant_msg:
        return
    with _history_lock:
        _chat_history.append({"role": "user", "content": user_msg})
        _chat_history.append({"role": "assistant", "content": assistant_msg})
        del _chat_history[:-_HISTORY_MAX]


_TOOL_VERBS = {
    "list_installed_apps": "Checking your installed apps",
    "uninstall_app":       "Uninstalling",
    "get_system_telemetry":"Reading system telemetry",
    "list_top_processes":  "Listing top processes",
    "kill_process":        "Stopping a process",
    "disk_cleanup":        "Clearing temporary files",
    "optimize_system":     "Optimizing the system",
    "search_web":          "Searching the web",
    "rag_search":          "Searching your knowledge vault",
    "list_directory":      "Listing files",
    "launch_app":          "Launching an app",
    "download_install":    "Downloading",
}


def _friendly_status(msg: str) -> str | None:
    """Map a raw agent status line to a short, user-facing progress phrase.
    Returns None for noise that shouldn't be shown."""
    m = (msg or "").lower()
    if m.startswith("thinking"):
        return "Thinking…"
    if "tool call:" in m:
        import re
        mt = re.search(r"tool call:\s*([a-z_]+)", m)
        name = mt.group(1) if mt else ""
        return f"{_TOOL_VERBS.get(name, 'Using ' + (name or 'a tool'))}…"
    if "awaiting approval" in m:
        return "Waiting for your approval…"
    if m.startswith("transient error") or "retry" in m:
        return "Provider busy — retrying…"
    return None


@_expose
def send_chat(text: str, history: list | None = None) -> dict:
    """
    User-facing chat entry point.

    Routing order:
      1. INSTANT fast-path: identity / greeting -> canned reply, <1 ms.
      2. Router LLM (20s max): classifies message as "direct" or "team".
      3a. DIRECT: single agent, 90s max, returns answer inline.
      3b. TEAM: returns immediately with acknowledgement; team runs in a
          background thread and pushes the final answer to the chat via
          _albedo_chat_push when complete.

    Returns {ok, mode, reason, answer, error} —
        mode = "instant" | "direct" | "team"
    """
    if not text or not text.strip():
        return {"ok": False, "error": "empty message"}

    _phase_t0 = _time_mod.perf_counter()

    def _ph(label: str) -> None:
        _tlog(f"+{(_time_mod.perf_counter() - _phase_t0):6.1f}s {label}  | {text[:40]!r}")

    _ph("send_chat START")

    # ── 1. Instant intercept (no LLM) ────────────────────────────────
    try:
        from albedo.pipeline import try_fast_answer
        canned = try_fast_answer(text.strip())
        if canned:
            return {"ok": True, "mode": "instant", "reason": "fast-path",
                    "answer": canned, "error": None}
    except Exception:
        pass
    _ph("after fast-path")

    # ── 1b. Semantic answer cache — instant near-duplicate knowledge reply ────
    # Only for non-team knowledge questions; volatile/system queries are never
    # cached (guarded inside semantic_cache), and only tool-free answers are
    # ever stored (see the direct path below), so this never serves stale state.
    try:
        from albedo.agent_team import _heuristic_classify as _hc  # noqa: PLC0415
        from albedo import semantic_cache  # noqa: PLC0415
        if _hc(text.strip()) != "team":
            _cached = semantic_cache.lookup(text.strip())
            if _cached:
                _remember(text.strip(), _cached)
                return {"ok": True, "mode": "cached", "reason": "semantic-cache",
                        "answer": _cached, "error": None}
    except Exception:
        pass
    _ph("after semantic-cache lookup")

    set_swarm_state("ALBEDO_CORE", "active")

    from albedo.agent_team import (  # noqa: PLC0415
        _ROUTER_PROMPT, _extract_json, _role_provider, _emit as _team_emit,
        _heuristic_classify,
    )
    from albedo import agent as _agent_mod  # noqa: PLC0415

    # ── 2. Routing — heuristic ONLY (no router LLM call) ─────────────────────
    # Default to DIRECT unless the zero-latency keyword heuristic clearly detects
    # a multi-specialist task. The old LLM router added a full round-trip (up to a
    # 30s timeout) before EVERY answer — pure latency for the common case. The
    # direct agent is fully tool-capable, so borderline queries still get handled.
    mode = _heuristic_classify(text.strip()) or "direct"
    reason = "keyword-heuristic" if mode == "team" else "default-direct"

    _team_emit("router.decision", mode=mode, reason=reason, message=text[:200])

    # ── 3b. TEAM — non-blocking; each specialist's result streams to chat ─────
    if mode == "team":
        def _chat_push(kind: str, msg: str) -> None:
            try:
                import eel as _eel_mod  # noqa: PLC0415
                _eel_mod._albedo_chat_push(kind, msg)
            except Exception:
                pass

        def _on_task_done(result: dict) -> None:
            role = result.get("role", "?")
            ans = (result.get("answer") or "").strip()
            err = result.get("error")
            if err and not ans:
                _chat_push("system", f"[{role}] (error: {str(err)[:120]})")
            elif ans:
                _chat_push("albedo", f"[{role}] {ans}")

        def _bg_team() -> None:
            try:
                from albedo.agent_team import run_team  # noqa: PLC0415
                team_res = run_team(text.strip(), require_plan_approval=False,
                                    on_task_done=_on_task_done)
                # Per-agent answers already streamed in; close with the Critic's
                # verdict rather than re-dumping every result.
                crit = team_res.get("critique") or {}
                summary = (crit.get("summary") or "").strip()
                if team_res.get("error"):
                    _chat_push("system", f"[TEAM] {team_res['error']}")
                elif summary:
                    verdict = "complete" if crit.get("complete") else "incomplete"
                    _chat_push("albedo", f"[Critic — {verdict}] {summary}")
                else:
                    _chat_push("system", "[TEAM] done.")
            except Exception as exc:
                _chat_push("system", f"[TEAM] error: {exc}")
            set_swarm_state("ALBEDO_CORE", "standby")

        threading.Thread(target=_bg_team, daemon=True, name="team-bg").start()
        return {
            "ok": True,
            "mode": "team",
            "reason": reason,
            "answer": "[TEAM activated — agents are working. Watch Team window for live progress. Answer will appear here when complete.]",
            "error": None,
        }

    # ── 3a. DIRECT — 150s timeout, streams tokens live as they generate ──────
    _direct_bucket: dict = {}
    _streamed = {"any": False}
    import time as _t_mod  # noqa: PLC0415
    from albedo import perf as _perf  # noqa: PLC0415
    _turn = _perf.Turn(text.strip())
    _t_start = _t_mod.perf_counter()

    # Instant "Thinking…" so the user sees activity the moment Albedo starts,
    # before the first LLM round even returns.
    try:
        import eel as _eel_mod  # noqa: PLC0415
        _eel_mod._albedo_chat_status("Thinking…")
    except Exception:
        pass

    def _push_token(tok: str) -> None:
        if not tok:
            return
        _streamed["any"] = True
        try:
            import eel as _eel_mod  # noqa: PLC0415
            _eel_mod._albedo_chat_token(tok)
        except Exception:
            pass

    # Light up the provider that's ABOUT to answer (so the NEURAL LINKS bar
    # shows "active" during processing, not only once the answer lands).
    try:
        from albedo import providers as _prov_mod  # noqa: PLC0415
        _start_prov = _prov_mod.resolve_provider(None).upper()
        for _llm in ("GEMINI", "GROQ", "TOGETHER", "AZURE", "ANTHROPIC", "OLLAMA"):
            update_neural_link(_llm, "active" if _llm == _start_prov else "")
    except Exception:
        pass

    with _history_lock:
        _hist_snapshot = list(_chat_history)   # authoritative server-side memory

    def _push_status(msg: str) -> None:
        friendly = _friendly_status(msg)
        if not friendly:
            return
        try:
            import eel as _eel_mod  # noqa: PLC0415
            _eel_mod._albedo_chat_status(friendly)
        except Exception:
            pass

    def _do_direct() -> None:
        _ph("agent run START")
        try:
            r = _agent_mod.run_agent(text.strip(), history=_hist_snapshot,
                                     role="Albedo", on_token=_push_token,
                                     status_cb=_push_status)
            _direct_bucket["r"] = r
            _ph(f"agent run DONE prov={r.get('provider')} iters={r.get('iterations')} "
                f"err={(r.get('error') or '')[:40]}")
        except Exception as exc:
            _direct_bucket["r"] = {"answer": "", "error": str(exc)}
            _ph(f"agent run EXC {exc}")

    dt = threading.Thread(target=_do_direct, daemon=True, name="chat-direct")
    dt.start()
    # COOPERATIVE wait — send_chat runs in eel's gevent hub thread. A hard
    # dt.join() FREEZES that hub for the whole call, so the worker thread's UI
    # pushes (status/tokens) couldn't be delivered until the 150s timeout — the
    # agent was effectively deadlocked on its own status update. gevent.sleep()
    # yields to the hub each tick so pushes flow in real time and we return the
    # instant the agent finishes (~seconds).
    try:
        import gevent as _gvt  # noqa: PLC0415
        _waited = 0.0
        while dt.is_alive() and _waited < 150:
            _gvt.sleep(0.1)
            _waited += 0.1
    except Exception:
        dt.join(timeout=150)
    if dt.is_alive():
        # Record the (slow) turn so QUERY LATENCY shows it timed out + how long.
        try:
            _turn.add("answer", (_t_mod.perf_counter() - _t_start) * 1000.0)
            _turn.finish("chat:TIMEOUT-150s")
        except Exception:
            pass
        # If the answer is actively streaming to the UI, it's not really stuck —
        # let it finish in the background and close the line, no scary error.
        if _streamed["any"]:
            def _finish_late() -> None:
                dt.join(120)
                try:
                    import eel as _eel_mod  # noqa: PLC0415
                    _eel_mod._albedo_chat_token_end()
                except Exception:
                    pass
                set_swarm_state("ALBEDO_CORE", "standby")
            threading.Thread(target=_finish_late, daemon=True, name="chat-late").start()
            return {"ok": True, "mode": "direct", "reason": reason,
                    "answer": "", "error": None, "streamed": True}
        set_swarm_state("ALBEDO_CORE", "error")
        return {"ok": False, "mode": "direct", "reason": reason,
                "answer": "", "error": "direct answer timed out (150 s)",
                "streamed": _streamed["any"]}

    r = _direct_bucket.get("r") or {}
    ok = not bool(r.get("error"))
    # Record per-turn latency so the QUERY LATENCY panel shows where chat time
    # goes + which provider answered (diagnoses slowness).
    try:
        _turn.add("answer", (_t_mod.perf_counter() - _t_start) * 1000.0)
        _turn.finish(f"chat:{(r.get('provider') or '?')}")
    except Exception:
        pass
    set_swarm_state("ALBEDO_CORE", "standby" if ok else "error")
    # Reflect which brain actually answered on the NEURAL LINKS bar (so a
    # failover, e.g. groq→gemini, is visible). Active = the answering provider;
    # clear overrides on the others so they fall back to their config state.
    _prov = (r.get("provider") or "").upper()
    if _prov:
        for _llm in ("GEMINI", "GROQ", "TOGETHER", "AZURE", "ANTHROPIC", "OLLAMA"):
            update_neural_link(_llm, "active" if _llm == _prov else "")
    # Signal end-of-stream so the UI can finalize the live line.
    if _streamed["any"]:
        try:
            import eel as _eel_mod  # noqa: PLC0415
            _eel_mod._albedo_chat_token_end()
        except Exception:
            pass
    # Remember this exchange so follow-ups ("yes", "do it", "the second one")
    # keep context on the next turn.
    if ok and r.get("answer"):
        _remember(text.strip(), r.get("answer", ""))
    # Cache the answer for instant near-duplicate replies — but ONLY if it used
    # no tools (a tool answer reflects live state and must not be cached).
    if ok and r.get("answer"):
        steps = r.get("steps") or []
        used_tools = any((s or {}).get("type") == "tool_call" for s in steps)
        if not used_tools:
            try:
                from albedo import semantic_cache  # noqa: PLC0415
                semantic_cache.store(text.strip(), r.get("answer", ""))
            except Exception:
                pass
    return {"ok": ok, "mode": "direct", "reason": reason,
            "answer": r.get("answer", ""), "error": r.get("error"),
            "streamed": _streamed["any"]}


@_expose
def get_event_history(limit: int = 200) -> dict:
    """Return recent events from the event bus (for windows that open mid-run)."""
    try:
        from albedo import event_bus
        return {"ok": True, "events": event_bus.history(limit=int(limit or 200))}
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# --- Obsidian vault graph (for the Brain visualization) -----------------------

_WIKILINK_RE = None
# Bump this token if the graph schema changes — the cached dict from an older
# version (e.g. without "folder" on nodes) won't satisfy the new viz.
_VAULT_GRAPH_SCHEMA = "v2-folder"
_vault_graph_cache: dict | None = None


@_expose
def get_vault_graph(refresh: bool = False) -> dict:
    """
    Walk OBSIDIAN_VAULT_PATH and return a graph of notes + wikilinks for the
    Brain viz. Cached in memory; pass refresh=True to rebuild.
    Returns {ok, nodes:[{id,title,path}], edges:[{src,dst}], count}.
    """
    global _WIKILINK_RE, _vault_graph_cache
    if (_vault_graph_cache is not None and not refresh
            and _vault_graph_cache.get("schema") == _VAULT_GRAPH_SCHEMA):
        return _vault_graph_cache
    try:
        import os as _os, re as _re
        from pathlib import Path as _Path
        if _WIKILINK_RE is None:
            _WIKILINK_RE = _re.compile(r"\[\[([^\]\|#]+)(?:[#\|][^\]]*)?\]\]")
        vault = _os.environ.get("OBSIDIAN_VAULT_PATH", "").strip()
        if not vault:
            return {"ok": False, "error": "OBSIDIAN_VAULT_PATH not set",
                    "nodes": [], "edges": []}
        root = _Path(vault)
        if not root.exists():
            return {"ok": False, "error": f"vault not found: {vault}",
                    "nodes": [], "edges": []}

        # Build node table keyed by lowercase title (Obsidian wikilinks are
        # title-based; multiple files with the same stem collide — first wins).
        nodes: dict[str, dict] = {}
        for md in root.rglob("*.md"):
            try:
                rel = str(md.relative_to(root)).replace("\\", "/")
                title = md.stem
                key = title.lower()
                # Top-level folder = the "category" for color grouping in the viz.
                # Notes at vault root get folder "_root_".
                parts = rel.split("/")
                folder = parts[0] if len(parts) > 1 else "_root_"
                if key not in nodes:
                    nodes[key] = {
                        "id":     key,
                        "title":  title,
                        "path":   rel,
                        "folder": folder,
                    }
            except Exception:
                continue
        # Edges: parse [[wikilinks]] -> existing nodes only
        edges: list[dict] = []
        for md in root.rglob("*.md"):
            try:
                src_key = md.stem.lower()
                if src_key not in nodes:
                    continue
                txt = md.read_text(encoding="utf-8", errors="ignore")
                for m in _WIKILINK_RE.finditer(txt):
                    dst_key = m.group(1).strip().lower()
                    if dst_key in nodes and dst_key != src_key:
                        edges.append({"src": src_key, "dst": dst_key})
            except Exception:
                continue

        _vault_graph_cache = {
            "ok": True,
            "schema": _VAULT_GRAPH_SCHEMA,
            "nodes": list(nodes.values()),
            "edges": edges,
            "count": len(nodes),
        }
        return _vault_graph_cache
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "nodes": [], "edges": []}


@_expose
def run_team_query(goal: str) -> dict:
    """
    Run a goal through the SPECIALIST TEAM (Orchestrator plans -> specialists
    execute sequentially -> Critic reviews). The plan and every tool call are
    gated through the safety_catch approval modal. Returns
    {ok, goal, plan, results, critique, revised, error}.

    Background thread + generous timeout — the team runs several agents.
    """
    if not goal or not goal.strip():
        return {"ok": False, "error": "empty goal"}

    set_swarm_state("ALBEDO_CORE", "active")
    out: dict = {}

    def _run() -> None:
        try:
            from albedo.agent_team import run_team
            res = run_team(goal.strip())
            out.update(res)
            out["ok"] = res.get("error") is None
            set_swarm_state("ALBEDO_CORE",
                            "standby" if out["ok"] else "error")
        except Exception as exc:                                    # noqa: BLE001
            out["ok"] = False
            out["error"] = f"{type(exc).__name__}: {exc}"
            set_swarm_state("ALBEDO_CORE", "error")

    t = threading.Thread(target=_run, daemon=True, name="team-query")
    t.start()
    t.join(timeout=600)   # team runs multiple agents — generous cap

    if t.is_alive():
        set_swarm_state("ALBEDO_CORE", "error")
        return {"ok": False, "error": "team timeout (600 s)"}
    return out


@_expose
def get_team_roles() -> dict:
    """Return the team roster + each role's tools + current provider mapping.
    Powers a future TEAM tab in Mission Control."""
    try:
        from albedo import agent_team, providers
        roles = {
            name: {
                "tools": spec.tool_names,
                "provider": (_read_settings_dict().get("agent_roles", {}).get(name)
                             or spec.default_provider or "(global)"),
            }
            for name, spec in agent_team.ROLES.items()
        }
        return {"ok": True, "roles": roles,
                "available": providers.available_providers()}
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@_expose
def set_team_roles(mapping: dict) -> dict:
    """Persist a {role: provider} map to settings.json agent_roles (TEAM tab)."""
    try:
        from albedo import agent_team
        if not isinstance(mapping, dict):
            return {"ok": False, "error": "mapping must be an object"}
        valid = set(agent_team.ROLES.keys())
        clean = {k: str(v).lower().strip() for k, v in mapping.items()
                 if k in valid and str(v).strip()}
        data = _read_settings_dict()
        data["agent_roles"] = {**data.get("agent_roles", {}), **clean}
        _write_settings_dict(data)
        return {"ok": True, "agent_roles": data["agent_roles"]}
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# API key management — surfaces .env values so users can add/edit/clear them
# from the SETTINGS UI instead of editing .env by hand.
# Keys live in <project>/.env, gitignored. Values never returned to JS (only
# the SET/NOT-SET status), so a chat capture wouldn't leak them.
# ---------------------------------------------------------------------------

# (provider key, friendly label, where-to-get URL)
_API_KEY_SPECS = [
    ("ANTHROPIC_API_KEY",   "Anthropic (Claude)",        "https://console.anthropic.com/settings/keys"),
    ("OPENAI_API_KEY",      "OpenAI (GPT)",              "https://platform.openai.com/api-keys"),
    ("GEMINI_API_KEY",      "Google Gemini",             "https://aistudio.google.com/app/apikey"),
    ("GROQ_API_KEY",        "Groq",                      "https://console.groq.com/keys"),
    ("TOGETHER_API_KEY",    "Together AI",               "https://api.together.xyz/settings/api-keys"),
    ("AZURE_OPENAI_KEY",    "Azure OpenAI (key)",        "https://portal.azure.com"),
    ("AZURE_OPENAI_ENDPOINT","Azure OpenAI (endpoint)",  "https://portal.azure.com"),
    ("AZURE_OPENAI_DEPLOYMENT","Azure OpenAI (deployment name)", "https://portal.azure.com"),
    ("WOLFRAM_API_KEY",     "Wolfram Alpha (math)",      "https://developer.wolframalpha.com/access"),
    ("TAVILY_API_KEY",      "Tavily (web search)",       "https://app.tavily.com/home"),
    ("DEEPGRAM_API_KEY",    "Deepgram (STT)",            "https://console.deepgram.com/"),
]


def _env_path():
    from pathlib import Path
    return Path(__file__).resolve().parent.parent.parent / ".env"


def _merge_env(updates: dict) -> bool:
    """Read .env, merge {KEY: value} updates, write back atomically.
    Removes keys whose value is empty string. Preserves comments + unrelated lines."""
    path = _env_path()
    lines = []
    if path.exists():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return False
    seen = set()
    out = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out.append(line); continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            val = updates[key]
            if val:                       # rewrite
                out.append(f"{key}={val}")
            # empty val -> drop the line
            seen.add(key)
        else:
            out.append(line)
    for key, val in updates.items():
        if key not in seen and val:
            out.append(f"{key}={val}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
        return True
    except Exception:
        return False


def _reload_env_into_process() -> None:
    """Re-load .env with override so the running process sees the new keys.
    Also reset providers' lazy clients so they pick up the new keys."""
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path(), override=True)
    except Exception:
        pass
    # swarm caches Gemini/Groq/Together clients — flush them
    try:
        from swarm import reinit_swarm_clients
        reinit_swarm_clients()
    except Exception:
        pass


@_expose
def get_api_keys_status() -> dict:
    """Return per-provider SET/NOT-SET status (never values).
    Powers the API KEYS section in Settings."""
    import os as _os
    out = []
    for env_key, label, url in _API_KEY_SPECS:
        v = (_os.environ.get(env_key, "") or "").strip()
        out.append({
            "key":   env_key,
            "label": label,
            "url":   url,
            "set":   bool(v),
            "preview": (v[:4] + "…") if v and not env_key.endswith("ENDPOINT") and not env_key.endswith("DEPLOYMENT") else (v if v else ""),
        })
    return {"ok": True, "items": out}


@_expose
def set_api_keys(updates: dict) -> dict:
    """
    Persist API keys to .env and hot-reload the process so providers/swarm see
    them immediately. Empty string clears a key.
    `updates` shape: {ENV_KEY: "value", ...}
    """
    if not isinstance(updates, dict) or not updates:
        return {"ok": False, "error": "no updates"}
    # Whitelist — only allow known keys to be written
    allowed = {spec[0] for spec in _API_KEY_SPECS}
    clean = {k: (v or "").strip() for k, v in updates.items() if k in allowed}
    if not clean:
        return {"ok": False, "error": "no recognized keys in update"}
    if not _merge_env(clean):
        return {"ok": False, "error": "failed to write .env"}
    _reload_env_into_process()
    return {"ok": True, "updated": list(clean.keys())}


@_expose
def get_brain_config() -> dict:
    """Return current brain provider/model selection + which providers have keys.
    Powers the BRAIN tab in Mission Control."""
    try:
        from albedo import providers
        return {
            "ok": True,
            "active_provider": providers.resolve_provider(),
            "active_model": providers.resolve_model(providers.resolve_provider()),
            "available": providers.available_providers(),
            "default_models": providers.DEFAULT_MODELS,
            "autonomy": _read_settings_dict().get("agent_autonomy", "approve_all"),
        }
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@_expose
def set_brain_config(provider: str = "", model: str = "", autonomy: str = "") -> dict:
    """Persist brain provider/model/autonomy to settings.json (BRAIN tab)."""
    try:
        data = _read_settings_dict()
        if provider:
            data["brain_provider"] = provider.strip().lower()
        if model:
            data["brain_model"] = model.strip()
        if autonomy in ("approve_all", "approve_destructive", "full_auto"):
            data["agent_autonomy"] = autonomy
        _write_settings_dict(data)
        return {"ok": True, "brain_provider": data.get("brain_provider", ""),
                "brain_model": data.get("brain_model", ""),
                "agent_autonomy": data.get("agent_autonomy", "approve_all")}
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


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
# Mobile relay — pairing + status endpoints exposed to JS
# ---------------------------------------------------------------------------

@_expose
def mobile_pair(relay_host: str = "albedo-relay.fly.dev") -> dict:
    """
    Register with the relay server and save the token.
    Called from the MOBILE tab when the user clicks 'Generate Pairing Code'.
    Returns {ok, token, relay_url, qr_data} where qr_data is the string
    the phone app needs (relay_url + "|" + token).
    """
    try:
        from albedo import mobile_relay as _mr
        result = _mr.pair(relay_host)
        if not result.get("ok"):
            return result
        token     = result["token"]
        relay_url = result["relay_url"]
        qr_data   = f"{relay_url}|{token}"
        # Start relay now that we have a token
        _mr.start()
        return {"ok": True, "token": token, "relay_url": relay_url, "qr_data": qr_data}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@_expose
def mobile_status() -> dict:
    """Return current relay connection status and pairing info."""
    try:
        from albedo import mobile_relay as _mr
        token     = _mr.get_token()
        relay_url = _mr.get_relay_url()
        qr_data   = f"{relay_url}|{token}" if token else ""
        return {
            "ok":        True,
            "connected": _mr.is_connected(),
            "token":     token,
            "relay_url": relay_url,
            "qr_data":   qr_data,
            "paired":    bool(token),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@_expose
def mobile_unpair() -> dict:
    """Clear the pairing token and disconnect the relay."""
    try:
        from albedo import mobile_relay as _mr
        import json
        from pathlib import Path
        settings_path = Path(__file__).resolve().parent.parent.parent / "settings.json"
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        data.pop("mobile_token", None)
        data.pop("relay_host",   None)
        settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        _mr.stop()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Safety catch — Eel approval handler
#
# When the LLM swarm wants to run a subprocess command, safety_catch.py
# calls the registered approval handler (us). We push the request to the
# JS layer via _albedo_approval_request(), then block on a threading.Event
# until the user clicks Approve or Deny in the UI modal.
#
# The JS side calls eel.approve_command(true/false) which sets the event
# and stores the result. We return the result to safety_catch.safe_run().
#
# Thread-safety: only one approval can be in-flight at a time (the LLM
# pipeline is single-threaded per query). The lock + event pair ensures
# no race between handler and approve_command.
# ---------------------------------------------------------------------------

_approval_lock   = threading.Lock()
_approval_event: "threading.Event | None"  = None
_approval_result: bool = False


def _eel_approval_handler(req: "Any") -> bool:
    """
    Eel-backed approval handler for safety_catch.

    Sends the pending command to the JS modal and blocks until the user
    responds (or 60 s elapses, defaulting to deny).
    """
    global _approval_event, _approval_result
    evt = threading.Event()
    with _approval_lock:
        _approval_event  = evt
        _approval_result = False   # default: deny on timeout

    # Push to JS — _albedo_approval_request is registered in chat.js
    try:
        import eel as _eel
        _eel._albedo_approval_request(req.as_dict())()
    except Exception as exc:
        print(f"[bridge] approval push failed: {exc}")
        with _approval_lock:
            _approval_event = None
        return False

    # Block until JS responds or 60 s timeout
    evt.wait(timeout=60.0)

    with _approval_lock:
        result           = _approval_result
        _approval_event  = None
    return result


@_expose
def approve_command(approved: bool) -> dict:
    """
    Called from JS when the user clicks Approve or Deny on the safety modal.
    Unblocks the approval handler thread with the user's decision.
    """
    global _approval_result, _approval_event
    with _approval_lock:
        _approval_result = bool(approved)
        evt = _approval_event
    if evt is not None:
        evt.set()
    return {"ok": True}


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
        # Live-swap inference model + wake-word model when persona changes
        if key == "active_persona" and isinstance(value, str):
            notify_persona_change(value)
            # Reload OWW so only the new persona's wake word is active
            try:
                from albedo.audio.wakeword import reset_wake_model
                reset_wake_model()
            except Exception:
                pass
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
def get_dream_file_suggestions() -> dict:
    """
    Return pending file-move suggestions the dream cycle proposed but did NOT
    apply. Surfaced at session start so the user decides. Each item:
    {src, dest, category, timestamp}.
    """
    try:
        from albedo.dream.file_organizer import get_pending_suggestions
        moves = get_pending_suggestions()
        return {"ok": True, "count": len(moves), "moves": moves}
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@_expose
def apply_dream_file_suggestions() -> dict:
    """User approved the dream-cycle move suggestions — execute them now."""
    try:
        from albedo.dream.file_organizer import apply_suggestions
        applied = apply_suggestions()   # loads pending from disk, moves, clears
        return {"ok": True, "applied": len(applied),
                "moves": [m.as_dict() for m in applied]}
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@_expose
def discard_dream_file_suggestions() -> dict:
    """User declined the dream-cycle move suggestions — clear, move nothing."""
    try:
        from albedo.dream.file_organizer import discard_suggestions
        n = discard_suggestions()
        return {"ok": True, "discarded": n}
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
