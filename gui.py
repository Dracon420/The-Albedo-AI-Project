"""
gui.py  --  Albedo Mission Control

Dark-mode desktop interface built with customtkinter. Text and voice
input both route through the Hybrid RAG pipeline. All heavy work runs
on daemon threads; UI updates are marshalled through self.after() via
an internal queue so tkinter is never touched from a background thread.
"""

import math
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageTk

ROOT = Path(__file__).parent

# ── Theme ──────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

C_BG       = "#0A0F2C"
C_PANEL    = "#0E1330"
C_CYAN     = "#00F5FF"
C_CYAN_DIM = "#0099BB"
C_BORDER   = "#1A2050"
C_TEXT     = "#C8D4E8"
C_MUTED    = "#3A4570"
C_GREEN    = "#00FF88"
C_PURPLE   = "#9988FF"
C_DANGER   = "#FF3A5C"

_STATE_COLOR = {
    "standby":    C_MUTED,
    "listening":  C_GREEN,
    "processing": C_CYAN,
    "speaking":   C_PURPLE,
}

_STATE_LABEL = {
    "standby":    "STANDBY",
    "listening":  "LISTENING",
    "processing": "PROCESSING",
    "speaking":   "SPEAKING",
}

CANVAS_SIZE = 220
ICON_RADIUS = 56
CENTER      = CANVAS_SIZE // 2


# ── Colour helper ──────────────────────────────────────────────────────────

def _blend(c1: str, c2: str, t: float) -> str:
    """Interpolate two hex colours; t=0 -> c1, t=1 -> c2."""
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    r = max(0, min(255, int(r1 + (r2 - r1) * t)))
    g = max(0, min(255, int(g1 + (g2 - g1) * t)))
    b = max(0, min(255, int(b1 + (b2 - b1) * t)))
    return f"#{r:02x}{g:02x}{b:02x}"


# ── .env writer ────────────────────────────────────────────────────────────

def _update_env(key: str, value: str) -> None:
    env_path = ROOT / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    found = False
    for i, line in enumerate(lines):
        k = line.split("=")[0].strip()
        if k == key:
            lines[i] = f'{key}="{value}"'
            found = True
            break
    if not found:
        lines.append(f'{key}="{value}"')
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Settings dialog ────────────────────────────────────────────────────────

class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("ALBEDO  //  RAG SETTINGS")
        self.geometry("580x320")
        self.resizable(False, False)
        self.configure(fg_color=C_PANEL)
        self.grab_set()
        self.focus_set()
        self._build()

    def _build(self) -> None:
        from albedo.config import CHAOTIC_3D_PATH, EXOTIC_OS_PATH

        p = {"padx": 24, "pady": 6}

        ctk.CTkLabel(self, text="RAG DIRECTORIES", font=("Courier New", 15, "bold"),
                     text_color=C_CYAN).pack(pady=(20, 8))

        ctk.CTkLabel(self, text="Chaotic 3D  --  STL / gcode / slicer configs",
                     font=("Courier New", 11), text_color=C_TEXT).pack(anchor="w", **p)
        self._var_3d = ctk.StringVar(value=str(CHAOTIC_3D_PATH))
        ctk.CTkEntry(self, textvariable=self._var_3d, width=530,
                     font=("Courier New", 11), fg_color=C_BG,
                     border_color=C_BORDER, text_color=C_TEXT).pack(**p)

        ctk.CTkLabel(self, text="Exotic OS  --  Python / logs / reptile records",
                     font=("Courier New", 11), text_color=C_TEXT).pack(anchor="w", **p)
        self._var_os = ctk.StringVar(value=str(EXOTIC_OS_PATH))
        ctk.CTkEntry(self, textvariable=self._var_os, width=530,
                     font=("Courier New", 11), fg_color=C_BG,
                     border_color=C_BORDER, text_color=C_TEXT).pack(**p)

        btn = ctk.CTkFrame(self, fg_color="transparent")
        btn.pack(pady=16)
        ctk.CTkButton(btn, text="SAVE", width=130,
                      font=("Courier New", 12, "bold"),
                      command=self._save).pack(side="left", padx=10)
        ctk.CTkButton(btn, text="RE-INDEX NOW", width=160,
                      font=("Courier New", 12, "bold"),
                      fg_color=C_CYAN_DIM, hover_color=C_CYAN,
                      command=self._reindex).pack(side="left", padx=10)

        self._msg = ctk.CTkLabel(self, text="", font=("Courier New", 10),
                                 text_color=C_MUTED)
        self._msg.pack()

    def _save(self) -> None:
        _update_env("CHAOTIC_3D_PATH", self._var_3d.get().strip())
        _update_env("EXOTIC_OS_PATH",  self._var_os.get().strip())
        import importlib, albedo.config as _cfg
        importlib.reload(_cfg)
        self._msg.configure(text="Saved. Re-index to apply new paths.", text_color=C_GREEN)

    def _reindex(self) -> None:
        self._msg.configure(text="Indexing...", text_color=C_CYAN)
        self.update()
        def _run():
            from albedo.rag.indexer import index_all
            results = index_all()
            total = sum(results.values())
            summary = "  ".join(f"{k}: {v}" for k, v in results.items())
            self.after(0, lambda: self._msg.configure(
                text=f"Done. {total} new chunks  ({summary})", text_color=C_GREEN))
        threading.Thread(target=_run, daemon=True).start()


# ── Main window ────────────────────────────────────────────────────────────

class AlbedoGUI(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("ALBEDO  //  MISSION CONTROL")
        self.geometry("720x860")
        self.minsize(600, 700)
        self.configure(fg_color=C_BG)

        self._state       = "standby"
        self._ui_queue    : queue.Queue = queue.Queue()
        self._voice_stop  = threading.Event()
        self._audio_stream = None
        self._settings_win = None
        self._pulse_phase = 0.0
        self._icon_photo  = None   # ImageTk ref kept alive

        self._build_ui()
        self._start_queue_poll()
        self._animate()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Header bar
        hdr = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=0, height=62)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(
            hdr,
            text="ALBEDO  //  MISSION CONTROL",
            font=("Courier New", 19, "bold"),
            text_color=C_CYAN,
        ).pack(side="left", padx=22, pady=14)

        self._state_chip = ctk.CTkLabel(
            hdr,
            text="STANDBY",
            font=("Courier New", 11),
            text_color=C_MUTED,
        )
        self._state_chip.pack(side="right", padx=22)

        # Orb canvas (plain tkinter Canvas -- customtkinter has no CTkCanvas)
        self._canvas = tk.Canvas(
            self,
            width=CANVAS_SIZE,
            height=CANVAS_SIZE,
            bg=C_BG,
            highlightthickness=0,
        )
        self._canvas.pack(pady=(14, 0))
        self._load_icon()

        # Output log
        log_outer = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=8)
        log_outer.pack(fill="both", expand=True, padx=16, pady=(12, 4))

        self._log = ctk.CTkTextbox(
            log_outer,
            font=("Courier New", 12),
            fg_color=C_PANEL,
            text_color=C_TEXT,
            wrap="word",
            state="disabled",
            border_width=0,
            scrollbar_button_color=C_BORDER,
        )
        self._log.pack(fill="both", expand=True, padx=4, pady=4)

        # Tag colours applied to the internal tk.Text widget
        tb = self._log._textbox
        tb.tag_config("albedo", foreground=C_CYAN)
        tb.tag_config("user",   foreground=C_TEXT)
        tb.tag_config("system", foreground=C_MUTED)
        tb.tag_config("error",  foreground=C_DANGER)

        # Input row
        row = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=8)
        row.pack(fill="x", padx=16, pady=(4, 12))

        self._mic_btn = ctk.CTkButton(
            row, text="MIC", width=62, height=44,
            font=("Courier New", 11, "bold"),
            fg_color=C_BORDER, hover_color=C_CYAN_DIM,
            command=self._handle_mic,
        )
        self._mic_btn.pack(side="left", padx=(10, 4), pady=10)

        self._entry = ctk.CTkEntry(
            row,
            placeholder_text="Type a query or press MIC...",
            font=("Courier New", 12),
            fg_color=C_BG, border_color=C_BORDER, text_color=C_TEXT,
            height=44,
        )
        self._entry.pack(side="left", fill="x", expand=True, padx=4, pady=10)
        self._entry.bind("<Return>", lambda _: self._handle_send())

        self._send_btn = ctk.CTkButton(
            row, text="SEND", width=72, height=44,
            font=("Courier New", 11, "bold"),
            command=self._handle_send,
        )
        self._send_btn.pack(side="left", padx=4, pady=10)

        ctk.CTkButton(
            row, text="SETTINGS", width=92, height=44,
            font=("Courier New", 10, "bold"),
            fg_color=C_BORDER, hover_color=C_CYAN_DIM,
            command=self._open_settings,
        ).pack(side="left", padx=(4, 10), pady=10)

    # ── Icon loading ───────────────────────────────────────────────────────

    def _load_icon(self) -> None:
        ico = ROOT / "albedo_icon.ico"
        if ico.exists():
            try:
                img = Image.open(ico)
                # Pull the largest frame from the ICO container
                best_img = img.copy()
                try:
                    for frame in range(getattr(img, "n_frames", 1)):
                        img.seek(frame)
                        if img.size[0] >= best_img.size[0]:
                            best_img = img.copy()
                except EOFError:
                    pass
                best_img = best_img.convert("RGBA").resize(
                    (ICON_RADIUS * 2, ICON_RADIUS * 2), Image.LANCZOS
                )
                self._icon_photo = ImageTk.PhotoImage(best_img)
                self._canvas.create_image(
                    CENTER, CENTER, image=self._icon_photo, tags="icon",
                )
                return
            except Exception:
                pass  # fall through

        # Placeholder glyph when no icon file is present
        self._canvas.create_text(
            CENTER, CENTER, text="A",
            fill=C_CYAN, font=("Courier New", 80, "bold"),
            tags="icon",
        )

    # ── Pulse animation ────────────────────────────────────────────────────

    def _animate(self) -> None:
        self._pulse_phase = (self._pulse_phase + 0.07) % (2 * math.pi)
        self._canvas.delete("ring")

        color = _STATE_COLOR[self._state]

        if self._state == "standby":
            r = ICON_RADIUS + 10
            self._canvas.create_oval(
                CENTER - r, CENTER - r, CENTER + r, CENTER + r,
                outline=C_BORDER, width=1, tags="ring",
            )
        else:
            # Three ripple rings with staggered phases
            for i, base_gap in enumerate([14, 26, 40]):
                phase = (self._pulse_phase + i * 0.9) % (2 * math.pi)
                p = (math.sin(phase) + 1) / 2          # 0..1
                r = ICON_RADIUS + base_gap + int(7 * p)
                fade = 1.0 - i * 0.3
                ring_color = _blend(color, C_BG, 1 - fade * (0.45 + 0.55 * p))
                width = max(1, int((3 - i) * fade))
                self._canvas.create_oval(
                    CENTER - r, CENTER - r, CENTER + r, CENTER + r,
                    outline=ring_color, width=width, tags="ring",
                )

        # Keep icon layer on top of rings
        self._canvas.tag_raise("icon")
        self.after(50, self._animate)   # 20 fps

    # ── State management ───────────────────────────────────────────────────

    def _set_state(self, state: str) -> None:
        self._state = state
        self._state_chip.configure(text=_STATE_LABEL[state])

        busy = state in ("processing", "speaking")
        self._send_btn.configure(state="disabled" if busy else "normal")

        if state == "listening":
            self._mic_btn.configure(text="STOP", fg_color=C_GREEN,
                                    hover_color="#00CC66")
        else:
            self._mic_btn.configure(text="MIC", fg_color=C_BORDER,
                                    hover_color=C_CYAN_DIM)
            self._mic_btn.configure(state="disabled" if busy else "normal")

    # ── Log output ─────────────────────────────────────────────────────────

    def _log_append(self, role: str, text: str) -> None:
        ts = datetime.now().strftime("%H:%M")
        prefixes = {
            "albedo": f"[{ts}] ALBEDO  ",
            "user":   f"[{ts}] YOU     ",
            "system": f"[{ts}] SYS     ",
            "error":  f"[{ts}] ERROR   ",
        }
        prefix = prefixes.get(role, f"[{ts}] ")
        tb = self._log._textbox
        self._log.configure(state="normal")
        tb.insert("end", prefix, role)
        tb.insert("end", text.strip() + "\n\n")
        self._log.configure(state="disabled")
        tb.see("end")

    # ── Queue poll (thread -> UI bridge) ───────────────────────────────────

    def _start_queue_poll(self) -> None:
        def _poll():
            try:
                while True:
                    self._ui_queue.get_nowait()()
            except queue.Empty:
                pass
            self.after(40, _poll)
        self.after(40, _poll)

    def _ui(self, fn) -> None:
        self._ui_queue.put(fn)

    # ── Text input ─────────────────────────────────────────────────────────

    def _handle_send(self) -> None:
        text = self._entry.get().strip()
        if not text or self._state in ("processing", "speaking"):
            return
        self._entry.delete(0, "end")

        use_web = text.lower().startswith("web:")
        query   = text[4:].strip() if use_web else text

        self._log_append("user", query)
        self._set_state("processing")
        threading.Thread(
            target=self._run_pipeline, args=(query, use_web), daemon=True,
        ).start()

    # ── Voice input ────────────────────────────────────────────────────────

    def _handle_mic(self) -> None:
        if self._state == "listening":
            self._voice_stop.set()
            return
        if self._state in ("processing", "speaking"):
            return
        self._voice_stop.clear()
        self._set_state("listening")
        threading.Thread(target=self._run_voice, daemon=True).start()

    def _run_voice(self) -> None:
        try:
            from albedo.audio.capture import AudioStream, record_utterance
            from albedo.audio.stt import transcribe

            if self._audio_stream is None:
                self._audio_stream = AudioStream()
                self._audio_stream.start()

            audio = record_utterance(self._audio_stream)

            if self._voice_stop.is_set() or audio is None or len(audio) == 0:
                self._ui(lambda: self._set_state("standby"))
                return

            self._ui(lambda: self._set_state("processing"))
            query = transcribe(audio)

            if not query:
                self._ui(lambda: self._log_append("system", "No speech detected."))
                self._ui(lambda: self._set_state("standby"))
                return

            self._ui(lambda: self._log_append("user", query))
            self._run_pipeline(query, use_web=False)

        except Exception as exc:
            msg = str(exc)
            self._ui(lambda: self._log_append("error", msg))
            self._ui(lambda: self._set_state("standby"))

    # ── Pipeline runner ────────────────────────────────────────────────────

    def _run_pipeline(self, query: str, use_web: bool) -> None:
        try:
            from albedo.pipeline import run as pipeline_run
            response = pipeline_run(query, use_web=use_web)

            self._ui(lambda: self._log_append("albedo", response))
            self._ui(lambda: self._set_state("speaking"))

            # TTS -- subprocess call, safe to run on this thread
            try:
                from albedo.audio.tts import speak
                speak(response)
            except Exception:
                pass  # TTS unavailable is non-fatal

        except Exception as exc:
            msg = str(exc)
            self._ui(lambda: self._log_append("error", msg))
        finally:
            self._ui(lambda: self._set_state("standby"))

    # ── Settings ───────────────────────────────────────────────────────────

    def _open_settings(self) -> None:
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.focus()
            return
        self._settings_win = SettingsDialog(self)

    # ── Cleanup ────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        if self._audio_stream:
            try:
                self._audio_stream.stop()
            except Exception:
                pass
        self.destroy()


# ── Entry point ────────────────────────────────────────────────────────────

def main() -> None:
    app = AlbedoGUI()
    app._log_append("system", "Albedo Mission Control online.")
    app._log_append("system", "Type a query and press SEND, or press MIC to speak.")
    app._log_append("system", "Prefix any query with  web:  to force live web search.")
    app.mainloop()


if __name__ == "__main__":
    main()
