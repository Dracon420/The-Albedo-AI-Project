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
import subprocess
from pathlib import Path
from typing import Optional


_ROOT    = Path(__file__).resolve().parent.parent.parent
_WEB_DIR = _ROOT / "web"

# Module-level port — set once eel.start() is called so widget launcher can use it.
_active_port: int = 8088


# ---------------------------------------------------------------------------
# Widget + mode Eel functions — exposed before eel.init() via late-import
# so they're available to any connected browser window (main + widget).
# ---------------------------------------------------------------------------

def _expose_widget_fns() -> None:
    """Register widget-related @eel.expose functions. Called once in run()."""
    try:
        import eel as _eel

        def _find_chrome() -> "str | None":
            for p in (
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            ):
                if Path(p).exists():
                    return p
            return None

        # Per-panel default size + spawn position (x, y, w, h).
        _PANEL_GEOMETRY = {
            "widget": (30, 80, 380, 560),
            "chat":   (40, 60, 520, 720),
            "brain":  (580, 60, 440, 560),
            "team":   (580, 60, 560, 720),
        }
        _PANEL_PAGES = {
            "widget": "widget.html",
            "chat":   "chat_window.html",
            "brain":  "brain_window.html",
            "team":   "team_window.html",
        }

        @_eel.expose
        def open_panel_window(panel: str = "widget") -> None:
            """
            Launch a detachable panel (chat / brain / team / widget) in its own
            frameless Chrome --app= window. Generalizes the old widget launcher.
            """
            panel = (panel or "widget").lower().strip()
            page = _PANEL_PAGES.get(panel)
            if page is None:
                print(f"[eel_app] Unknown panel: {panel!r}")
                return
            port = _active_port
            url  = f"http://127.0.0.1:{port}/{page}"
            exe  = _find_chrome()
            if not exe:
                print("[eel_app] Chrome/Edge not found — cannot open panel.")
                return
            x, y, w, h = _PANEL_GEOMETRY.get(panel, _PANEL_GEOMETRY["widget"])
            try:
                subprocess.Popen([
                    exe,
                    f"--app={url}",
                    f"--window-size={w},{h}",
                    f"--window-position={x},{y}",
                    "--disable-extensions",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disk-cache-size=1",
                    "--media-cache-size=1",
                ])
                print(f"[eel_app] Panel '{panel}' window opened -> {url}")
            except Exception as exc:
                print(f"[eel_app] Panel '{panel}' launch failed: {exc}")

        @_eel.expose
        def open_widget_window() -> None:
            """Back-compat alias — opens the compact widget overlay."""
            open_panel_window("widget")

        @_eel.expose
        def snap_windows(preset: str = "left-stack") -> dict:
            """
            Arrange Albedo's own windows into a preset layout using win32. Finds
            windows by their <title> (Chat/Brain/Team/Mission Control), so only
            open ones are moved; missing panels are skipped.

            Presets: 'left-stack' (Chat left half; Brain top-right; Team
            bottom-right), 'thirds' (three columns), 'focus-chat' (Chat ~60% left,
            Brain+Team stacked right).
            """
            try:
                import win32gui, win32api, win32con
            except Exception as exc:
                return {"ok": False, "error": f"win32 unavailable: {exc}"}

            # Work area (excludes taskbar) via SPI_GETWORKAREA. win32gui's
            # SystemParametersInfo doesn't support action 48 in this build, so use
            # ctypes directly (reliable across pywin32 versions).
            try:
                import ctypes
                from ctypes import wintypes
                _r = wintypes.RECT()
                if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(_r), 0):
                    wx, wy, wr, wb = _r.left, _r.top, _r.right, _r.bottom
                    W, H = wr - wx, wb - wy
                else:
                    raise OSError("SystemParametersInfoW failed")
            except Exception:
                wx, wy = 0, 0
                W = win32api.GetSystemMetrics(0)
                H = win32api.GetSystemMetrics(1)

            # Title substrings that identify each panel window.
            title_map = {
                "chat":   ("ALBEDO // CHAT", "CHAT"),
                "brain":  ("ALBEDO // BRAIN", "BRAIN"),
                "team":   ("ALBEDO // TEAM", "TEAM"),
                "main":   ("MISSION CONTROL",),
            }

            def _find(substrs):
                found = []
                def _cb(hwnd, _):
                    if not win32gui.IsWindowVisible(hwnd):
                        return True
                    t = win32gui.GetWindowText(hwnd) or ""
                    tu = t.upper()
                    if any(s.upper() in tu for s in substrs):
                        found.append(hwnd)
                    return True
                win32gui.EnumWindows(_cb, None)
                return found[0] if found else None

            hwnds = {k: _find(v) for k, v in title_map.items()}

            def _place(hwnd, x, y, w, h):
                if not hwnd:
                    return False
                win32gui.SetWindowPos(hwnd, win32con.HWND_TOP,
                                      int(x), int(y), int(w), int(h),
                                      win32con.SWP_SHOWWINDOW)
                return True

            moved = []
            if preset == "thirds":
                cw = W // 3
                for i, key in enumerate(("chat", "brain", "team")):
                    if _place(hwnds[key], wx + i * cw, wy, cw, H):
                        moved.append(key)
            elif preset == "focus-chat":
                if _place(hwnds["chat"], wx, wy, int(W * 0.6), H):
                    moved.append("chat")
                if _place(hwnds["brain"], wx + int(W * 0.6), wy, int(W * 0.4), H // 2):
                    moved.append("brain")
                if _place(hwnds["team"], wx + int(W * 0.6), wy + H // 2, int(W * 0.4), H // 2):
                    moved.append("team")
            else:  # left-stack (default)
                if _place(hwnds["chat"], wx, wy, W // 2, H):
                    moved.append("chat")
                if _place(hwnds["brain"], wx + W // 2, wy, W // 2, H // 2):
                    moved.append("brain")
                if _place(hwnds["team"], wx + W // 2, wy + H // 2, W // 2, H // 2):
                    moved.append("team")

            print(f"[eel_app] snap '{preset}' arranged: {moved}")
            return {"ok": True, "preset": preset, "arranged": moved}

        # --- OS-level fullscreen state ---
        _fs_saved = {}   # {"hwnd": int, "style": int, "placement": tuple}

        @_eel.expose
        def set_window_mode(mode: str) -> None:
            """
            Called by modes.js when switching FULL / WIN / WIDGET.
            Uses win32gui to go borderless fullscreen; requestFullscreen()
            is silently rejected in Chrome --app= mode on Windows.
            GetForegroundWindow() is reliable here: the user just clicked
            a button inside Chrome, so Chrome is still the active window
            when this WebSocket callback fires.
            """
            import win32gui, win32con, win32api
            nonlocal _fs_saved

            print(f"[eel_app] View mode → {mode}")

            if mode == "fullscreen":
                hwnd = win32gui.GetForegroundWindow()
                if not hwnd:
                    print("[eel_app] fullscreen: GetForegroundWindow=0, skipping.")
                    return
                style     = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
                placement = win32gui.GetWindowPlacement(hwnd)
                _fs_saved = {"hwnd": hwnd, "style": style, "placement": placement}

                # Strip title bar + resize border → borderless
                new_style = style & ~(win32con.WS_CAPTION | win32con.WS_THICKFRAME)
                win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, new_style)

                sw = win32api.GetSystemMetrics(0)
                sh = win32api.GetSystemMetrics(1)
                win32gui.SetWindowPos(
                    hwnd, win32con.HWND_TOP, 0, 0, sw, sh,
                    win32con.SWP_FRAMECHANGED
                )
                print(f"[eel_app] Borderless fullscreen → {sw}x{sh} hwnd={hwnd}")

            elif _fs_saved.get("hwnd"):
                hwnd = _fs_saved["hwnd"]
                win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, _fs_saved["style"])
                win32gui.SetWindowPlacement(hwnd, _fs_saved["placement"])
                win32gui.SetWindowPos(
                    hwnd, win32con.HWND_TOP, 0, 0, 0, 0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_FRAMECHANGED
                )
                _fs_saved = {}
                print("[eel_app] Window restored to normal.")

        @_eel.expose
        def run_pipeline(query: str) -> str:
            """
            Execute the Albedo pipeline for a query — used by widget.html's chat.
            Returns the text response.
            """
            try:
                from albedo.pipeline import run as _run
                return _run(query) or ""
            except Exception as exc:
                print(f"[eel_app] run_pipeline error: {exc}")
                return f"[ERR] {exc}"

        @_eel.expose
        def widget_mic_press() -> None:
            """Placeholder for widget MIC button — hooks into the same PTT flow."""
            print("[eel_app] Widget MIC pressed — not yet wired to capture.")

    except Exception as exc:
        print(f"[eel_app] Widget fn registration failed (non-fatal): {exc}")


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

    global _active_port

    import eel

    # Importing the bridge applies @eel.expose to every public function.
    # Must happen AFTER eel.init() or before? Eel collects exposed
    # functions from the active interpreter at start() time regardless,
    # so order doesn't matter — do init() first for clarity.
    eel.init(str(_WEB_DIR))
    from albedo.eel_app import bridge       # noqa: F401  — registers @eel.expose

    # Wire safety_catch to the Eel UI approval handler so command-approval
    # prompts appear in the modal rather than the console.
    try:
        from albedo.safety_catch import set_approval_handler
        set_approval_handler(bridge._eel_approval_handler)
        print("[eel_app] safety_catch wired to Eel UI approval handler.")
    except Exception as _exc:
        print(f"[eel_app] safety_catch handler registration failed (non-fatal): {_exc}")

    # Register widget + mode functions
    _expose_widget_fns()

    # ── Mobile relay — start in background if token is already configured ──
    try:
        from albedo import mobile_relay as _mr
        if _mr.get_token():
            _mr.start()
            print("[eel_app] Mobile relay started.")
        else:
            print("[eel_app] Mobile relay: no token yet — pair from MOBILE tab first.")
    except Exception as _exc:
        print(f"[eel_app] Mobile relay start failed (non-fatal): {_exc}")

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

        def _push_chat(kind: str, text: str) -> None:
            """Push a line to the JS chat feed from any thread."""
            try:
                import eel as _eel
                _eel._albedo_chat_push(kind, text)()
            except Exception:
                pass

        def _set_send_stop(is_stop: bool) -> None:
            """Toggle the SEND button to STOP (or back) in the JS UI."""
            try:
                import eel as _eel
                _eel._albedo_send_stop(is_stop)()
            except Exception:
                pass

        def _transcribe_wake(audio) -> str:
            """
            Transcribe wake-word follow-up audio.
            Uses Groq Whisper API when GROQ_API_KEY is set (far more accurate
            than Vosk small for short voice queries).  Falls back to Vosk.
            """
            import os as _os, io as _io, wave as _wave
            import numpy as _np
            groq_key = _os.environ.get("GROQ_API_KEY", "").strip()
            if groq_key:
                try:
                    import groq as _groq
                    client = _groq.Groq(api_key=groq_key)
                    # Convert float32 audio → 16kHz mono WAV bytes
                    pcm = (_np.clip(audio, -1.0, 1.0) * 32767).astype(_np.int16)
                    buf = _io.BytesIO()
                    with _wave.open(buf, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(16000)
                        wf.writeframes(pcm.tobytes())
                    buf.seek(0)
                    result = client.audio.transcriptions.create(
                        model="whisper-large-v3-turbo",
                        file=("wake.wav", buf, "audio/wav"),
                        language="en",
                    )
                    text = (result.text or "").strip()
                    if text:
                        print(f"[eel_app] Groq Whisper: {text!r}")
                        return text
                except Exception as _exc:
                    print(f"[eel_app] Groq Whisper failed, falling back to Vosk: {_exc}")
            # Fallback: Vosk
            from albedo.audio.stt import transcribe as _vosk_transcribe
            return _vosk_transcribe(audio).strip()

        def _on_mic_wakeword() -> None:
            """
            Called by the wakeword listener thread each time a wake word fires.

            Full response cycle:
              1. Play the wake-ack phrase ("Yes?") — skipped if audio muted
              2. Record the follow-up utterance via VAD
              3. Transcribe via Groq Whisper (→ Vosk fallback)
              4. Route through the pipeline (cloud → Ollama fallback)
              5. Speak the reply — skipped if audio muted
              6. Push user text + reply into the Eel chat feed
              7. Cooldown: drain mic buffer so TTS audio can't re-trigger wake
            """
            from albedo.eel_app.bridge import is_audio_muted

            word = _ww.get_last_detected_word()
            print(f"[eel_app] Wake word '{word}' fired — capturing utterance.")
            _push_chat("system", f"[WAKE] '{word.upper()}' detected — listening…")

            # 1. Play acknowledgement phrase
            if not is_audio_muted():
                try:
                    import os as _os
                    ack = _os.environ.get("WAKE_ACK_PHRASE", "Yes?").strip()
                    if ack:
                        from albedo.audio.tts import speak
                        speak(ack)
                except Exception as _exc:
                    print(f"[eel_app] Wake ack TTS failed: {_exc}")

            # 1b. Brief gap so user can start speaking after hearing the ack.
            #     Also drains the mic ring-buffer to discard any ack echo that
            #     leaked in before the user's voice arrives.
            import time as _time
            _time.sleep(0.35)
            with _wake_lock:
                _s_drain = _wake_stream
            if _s_drain:
                try:
                    _s_drain.drain()
                except Exception:
                    pass

            # 2. Record follow-up utterance
            audio = None
            try:
                from albedo.audio.capture import record_utterance
                with _wake_lock:
                    stream_ref = _wake_stream
                if stream_ref is not None:
                    audio = record_utterance(stream_ref)
            except Exception as _exc:
                print(f"[eel_app] Wake record failed: {_exc}")

            if audio is None or len(audio) == 0:
                print("[eel_app] Wake: no audio captured after wake word.")
                return

            # 3. Transcribe (Groq Whisper → Vosk fallback)
            text = ""
            try:
                text = _transcribe_wake(audio)
            except Exception as _exc:
                print(f"[eel_app] Wake transcribe failed: {_exc}")

            if not text:
                print("[eel_app] Wake: nothing transcribed.")
                return

            print(f"[eel_app] Wake utterance: {text!r}")
            _push_chat("user", f"> {text}")

            # Signal UI: switch SEND → STOP
            _set_send_stop(True)

            # 4. Route through pipeline
            reply = ""
            try:
                from albedo.pipeline import run as _pipeline_run
                reply = _pipeline_run(text)
            except Exception as _exc:
                print(f"[eel_app] Wake pipeline failed: {_exc}")
                reply = "Sorry, I ran into an error processing that."

            _set_send_stop(False)

            if not reply:
                return

            # Push reply to chat feed
            try:
                from albedo.eel_app.bridge import get_active_persona_name
                persona = get_active_persona_name().get("name", "ALBEDO")
                _push_chat("albedo", f"{persona}  {reply}")
            except Exception:
                pass

            # 5. Speak reply
            if not is_audio_muted():
                try:
                    from albedo.audio.tts import speak
                    speak(reply)
                except Exception as _exc:
                    print(f"[eel_app] Wake TTS reply failed: {_exc}")

            # 7. Cooldown — drain mic buffer so TTS audio can't re-trigger OWW
            try:
                import sounddevice as _sd
                with _wake_lock:
                    s = _wake_stream
                if s:
                    s.drain()
                _sd.sleep(1500)  # 1.5 s silence before re-arming
            except Exception:
                pass

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

    actual_port  = _free_port(port)
    _active_port = actual_port          # expose to widget launcher
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
            cmdline_args=[
                "--start-maximized",
                "--disk-cache-size=1",      # disable persistent cache so updated
                "--media-cache-size=1",     # HTML/JS/CSS is always fetched fresh
            ],
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
