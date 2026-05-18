"""
comm_mode.py — voice input mode + wake-word arm state.

Two pieces of UI-facing state, kept as a single source of truth so the
Tk GUI (v2.x) and the forthcoming Eel UI (v3.x) bind to the same backend
without duplicating logic.

CommMode controls how the MIC button captures audio:
    PUSH_TO_TALK -- record while the button is held down (press → release)
    LATCH        -- click once to start, click again to stop (the v2.0.2
                    default behaviour)

WakeState controls whether the background wake-word listener thread is
running:
    ARMED        -- listener active, waiting for the configured wake word
                    to trigger a recording cycle automatically
    DISARMED     -- listener stopped; only the MIC button starts recording

Both pieces persist to ``settings.json`` next to the install root so the
user's choice survives a restart. The same settings.json that gui.py
already reads/writes — comm_mode.py loads/saves cooperatively, holding
the file briefly on each write.

Observer pattern
----------------
UIs subscribe via ``on_mode_change(callback)`` and ``on_wake_change(callback)``
so they can re-render the MIC button visual state or arm/disarm the
background listener without polling. Callbacks fire on the thread that
called set_mode / set_wake_state — UIs should marshal back to their own
event loop if needed (Tk uses ``widget.after(0, ...)``).

Public API
----------
    class CommMode(str, Enum)         PUSH_TO_TALK | LATCH
    class WakeState(str, Enum)        ARMED | DISARMED

    get_mode() -> CommMode
    set_mode(m: CommMode) -> CommMode      # returns the new state
    get_wake_state() -> WakeState
    set_wake_state(s: WakeState) -> WakeState

    on_mode_change(fn) -> None             # add an observer callback
    on_wake_change(fn) -> None
    clear_observers() -> None              # for tests + tear-down

    settings_path() -> Path                # which file holds the persisted state
    reload() -> None                       # discard cached state, re-read disk
"""
from __future__ import annotations

import json
import threading
from enum import Enum
from pathlib import Path
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT          = Path(__file__).resolve().parent.parent.parent
_SETTINGS_FILE = _ROOT / "settings.json"

# Keys under which comm_mode persists into settings.json. Prefixed so they
# never collide with gui.py's own keys.
_KEY_MODE = "comm_mode"
_KEY_WAKE = "wake_state"


# ---------------------------------------------------------------------------
# Enums — string values so JSON serialisation is human-readable
# ---------------------------------------------------------------------------

class CommMode(str, Enum):
    PUSH_TO_TALK = "ptt"
    LATCH        = "latch"


class WakeState(str, Enum):
    ARMED    = "armed"
    DISARMED = "disarmed"


# ---------------------------------------------------------------------------
# Defaults — preserve v2.0.2 behaviour for users who never touch the toggles
# ---------------------------------------------------------------------------

_DEFAULT_MODE = CommMode.LATCH       # current MIC button is already click-to-toggle
_DEFAULT_WAKE = WakeState.DISARMED   # don't surprise users with always-on listening


# ---------------------------------------------------------------------------
# Internal state (guarded by _lock)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_mode: Optional[CommMode] = None
_wake: Optional[WakeState] = None

_mode_observers: list[Callable[[CommMode], None]] = []
_wake_observers: list[Callable[[WakeState], None]] = []


# ---------------------------------------------------------------------------
# Settings file I/O — load/save cooperatively with gui.py
# ---------------------------------------------------------------------------

def _read_settings() -> dict:
    """Return the current settings.json contents, or {} if the file is missing/corrupt."""
    try:
        return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_settings(merged: dict) -> None:
    """Atomically write the merged settings dict. Best-effort — never raises."""
    try:
        _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS_FILE.write_text(
            json.dumps(merged, indent=2), encoding="utf-8")
    except OSError:
        pass


def _coerce_mode(raw) -> CommMode:
    if isinstance(raw, CommMode):
        return raw
    if isinstance(raw, str):
        for m in CommMode:
            if m.value == raw.strip().lower():
                return m
    return _DEFAULT_MODE


def _coerce_wake(raw) -> WakeState:
    if isinstance(raw, WakeState):
        return raw
    if isinstance(raw, str):
        for w in WakeState:
            if w.value == raw.strip().lower():
                return w
    return _DEFAULT_WAKE


def _load_from_disk() -> None:
    """Populate _mode + _wake from settings.json, falling back to defaults."""
    global _mode, _wake
    data = _read_settings()
    _mode = _coerce_mode(data.get(_KEY_MODE))
    _wake = _coerce_wake(data.get(_KEY_WAKE))


def _persist() -> None:
    """Merge current state into settings.json, preserving other keys."""
    data = _read_settings()
    data[_KEY_MODE] = (_mode or _DEFAULT_MODE).value
    data[_KEY_WAKE] = (_wake or _DEFAULT_WAKE).value
    _write_settings(data)


def _ensure_loaded() -> None:
    """Lazy first-call init — no module-level disk read at import time."""
    if _mode is None or _wake is None:
        _load_from_disk()


# ---------------------------------------------------------------------------
# Public API — read state
# ---------------------------------------------------------------------------

def get_mode() -> CommMode:
    with _lock:
        _ensure_loaded()
        return _mode or _DEFAULT_MODE


def get_wake_state() -> WakeState:
    with _lock:
        _ensure_loaded()
        return _wake or _DEFAULT_WAKE


# ---------------------------------------------------------------------------
# Public API — write state (notifies observers + persists)
# ---------------------------------------------------------------------------

def set_mode(m: CommMode) -> CommMode:
    """Update the comm mode. Idempotent. Fires observers only on actual change."""
    global _mode
    if not isinstance(m, CommMode):
        m = _coerce_mode(m)

    fired = False
    callbacks: list = []
    with _lock:
        _ensure_loaded()
        if _mode != m:
            _mode = m
            _persist()
            callbacks = list(_mode_observers)
            fired = True

    if fired:
        for cb in callbacks:
            try:
                cb(m)
            except Exception as exc:                                # noqa: BLE001
                # An observer crashing must not break the setter.
                print(f"[comm_mode] mode observer error: {exc}")
    return m


def set_wake_state(s: WakeState) -> WakeState:
    """Update the wake-word arm state. Idempotent. Fires observers on change."""
    global _wake
    if not isinstance(s, WakeState):
        s = _coerce_wake(s)

    fired = False
    callbacks: list = []
    with _lock:
        _ensure_loaded()
        if _wake != s:
            _wake = s
            _persist()
            callbacks = list(_wake_observers)
            fired = True

    if fired:
        for cb in callbacks:
            try:
                cb(s)
            except Exception as exc:                                # noqa: BLE001
                print(f"[comm_mode] wake observer error: {exc}")
    return s


# ---------------------------------------------------------------------------
# Observer registration
# ---------------------------------------------------------------------------

def on_mode_change(fn: Callable[[CommMode], None]) -> None:
    """Register a callback fired whenever set_mode() changes the state."""
    with _lock:
        if fn not in _mode_observers:
            _mode_observers.append(fn)


def on_wake_change(fn: Callable[[WakeState], None]) -> None:
    """Register a callback fired whenever set_wake_state() changes the state."""
    with _lock:
        if fn not in _wake_observers:
            _wake_observers.append(fn)


def clear_observers() -> None:
    """Drop all registered observers. Used by tests + window teardown."""
    with _lock:
        _mode_observers.clear()
        _wake_observers.clear()


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def settings_path() -> Path:
    return _SETTINGS_FILE


def reload() -> None:
    """Discard in-memory state and re-read settings.json."""
    global _mode, _wake
    with _lock:
        _mode = None
        _wake = None


# Test helper
def _reset_for_tests() -> None:
    global _mode, _wake
    with _lock:
        _mode = None
        _wake = None
        _mode_observers.clear()
        _wake_observers.clear()
