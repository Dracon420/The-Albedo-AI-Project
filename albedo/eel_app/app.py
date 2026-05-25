"""
app.py — Eel UI launcher.

Initialises the bridge functions, points Eel at the ``web/`` directory,
and launches a Chromium-based app-mode browser window pointed at
``index.html``. When Chrome / Edge isn't available, falls back to the
user's default browser (less polished but functional).

The launcher is called from ``main.py`` / ``gui.py`` when the user has
set ``ALBEDO_UI=eel`` in their .env, so the original Tk GUI is still
available to anyone who doesn't opt in.

Public API
----------
    run(port=8088, mode="chrome")        # blocks until window closes
    is_eel_available() -> bool
"""
from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Optional


_ROOT    = Path(__file__).resolve().parent.parent.parent
_WEB_DIR = _ROOT / "web"


def _full_screen_size() -> tuple[int, int]:
    """
    Return (w, h) matching the primary display so the Eel window opens
    maximized. Falls back to 1920 x 1080 if screen detection fails.
    """
    # Try tkinter first — stdlib, cross-platform, no extra deps.
    try:
        import tkinter as _tk
        root = _tk.Tk()
        root.withdraw()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.destroy()
        if sw > 0 and sh > 0:
            return (sw, sh)
    except Exception:
        pass

    # Windows fallback via ctypes (in case tkinter is missing).
    try:
        import ctypes
        u = ctypes.windll.user32
        u.SetProcessDPIAware()
        sw, sh = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
        if sw > 0 and sh > 0:
            return (sw, sh)
    except Exception:
        pass

    return (1920, 1080)


def is_eel_available() -> bool:
    """True when the eel package is importable. Cheap; safe to call repeatedly."""
    try:
        import eel  # noqa: F401
        return True
    except ImportError:
        return False


def _free_port(preferred: int) -> int:
    """Return ``preferred`` if it's free, else any OS-assigned port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", preferred))
        port = s.getsockname()[1]
        s.close()
        return port
    except OSError:
        s.close()
        # preferred is in use — let the OS pick
        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s2.bind(("127.0.0.1", 0))
        port = s2.getsockname()[1]
        s2.close()
        return port


def run(port: int = 8088, mode: Optional[str] = None) -> None:
    """
    Launch the Eel desktop window.

    port  -- HTTP port for the Eel server. Defaults to 8088. Falls back
             to an OS-assigned port if 8088 is busy.
    mode  -- browser mode for eel.start(). Defaults to ``"chrome"`` which
             gives an app-mode window with no chrome (frameless). Set to
             ``None`` for the user's default browser.

    Blocks until the user closes the window. Returns cleanly to the
    caller so any teardown (TTS stop, audio stream close, etc.) can
    happen in main()/gui.main().
    """
    if not is_eel_available():
        raise RuntimeError(
            "eel package not installed. Run 'pip install eel' in your "
            "Albedo venv, then re-launch."
        )
    if not _WEB_DIR.is_dir():
        raise RuntimeError(
            f"web/ frontend directory missing at {_WEB_DIR}. Reinstall "
            f"or check that the install bundle is complete."
        )

    import eel

    # Importing the bridge applies @eel.expose to every public function.
    # Must happen AFTER eel.init() or before? Eel collects exposed
    # functions from the active interpreter at start() time regardless,
    # so order doesn't matter — do init() first for clarity.
    eel.init(str(_WEB_DIR))
    from albedo.eel_app import bridge       # noqa: F401  — registers @eel.expose

    # ── Wake-word listener — starts/stops when the WAKE button is toggled ──
    # The UI calls set_wake_state("armed"/"disarmed") which fires comm_mode
    # observers. We register one here that actually starts/stops the Vosk
    # background listener so clicking WAKE does something.
    try:
        import threading as _threading
        from albedo.audio.capture import AudioStream
        from albedo.audio import wakeword as _ww
        from albedo.audio.comm_mode import on_wake_change, WakeState

        _wake_stream: AudioStream | None = None
        _wake_stop:   _threading.Event | None = None
        _wake_lock = _threading.Lock()

        def _on_mic_wakeword() -> None:
            """Called by the listener thread each time a wake word fires."""
            print("[eel_app] Wake word fired — ready for voice input.")

        def _wake_observer(state: WakeState) -> None:
            nonlocal _wake_stream, _wake_stop
            with _wake_lock:
                if state == WakeState.ARMED:
                    if _wake_stop and not _wake_stop.is_set():
                        return  # already running
                    try:
                        _wake_stream = AudioStream()
                        _wake_stream.start()
                        _wake_stop = _ww.start_background_listener(
                            _wake_stream, _on_mic_wakeword
                        )
                        print("[eel_app] Wake-word listener ARMED.")
                    except Exception as exc:
                        print(f"[eel_app] Wake-word listener failed to start: {exc}")
                else:
                    if _wake_stop:
                        _wake_stop.set()
                        _wake_stop = None
                    if _wake_stream:
                        try:
                            _wake_stream.stop()
                        except Exception:
                            pass
                        _wake_stream = None
                    print("[eel_app] Wake-word listener DISARMED.")

        on_wake_change(_wake_observer)
        print("[eel_app] Wake-word observer registered.")
    except Exception as exc:
        print(f"[eel_app] Wake-word setup failed (non-fatal): {exc}")

    # Start the idle monitor — fires the dream cycle after IDLE_THRESHOLD_MINUTES
    # of no keyboard/mouse activity.
    try:
        from albedo import idle_monitor
        from albedo.dream import orchestrator as _dream

        def _on_idle() -> None:
            _dream.start_dream(status_cb=bridge._dream_status_push)

        def _on_return() -> None:
            _dream.interrupt_dream()

        idle_monitor.start(on_idle_callback=_on_idle, on_return_callback=_on_return)
        print("[eel_app] Idle monitor armed.")
    except Exception as exc:
        print(f"[eel_app] Idle monitor failed to start: {exc}")

    actual_port = _free_port(port)
    win_size = _full_screen_size()
    print(f"[eel_app] Window size: {win_size[0]} x {win_size[1]} "
          f"(full-screen auto-sized)")

    # mode="chrome" gives app-mode windowing (no URL bar, no tabs).
    # Falls through to default browser if Chrome/Edge aren't on PATH.
    try:
        eel.start(
            "index.html",
            size=win_size,
            port=actual_port,
            mode=(mode if mode is not None else "chrome"),
            block=True,
            shutdown_delay=0.5,
            cmdline_args=["--start-maximized"],
        )
    except (SystemExit, KeyboardInterrupt):
        # eel raises SystemExit when the window closes — treat as clean exit.
        pass
    except OSError as exc:
        # Most often: Chrome isn't installed. Retry with default browser.
        if mode is None or mode == "default":
            raise
        print(f"[eel_app] Chrome launch failed ({exc}); retrying with default browser.")
        try:
            eel.start(
                "index.html",
                size=win_size,
                port=actual_port,
                mode="default",
                block=True,
                shutdown_delay=0.5,
            )
        except (SystemExit, KeyboardInterrupt):
            pass
