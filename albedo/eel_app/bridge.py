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

import threading
import time
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
