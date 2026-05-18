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

    actual_port = _free_port(port)

    # mode="chrome" gives app-mode windowing (no URL bar, no tabs).
    # Falls through to default browser if Chrome/Edge aren't on PATH.
    try:
        eel.start(
            "index.html",
            size=(1280, 900),
            port=actual_port,
            mode=(mode if mode is not None else "chrome"),
            block=True,
            shutdown_delay=0.5,
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
                size=(1280, 900),
                port=actual_port,
                mode="default",
                block=True,
                shutdown_delay=0.5,
            )
        except (SystemExit, KeyboardInterrupt):
            pass
