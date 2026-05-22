"""
idle_monitor.py — System idle detection for autonomous dream cycle triggering.

Uses Windows GetLastInputInfo (ctypes, zero extra deps) to measure seconds
since the last keyboard or mouse event.  When idle time exceeds the configured
threshold the module calls the registered callback and enters a cooldown so the
dream cycle isn't re-triggered immediately when the user returns.

Public API
----------
    start(on_idle_callback, on_return_callback=None)
        Begin monitoring in a daemon thread.
    stop()
        Stop the monitor thread cleanly.
    get_idle_seconds() -> float
        Instantaneous idle duration query (safe to call from any thread).
    is_monitoring() -> bool

Configuration (.env)
--------------------
    IDLE_THRESHOLD_MINUTES   Minutes of inactivity before dream fires (default 20)
    IDLE_POLL_INTERVAL_S     How often the monitor checks (default 30 s)
    IDLE_COOLDOWN_MINUTES    Minimum gap between dream cycles (default 120)
"""
from __future__ import annotations

import ctypes
import threading
import time
from typing import Callable, Optional

from albedo.config import (
    IDLE_THRESHOLD_MINUTES,
    IDLE_POLL_INTERVAL_S,
    IDLE_COOLDOWN_MINUTES,
)

# ---------------------------------------------------------------------------
# Windows idle query
# ---------------------------------------------------------------------------

class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def get_idle_seconds() -> float:
    """Seconds since last keyboard or mouse event (Windows only)."""
    try:
        lii = _LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(lii)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
        millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
        return max(0.0, millis / 1000.0)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Monitor state
# ---------------------------------------------------------------------------

_thread:          Optional[threading.Thread] = None
_stop_event:      threading.Event             = threading.Event()
_on_idle:         Optional[Callable]          = None
_on_return:       Optional[Callable]          = None
_last_dream_time: float                       = 0.0
_currently_idle:  bool                        = False
_lock:            threading.Lock              = threading.Lock()


def is_monitoring() -> bool:
    return _thread is not None and _thread.is_alive()


def _monitor_loop() -> None:
    global _last_dream_time, _currently_idle

    threshold_s = IDLE_THRESHOLD_MINUTES * 60
    cooldown_s  = IDLE_COOLDOWN_MINUTES  * 60

    print(f"[idle_monitor] Watching — threshold {IDLE_THRESHOLD_MINUTES}m, "
          f"cooldown {IDLE_COOLDOWN_MINUTES}m, poll {IDLE_POLL_INTERVAL_S}s")

    while not _stop_event.is_set():
        idle_s = get_idle_seconds()
        now    = time.time()

        with _lock:
            was_idle = _currently_idle

            if idle_s >= threshold_s:
                # User is idle
                if not was_idle:
                    _currently_idle = True
                    # Only fire if outside cooldown window
                    since_last = now - _last_dream_time
                    if since_last >= cooldown_s:
                        print(f"[idle_monitor] Idle threshold reached "
                              f"({idle_s:.0f}s). Firing dream cycle.")
                        _last_dream_time = now
                        if _on_idle:
                            threading.Thread(
                                target=_on_idle, daemon=True,
                                name="dream-cycle").start()
                    else:
                        remaining = (cooldown_s - since_last) / 60
                        print(f"[idle_monitor] Idle but in cooldown "
                              f"({remaining:.0f}m remaining).")
            else:
                # User is active
                if was_idle:
                    _currently_idle = False
                    print("[idle_monitor] Activity resumed.")
                    if _on_return:
                        threading.Thread(
                            target=_on_return, daemon=True,
                            name="dream-return").start()

        _stop_event.wait(timeout=IDLE_POLL_INTERVAL_S)


def start(
    on_idle_callback: Callable,
    on_return_callback: Optional[Callable] = None,
) -> None:
    """Start the idle monitor daemon thread."""
    global _thread, _on_idle, _on_return
    if is_monitoring():
        return
    _on_idle   = on_idle_callback
    _on_return = on_return_callback
    _stop_event.clear()
    _thread = threading.Thread(
        target=_monitor_loop, daemon=True, name="idle-monitor")
    _thread.start()


def stop() -> None:
    """Stop the idle monitor."""
    _stop_event.set()
