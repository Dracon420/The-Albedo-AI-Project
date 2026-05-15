"""
gui.py  --  Albedo Mission Control

Dark-mode desktop interface built with customtkinter. Text and voice
input both route through the Hybrid RAG pipeline. All heavy work runs
on daemon threads; UI updates are marshalled through self.after() via
an internal queue so tkinter is never touched from a background thread.

Fixes in this version:
  - Poll loop catches all callable exceptions so one bad update cannot
    kill the entire UI pump.
  - Voice VAD loop checks the stop event every chunk so STOP responds
    immediately instead of waiting for the VAD silence gate.
  - bridge.py fallback guarantees a non-empty string for every query.
  - from __future__ import annotations on all albedo modules eliminates
    the X | Y annotation evaluation crash on any Python version.
"""
from __future__ import annotations

import json
import math
import queue
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path

try:
    import customtkinter as ctk
    from PIL import Image, ImageTk
except ImportError as _import_err:
    import tkinter.messagebox as _mb
    _mb.showerror(
        "Albedo -- Missing Packages",
        "Required packages are not installed in the virtual environment.\n\n"
        f"Missing: {_import_err.name}\n\n"
        "Run setup_utility.py to complete the installation:\n"
        "  py -3.12 setup_utility.py\n\n"
        "Or re-run the Albedo Setup Wizard from the Start Menu."
    )
    raise SystemExit(1)

ROOT          = Path(__file__).parent
SETTINGS_PATH = ROOT / "settings.json"

# ── Persona constants ──────────────────────────────────────────────────────

_VOICES_DIR   = ROOT / "voices"
_WAKEWORD_DIR = ROOT / "wakewords"  # bundled in repo

# Display-name → voice file + wakeword model
PERSONA_MAP: dict[str, dict[str, str]] = {
    "Cortana": {
        "voice":    str(_VOICES_DIR / "en_US-kristin-medium.onnx"),
        "wakeword": str(_WAKEWORD_DIR / "hey_core_tah_nuh.onnx"),
    },
    "Jarvis": {
        "voice":    str(_VOICES_DIR / "en_US-ryan-medium.onnx"),
        "wakeword": str(_WAKEWORD_DIR / "hey_jarvis_v0.1.onnx"),
    },
}
_PERSONA_DISPLAY = list(PERSONA_MAP.keys())  # ["Cortana", "Jarvis"]


# ── Settings persistence ───────────────────────────────────────────────────

def _load_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_settings(data: dict) -> None:
    try:
        SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"[gui] Failed to save settings: {exc}")


# ── stdout / stderr redirector ─────────────────────────────────────────────

class _StdRedirector:
    """Routes sys.stdout / sys.stderr writes to the in-app console buffer."""

    def __init__(self, write_fn):
        self._write = write_fn

    def write(self, text: str) -> None:
        if text:
            self._write(text)

    def flush(self) -> None:
        pass


# ── Theme ──────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

C_BG         = "#0A0E17"   # deep obsidian
C_PANEL      = "#121824"   # dark graphite
C_CYAN       = "#00F0FF"   # electric laser cyan  (ALBEDO tags, borders)
C_CYAN_DIM   = "#0099CC"   # dim cyan             (scrollbars, hovers)
C_BORDER     = "#1C2640"   # structural border
C_TEXT       = "#E2E8F0"   # bright silver-white  (body text)
C_MUTED      = "#4A5880"   # subtle               (HUD decorative only)
C_GREEN      = "#39FF14"   # intense neon green   (YOU / user tags)
C_ORANGE     = "#FF9900"   # tactical orange       (SYS / system tags)
C_PURPLE     = "#9988FF"   # scan hover
C_DANGER     = "#FF3A5C"   # error

_STATE_COLOR = {
    "standby":    C_MUTED,
    "listening":  C_GREEN,   # neon green
    "processing": C_CYAN,    # electric cyan
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
    def __init__(self, parent: "AlbedoGUI"):
        super().__init__(parent)
        self._parent = parent
        self.title("ALBEDO  //  SETTINGS")
        self.geometry("580x420")
        self.resizable(False, False)
        self.configure(fg_color=C_PANEL)
        self.grab_set()
        self.focus_set()
        self._build()

    def _build(self) -> None:
        from albedo.config import CHAOTIC_3D_PATH, EXOTIC_OS_PATH
        p = {"padx": 24, "pady": 6}

        # ── RAG directories ────────────────────────────────────────────────
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

        # ── Persona / wake word ────────────────────────────────────────────
        ctk.CTkFrame(self, fg_color=C_BORDER, height=1).pack(fill="x", padx=24, pady=(12, 4))
        ctk.CTkLabel(self, text="PERSONA  &  WAKE WORD",
                     font=("Courier New", 15, "bold"),
                     text_color=C_CYAN).pack(pady=(8, 4))
        ctk.CTkLabel(self, text="Changes voice model and wake word simultaneously.",
                     font=("Courier New", 10), text_color=C_MUTED).pack(pady=(0, 6))

        active = self._parent._settings.get("active_persona", "cortana").capitalize()
        if active not in PERSONA_MAP:
            active = "Cortana"
        self._persona_var = ctk.StringVar(value=active)
        ctk.CTkOptionMenu(self,
                          variable=self._persona_var,
                          values=_PERSONA_DISPLAY,
                          font=("Courier New", 12),
                          fg_color=C_BG, text_color=C_TEXT,
                          button_color=C_BORDER, button_hover_color=C_CYAN_DIM,
                          dropdown_fg_color=C_BG,
                          dropdown_text_color=C_TEXT).pack(padx=24, fill="x", pady=(0, 4))

        # ── Buttons ────────────────────────────────────────────────────────
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
        import importlib
        import albedo.config as _cfg
        importlib.reload(_cfg)

        self._parent._apply_persona(self._persona_var.get())
        self._msg.configure(text="Saved. Re-index to apply new RAG paths.",
                            text_color=C_GREEN)

    def _reindex(self) -> None:
        self._msg.configure(text="Indexing...", text_color=C_CYAN)
        self.update()
        def _run() -> None:
            from albedo.rag.indexer import index_all
            results = index_all()
            total = sum(results.values())
            summary = "  ".join(f"{k}: {v}" for k, v in results.items())
            self.after(0, lambda: self._msg.configure(
                text=f"Done. {total} new chunks  ({summary})", text_color=C_GREEN))
        threading.Thread(target=_run, daemon=True).start()


# ── Hardware settings dialog ───────────────────────────────────────────────

class HardwareSettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent: "AlbedoGUI") -> None:
        super().__init__(parent)
        self._parent = parent
        self.title("ALBEDO  //  HARDWARE SETTINGS")
        self.geometry("600x380")
        self.resizable(False, False)
        self.configure(fg_color=C_PANEL)
        self.grab_set()
        self.focus_set()
        self._in_ids:    list[int] = []
        self._out_ids:   list[int] = []
        self._in_labels: list[str] = []
        self._out_labels: list[str] = []
        self._build()

    def _build(self) -> None:
        import sounddevice as sd

        ctk.CTkLabel(self, text="HARDWARE SETTINGS",
                     font=("Courier New", 15, "bold"),
                     text_color=C_CYAN).pack(pady=(20, 4))
        ctk.CTkLabel(self, text="Changes take effect on the next MIC press.",
                     font=("Courier New", 10), text_color=C_MUTED).pack(pady=(0, 12))

        try:
            devices  = sd.query_devices()
            hostapis = sd.query_hostapis()
        except Exception:
            devices  = []
            hostapis = []

        # Deduplicate: one entry per physical device name.
        # Prefer WASAPI (best quality) → MME → DirectSound → anything else.
        _API_RANK = {"Windows WASAPI": 0, "MME": 1, "Windows DirectSound": 2}

        def _rank(d: dict) -> int:
            try:
                return _API_RANK.get(hostapis[d["hostapi"]]["name"], 99)
            except Exception:
                return 99

        seen_in:  dict[str, tuple[int, int]] = {}  # name → (rank, device_idx)
        seen_out: dict[str, tuple[int, int]] = {}

        for i, d in enumerate(devices):
            name = d["name"]
            r    = _rank(d)
            if d["max_input_channels"] > 0:
                if name not in seen_in or r < seen_in[name][0]:
                    seen_in[name] = (r, i)
            if d["max_output_channels"] > 0:
                if name not in seen_out or r < seen_out[name][0]:
                    seen_out[name] = (r, i)

        for name, (_, idx) in seen_in.items():
            self._in_ids.append(idx)
            self._in_labels.append(name)

        for name, (_, idx) in seen_out.items():
            self._out_ids.append(idx)
            self._out_labels.append(name)

        settings = self._parent._settings

        # ── Input device ──────────────────────────────────────────────────
        fi = ctk.CTkFrame(self, fg_color="transparent")
        fi.pack(fill="x", padx=24, pady=6)
        ctk.CTkLabel(fi, text="INPUT  --  Microphone",
                     font=("Courier New", 11), text_color=C_TEXT).pack(anchor="w")

        saved_in = settings.get("audio_input_device")
        in_default = (self._in_labels[self._in_ids.index(saved_in)]
                      if saved_in is not None and saved_in in self._in_ids
                      else (self._in_labels[0] if self._in_labels else "No devices"))
        self._in_var = ctk.StringVar(value=in_default)

        if self._in_labels:
            ctk.CTkOptionMenu(fi, variable=self._in_var, values=self._in_labels,
                              font=("Courier New", 11),
                              fg_color=C_BG, text_color=C_TEXT,
                              button_color=C_BORDER,
                              button_hover_color=C_CYAN_DIM,
                              dropdown_fg_color=C_BG,
                              dropdown_text_color=C_TEXT).pack(fill="x", pady=(4, 0))
        else:
            ctk.CTkLabel(fi, text="No input devices found.",
                         font=("Courier New", 11),
                         text_color=C_DANGER).pack(anchor="w")

        # ── Output device ─────────────────────────────────────────────────
        fo = ctk.CTkFrame(self, fg_color="transparent")
        fo.pack(fill="x", padx=24, pady=6)
        ctk.CTkLabel(fo, text="OUTPUT  --  Speakers / HDMI",
                     font=("Courier New", 11), text_color=C_TEXT).pack(anchor="w")

        saved_out = settings.get("audio_output_device")
        out_default = (self._out_labels[self._out_ids.index(saved_out)]
                       if saved_out is not None and saved_out in self._out_ids
                       else (self._out_labels[0] if self._out_labels else "No devices"))
        self._out_var = ctk.StringVar(value=out_default)

        if self._out_labels:
            ctk.CTkOptionMenu(fo, variable=self._out_var, values=self._out_labels,
                              font=("Courier New", 11),
                              fg_color=C_BG, text_color=C_TEXT,
                              button_color=C_BORDER,
                              button_hover_color=C_CYAN_DIM,
                              dropdown_fg_color=C_BG,
                              dropdown_text_color=C_TEXT).pack(fill="x", pady=(4, 0))
        else:
            ctk.CTkLabel(fo, text="No output devices found.",
                         font=("Courier New", 11),
                         text_color=C_DANGER).pack(anchor="w")

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=16)
        ctk.CTkButton(btn_row, text="SAVE", width=130,
                      font=("Courier New", 12, "bold"),
                      command=self._save).pack(side="left", padx=10)

        self._msg = ctk.CTkLabel(self, text="", font=("Courier New", 10),
                                 text_color=C_MUTED)
        self._msg.pack()

    def _save(self) -> None:
        in_label  = self._in_var.get()
        out_label = self._out_var.get()

        in_id  = (self._in_ids[self._in_labels.index(in_label)]
                  if in_label in self._in_labels else None)
        out_id = (self._out_ids[self._out_labels.index(out_label)]
                  if out_label in self._out_labels else None)

        self._parent._settings["audio_input_device"]  = in_id
        self._parent._settings["audio_output_device"] = out_id
        _save_settings(self._parent._settings)
        self._parent._reset_audio_stream()
        self._msg.configure(text="Saved. Active on next MIC press.",
                            text_color=C_GREEN)


# ── Developer console dialog ───────────────────────────────────────────────

class ConsoleDialog(ctk.CTkToplevel):
    def __init__(self, parent: "AlbedoGUI") -> None:
        super().__init__(parent)
        self._parent = parent
        self.title("ALBEDO  //  DEVELOPER CONSOLE")
        self.geometry("820x500")
        self.configure(fg_color=C_PANEL)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build()
        # Populate with buffered history from before the dialog was opened
        if parent._console_buf:
            self._append("".join(parent._console_buf))

    def _build(self) -> None:
        hdr = ctk.CTkFrame(self, fg_color=C_BG, corner_radius=0, height=42)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="DEVELOPER CONSOLE  --  stdout / stderr",
                     font=("Courier New", 12, "bold"),
                     text_color=C_CYAN).pack(side="left", padx=16, pady=10)
        ctk.CTkButton(hdr, text="CLEAR", width=70, height=26,
                      font=("Courier New", 10),
                      fg_color=C_BORDER, hover_color=C_DANGER,
                      command=self._clear).pack(side="right", padx=12, pady=8)

        self._txt = ctk.CTkTextbox(self, font=("Courier New", 11),
                                   fg_color=C_BG, text_color=C_TEXT,
                                   wrap="word", state="disabled", border_width=0,
                                   scrollbar_button_color=C_BORDER)
        self._txt.pack(fill="both", expand=True, padx=4, pady=4)

    def _append(self, text: str) -> None:
        self._txt.configure(state="normal")
        self._txt.insert("end", text)
        self._txt.configure(state="disabled")
        self._txt._textbox.see("end")

    def _clear(self) -> None:
        self._txt.configure(state="normal")
        self._txt.delete("1.0", "end")
        self._txt.configure(state="disabled")
        self._parent._console_buf.clear()

    def _on_close(self) -> None:
        self._parent._console_win = None
        self.destroy()


# ── Main window ────────────────────────────────────────────────────────────

class AlbedoGUI(ctk.CTk):

    def __init__(self) -> None:
        super().__init__()
        self.title("ALBEDO  //  MISSION CONTROL")
        self.geometry("720x860")
        self.minsize(600, 700)
        self.configure(fg_color=C_BG)

        self._state        = "standby"
        self._ui_queue: queue.Queue = queue.Queue()
        self._voice_stop   = threading.Event()
        self._audio_stream = None   # AudioStream, lazy-init
        self._settings_win = None
        self._hardware_win = None
        self._console_win  = None
        self._console_buf: list[str] = []
        self._pulse_phase  = 0.0
        self._icon_photo   = None   # ImageTk ref kept alive
        self._settings     = _load_settings()
        self._scan_btn     = None   # set by _build_ui
        # Rolling conversation context — last 10 turns (20 messages)
        self._chat_history: list[dict] = []

        # Redirect stdout/stderr into the in-app console so nothing is lost
        # when running under pythonw.exe (no console window).
        self._stdout_orig = sys.stdout
        self._stderr_orig = sys.stderr
        sys.stdout = _StdRedirector(self._console_write)
        sys.stderr = _StdRedirector(self._console_write)

        self._build_ui()
        self._start_queue_poll()
        self._animate()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Pre-warm Whisper in background so first MIC press is instant
        threading.Thread(target=self._prewarm_whisper, daemon=True).start()

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ── Header ─────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=0, height=62)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(hdr, text="ALBEDO  //  MISSION CONTROL",
                     font=("Courier New", 19, "bold"),
                     text_color=C_CYAN).pack(side="left", padx=22, pady=14)

        self._state_chip = ctk.CTkLabel(hdr, text="STANDBY",
                                        font=("Courier New", 13),
                                        text_color=C_MUTED)
        self._state_chip.pack(side="right", padx=22)

        ctk.CTkButton(hdr, text="LOGS", width=60, height=30,
                      font=("Courier New", 10, "bold"),
                      fg_color=C_BORDER, hover_color=C_MUTED,
                      command=self._open_console).pack(side="right", padx=(0, 4), pady=16)

        # ── Tactical HUD status bar ─────────────────────────────────────────
        hud = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=0, height=22)
        hud.pack(fill="x")
        hud.pack_propagate(False)
        ctk.CTkLabel(
            hud,
            text="// CORE_SYS: ACTIVE  |  BRIDGE: OK  |  MEM: ONLINE  |  VEC_DB: READY",
            font=("Courier New", 9),
            text_color=C_MUTED,
        ).pack(side="left", padx=16)
        ctk.CTkLabel(
            hud,
            text="[ NET_LINK: OK ]",
            font=("Courier New", 9),
            text_color=C_CYAN_DIM,
        ).pack(side="right", padx=16)

        # ── Orb canvas ─────────────────────────────────────────────────────
        self._canvas = tk.Canvas(self, width=CANVAS_SIZE, height=CANVAS_SIZE,
                                 bg=C_BG, highlightthickness=0)
        self._canvas.pack(pady=(10, 0))
        self._load_icon()

        # ── Output log (neon border + HUD corner tags) ──────────────────────
        log_outer = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=8,
                                 border_width=1, border_color=C_CYAN)
        log_outer.pack(fill="both", expand=True, padx=16, pady=(10, 2))

        # HUD corner tags inside the log panel
        log_hdr = ctk.CTkFrame(log_outer, fg_color="transparent", height=18)
        log_hdr.pack(fill="x", padx=6, pady=(4, 0))
        log_hdr.pack_propagate(False)
        ctk.CTkLabel(log_hdr, text="// CHAT_FEED",
                     font=("Courier New", 9), text_color=C_MUTED).pack(side="left")
        ctk.CTkLabel(log_hdr, text="[ STREAM: ACTIVE ]",
                     font=("Courier New", 9), text_color=C_CYAN_DIM).pack(side="right")

        self._log = ctk.CTkTextbox(log_outer, font=("Consolas", 16),
                                   fg_color=C_PANEL, text_color=C_TEXT,
                                   wrap="word", state="disabled", border_width=0,
                                   scrollbar_button_color=C_CYAN_DIM)
        self._log.pack(fill="both", expand=True, padx=4, pady=(2, 4))

        tb = self._log._textbox
        tb.tag_config("albedo", foreground=C_CYAN)        # Electric laser cyan
        tb.tag_config("user",   foreground=C_GREEN)       # Intense neon green
        tb.tag_config("system", foreground=C_ORANGE)      # Tactical orange
        tb.tag_config("error",  foreground=C_DANGER)

        # ── CMD_INPUT HUD tag above input row ───────────────────────────────
        cmd_hdr = ctk.CTkFrame(self, fg_color="transparent", height=16)
        cmd_hdr.pack(fill="x", padx=18)
        cmd_hdr.pack_propagate(False)
        ctk.CTkLabel(cmd_hdr, text="[ CMD_INPUT ]",
                     font=("Courier New", 9), text_color=C_MUTED).pack(side="left")
        ctk.CTkLabel(cmd_hdr, text="// INPUT_READY",
                     font=("Courier New", 9), text_color=C_CYAN_DIM).pack(side="right")

        # ── Input row (neon border on entry) ────────────────────────────────
        row = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=8,
                           border_width=1, border_color=C_BORDER)
        row.pack(fill="x", padx=16, pady=(2, 12))

        self._mic_btn = ctk.CTkButton(row, text="MIC", width=62, height=44,
                                      font=("Courier New", 11, "bold"),
                                      fg_color=C_BORDER, hover_color=C_CYAN_DIM,
                                      command=self._handle_mic)
        self._mic_btn.pack(side="left", padx=(10, 4), pady=10)

        self._scan_btn = ctk.CTkButton(row, text="SCAN", width=62, height=44,
                                       font=("Courier New", 11, "bold"),
                                       fg_color=C_BORDER, hover_color=C_PURPLE,
                                       command=self._handle_scan)
        self._scan_btn.pack(side="left", padx=(0, 4), pady=10)

        self._entry = ctk.CTkEntry(row,
                                   placeholder_text="Type a query or press MIC...",
                                   font=("Consolas", 14),
                                   fg_color=C_BG, border_color=C_CYAN,
                                   text_color=C_TEXT, height=44)
        self._entry.pack(side="left", fill="x", expand=True, padx=4, pady=10)
        self._entry.bind("<Return>", lambda _: self._handle_send())

        self._send_btn = ctk.CTkButton(row, text="SEND", width=72, height=44,
                                       font=("Courier New", 11, "bold"),
                                       fg_color=C_CYAN_DIM, hover_color=C_CYAN,
                                       text_color="#000000",
                                       command=self._handle_send)
        self._send_btn.pack(side="left", padx=4, pady=10)

        ctk.CTkButton(row, text="SETTINGS", width=88, height=44,
                      font=("Courier New", 10, "bold"),
                      fg_color=C_BORDER, hover_color=C_CYAN_DIM,
                      command=self._open_settings).pack(side="left", padx=4, pady=10)

        ctk.CTkButton(row, text="HARDWARE", width=88, height=44,
                      font=("Courier New", 10, "bold"),
                      fg_color=C_BORDER, hover_color=C_CYAN_DIM,
                      command=self._open_hardware_settings).pack(side="left", padx=(4, 10), pady=10)

    # ── Icon loading ───────────────────────────────────────────────────────

    def _load_icon(self) -> None:
        ico = ROOT / "albedo_icon.ico"
        if ico.exists():
            try:
                img = Image.open(ico)
                best = img.copy()
                try:
                    for frame in range(getattr(img, "n_frames", 1)):
                        img.seek(frame)
                        if img.size[0] >= best.size[0]:
                            best = img.copy()
                except EOFError:
                    pass
                best = best.convert("RGBA").resize(
                    (ICON_RADIUS * 2, ICON_RADIUS * 2), Image.LANCZOS)
                self._icon_photo = ImageTk.PhotoImage(best)
                self._canvas.create_image(CENTER, CENTER,
                                          image=self._icon_photo, tags="icon")
                return
            except Exception:
                pass
        # Placeholder glyph
        self._canvas.create_text(CENTER, CENTER, text="A",
                                 fill=C_CYAN, font=("Courier New", 80, "bold"),
                                 tags="icon")

    # ── Pulse animation ────────────────────────────────────────────────────

    def _animate(self) -> None:
        self._pulse_phase = (self._pulse_phase + 0.07) % (2 * math.pi)
        self._canvas.delete("ring")
        color = _STATE_COLOR[self._state]

        if self._state == "standby":
            r = ICON_RADIUS + 10
            self._canvas.create_oval(CENTER - r, CENTER - r,
                                     CENTER + r, CENTER + r,
                                     outline=C_BORDER, width=1, tags="ring")
        else:
            for i, base_gap in enumerate([14, 26, 40]):
                phase = (self._pulse_phase + i * 0.9) % (2 * math.pi)
                p = (math.sin(phase) + 1) / 2
                r = ICON_RADIUS + base_gap + int(7 * p)
                fade = 1.0 - i * 0.3
                ring_color = _blend(color, C_BG, 1 - fade * (0.45 + 0.55 * p))
                width = max(1, int((3 - i) * fade))
                self._canvas.create_oval(CENTER - r, CENTER - r,
                                         CENTER + r, CENTER + r,
                                         outline=ring_color, width=width, tags="ring")
        self._canvas.tag_raise("icon")
        self.after(50, self._animate)

    # ── State management ───────────────────────────────────────────────────

    def _set_state(self, state: str) -> None:
        self._state = state
        chip_color = _STATE_COLOR[state]
        self._state_chip.configure(text=_STATE_LABEL[state], text_color=chip_color)
        busy = state in ("processing", "speaking")
        locked = busy or state == "listening"

        self._send_btn.configure(state="disabled" if busy else "normal")
        if self._scan_btn:
            self._scan_btn.configure(state="disabled" if locked else "normal")

        if state == "listening":
            self._mic_btn.configure(text="STOP", state="normal",
                                    fg_color=C_GREEN, hover_color="#00CC66")
        elif busy:
            self._mic_btn.configure(text="MIC", state="disabled",
                                    fg_color=C_BORDER, hover_color=C_CYAN_DIM)
        else:
            self._mic_btn.configure(text="MIC", state="normal",
                                    fg_color=C_BORDER, hover_color=C_CYAN_DIM)

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
        tb.insert("end", str(text).strip() + "\n\n")
        self._log.configure(state="disabled")
        tb.see("end")

    # ── Queue poll (thread -> UI bridge) ───────────────────────────────────
    #
    # CRITICAL: each callable is wrapped in its own try/except.
    # Without this, one bad update kills the entire pump permanently.

    def _start_queue_poll(self) -> None:
        def _poll() -> None:
            try:
                while True:
                    fn = self._ui_queue.get_nowait()
                    try:
                        fn()
                    except Exception as exc:
                        print(f"[gui] UI callable error: {exc}")
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
        threading.Thread(target=self._run_pipeline,
                         args=(query, use_web), daemon=True).start()

    # ── Voice input ────────────────────────────────────────────────────────

    def _handle_mic(self) -> None:
        if self._state == "listening":
            # Signal the recording loop to stop immediately
            self._voice_stop.set()
            return
        if self._state in ("processing", "speaking"):
            return
        self._voice_stop.clear()
        self._set_state("listening")
        threading.Thread(target=self._run_voice, daemon=True).start()

    def _run_voice(self) -> None:
        """
        Record audio from the mic until VAD silence OR the user presses STOP.
        Inlines the VAD loop so _voice_stop is checked every chunk (~80 ms).
        """
        try:
            import numpy as np
            import sounddevice as sd
            from albedo.audio.capture import AudioStream
            from albedo.audio.stt import transcribe
            from albedo.config import (
                AUDIO_SAMPLE_RATE, AUDIO_CHUNK_MS,
                VAD_SILENCE_THRESHOLD, VAD_SILENCE_DURATION,
                VAD_MAX_RECORD_SECONDS,
            )

            if self._audio_stream is None:
                in_dev = self._settings.get("audio_input_device")
                self._audio_stream = AudioStream(device=in_dev)
                self._audio_stream.start()
                sd.sleep(150)  # let the stream stabilise before reading

            stream = self._audio_stream
            stream.drain()

            chunk_samples  = int(AUDIO_SAMPLE_RATE * AUDIO_CHUNK_MS / 1000)
            silence_gate   = int(VAD_SILENCE_DURATION * AUDIO_SAMPLE_RATE / chunk_samples)
            max_chunks     = int(VAD_MAX_RECORD_SECONDS * AUDIO_SAMPLE_RATE / chunk_samples)

            frames: list = []
            silence_count = 0

            # VAD loop -- checks stop event every ~80 ms so STOP is immediate
            while len(frames) < max_chunks and not self._voice_stop.is_set():
                chunk = stream.read_chunk()
                if chunk is None:
                    sd.sleep(10)
                    continue
                frames.append(chunk)
                rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2))) / 32767
                if rms < VAD_SILENCE_THRESHOLD:
                    silence_count += 1
                    if silence_count >= silence_gate:
                        break
                else:
                    silence_count = 0

            if not frames or self._voice_stop.is_set():
                self._ui(lambda: self._set_state("standby"))
                return

            audio = np.concatenate(frames).astype(np.float32) / 32767

            self._ui(lambda: self._state_chip.configure(text="TRANSCRIBING..."))
            query = transcribe(audio)

            if not query:
                self._ui(lambda: self._log_append("system", "No speech detected."))
                self._ui(lambda: self._set_state("standby"))
                return

            # Capture query value for the lambda closure
            q = query
            self._ui(lambda: self._log_append("user", q))
            self._run_pipeline(query, use_web=False)

        except Exception as exc:
            msg = str(exc)
            self._ui(lambda: self._log_append(
                "error", f"Microphone error: {msg}  --  check sounddevice / mic permissions"))
            self._ui(lambda: self._set_state("standby"))

    # ── Pipeline runner (always on a background thread) ────────────────────

    def _run_pipeline(self, query: str, use_web: bool) -> None:
        try:
            from albedo.pipeline import run as pipeline_run

            # Snapshot history so background thread has a stable copy
            history_snapshot = list(self._chat_history)
            response = pipeline_run(query, use_web=use_web, history=history_snapshot)

            # Guarantee response is always a non-empty string
            if not isinstance(response, str) or not response.strip():
                response = "[Albedo] No response returned. Is Ollama running?"

            # Update rolling context (trim to last 10 turns = 20 messages)
            self._chat_history.append({"role": "user",      "content": query})
            self._chat_history.append({"role": "assistant", "content": response})
            if len(self._chat_history) > 20:
                self._chat_history = self._chat_history[-20:]

            # Capture for closure
            resp = response
            self._ui(lambda: self._log_append("albedo", resp))
            self._ui(lambda: self._set_state("speaking"))

            # TTS runs on this background thread -- UI stays responsive
            try:
                from albedo.audio.tts import speak_streamed
                out_dev = self._settings.get("audio_output_device")
                speak_streamed(response, device=out_dev, voice_model=self._get_tts_voice())
            except Exception as tts_err:
                print(f"[gui] TTS error: {tts_err}")

        except Exception as exc:
            msg = str(exc)
            self._ui(lambda: self._log_append("error", msg))

        finally:
            self._ui(lambda: self._set_state("standby"))

    # ── Whisper pre-warming ────────────────────────────────────────────────

    def _prewarm_whisper(self) -> None:
        """Load WhisperModel on a background thread at startup.
        The first MIC press is instant because the model is already resident."""
        try:
            self._ui(lambda: self._log_append(
                "system", "Loading Whisper STT model in background..."))
            from albedo.audio.stt import prewarm
            prewarm()
            self._ui(lambda: self._log_append("system", "Whisper ready."))
        except Exception as exc:
            _prewarm_msg = f"Whisper pre-warm failed (will retry on first MIC press): {exc}"
            self._ui(lambda: self._log_append("system", _prewarm_msg))

    # ── Visual scan ────────────────────────────────────────────────────────

    def _handle_scan(self) -> None:
        if self._state != "standby":
            return
        self._set_state("processing")
        threading.Thread(target=self._run_scan, daemon=True).start()

    def _run_scan(self) -> None:
        try:
            from albedo.vision import capture_vision, vision_query

            self._ui(lambda: self._state_chip.configure(text="CAPTURING..."))
            frame = capture_vision(device=0)
            if frame is None:
                self._ui(lambda: self._log_append(
                    "error",
                    "Visual Scan: could not open webcam.  "
                    "Check that the camera is connected and not in use."))
                return

            self._ui(lambda: self._state_chip.configure(text="ANALYZING..."))
            vision_temp = self._settings.get("vision_temperature", 0.2)
            result = vision_query(frame, temperature=vision_temp)

            if not result or not result.strip():
                result = (
                    "[Albedo] No visual analysis returned.  "
                    "Is moondream pulled?  Run: ollama pull moondream"
                )

            resp = result
            self._ui(lambda: self._log_append("albedo", resp))
            self._ui(lambda: self._set_state("speaking"))

            try:
                from albedo.audio.tts import speak_streamed
                out_dev = self._settings.get("audio_output_device")
                speak_streamed(result, device=out_dev, voice_model=self._get_tts_voice())
            except Exception as tts_err:
                print(f"[gui] TTS error: {tts_err}")

        except Exception as exc:
            msg = str(exc)
            self._ui(lambda: self._log_append("error", f"Visual Scan error: {msg}"))
        finally:
            self._ui(lambda: self._set_state("standby"))

    # ── Persona management ─────────────────────────────────────────────────

    def _get_tts_voice(self) -> str | None:
        """Return the Piper voice model path for the active persona."""
        key = self._settings.get("active_persona", "cortana").capitalize()
        persona = PERSONA_MAP.get(key) or PERSONA_MAP.get("Cortana")
        return persona["voice"] if persona else None

    def _apply_persona(self, display_name: str) -> None:
        """Switch active persona: hot-swap TTS voice + wakeword model, persist."""
        persona = PERSONA_MAP.get(display_name)
        if not persona:
            return
        key = display_name.lower()
        old_key = self._settings.get("active_persona", "")
        self._settings["active_persona"] = key
        _save_settings(self._settings)

        # Persist to .env so CLI listener mode picks it up on next launch
        _update_env("PIPER_VOICE_MODEL", persona["voice"])
        _update_env("WAKEWORD_MODEL",    persona["wakeword"])

        # Hot-swap the wakeword model for the current session
        try:
            from albedo.audio import wakeword as _ww
            _ww.set_active_model(persona["wakeword"])
        except Exception as exc:
            print(f"[gui] wakeword hot-swap failed (non-fatal): {exc}")

        if key != old_key:
            self._log_append(
                "system",
                f"[SYS] Persona updated: {display_name}. "
                "Voice and Wake Word synchronized.",
            )

    # ── Developer console ──────────────────────────────────────────────────

    def _console_write(self, text: str) -> None:
        """Buffer a console line and forward it to the dialog if open."""
        self._console_buf.append(text)
        if len(self._console_buf) > 500:
            self._console_buf = self._console_buf[-500:]
        if self._console_win and self._console_win.winfo_exists():
            self._ui(lambda t=text: self._console_win._append(t))

    def _open_console(self) -> None:
        if self._console_win and self._console_win.winfo_exists():
            self._console_win.focus()
            return
        self._console_win = ConsoleDialog(self)

    # ── Settings ───────────────────────────────────────────────────────────

    def _open_settings(self) -> None:
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.focus()
            return
        self._settings_win = SettingsDialog(self)

    def _open_hardware_settings(self) -> None:
        if self._hardware_win and self._hardware_win.winfo_exists():
            self._hardware_win.focus()
            return
        self._hardware_win = HardwareSettingsDialog(self)

    def _reset_audio_stream(self) -> None:
        """Stop and discard the current AudioStream so the next MIC press
        re-opens it with the newly selected device."""
        if self._audio_stream:
            try:
                self._audio_stream.stop()
            except Exception:
                pass
            self._audio_stream = None

    # ── Cleanup ────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        sys.stdout = self._stdout_orig
        sys.stderr = self._stderr_orig
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
    app._log_append("system",
        "Type a query and press SEND (or Return).  "
        "Prefix with  web:  to force live web search.")
    app._log_append("system",
        "Press MIC to start recording. Press STOP (or go silent) to send.")
    app.mainloop()


if __name__ == "__main__":
    main()
