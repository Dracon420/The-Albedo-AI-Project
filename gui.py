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

# Force 1:1 pixel mapping — prevents Windows display scaling from bloating the window.
ctk.set_window_scaling(1.0)
ctk.set_widget_scaling(1.0)

ROOT          = Path(__file__).parent
SETTINGS_PATH = ROOT / "settings.json"

# ── Persona constants ──────────────────────────────────────────────────────

_VOICES_DIR   = ROOT / "voices"

# Display-name → Piper voice file + Vosk wake word string
PERSONA_MAP: dict[str, dict[str, str]] = {
    "Cortana": {
        "voice":     str(_VOICES_DIR / "en_US-kristin-medium.onnx"),
        "wake_word": "hey cortana",
    },
    "Jarvis": {
        "voice":     str(_VOICES_DIR / "en_US-ryan-medium.onnx"),
        "wake_word": "hey jarvis",
    },
}
_PERSONA_DISPLAY = list(PERSONA_MAP.keys())  # ["Cortana", "Jarvis"]

# Background image options — display name → filename (None = plain dark)
_BG_FILES: dict[str, str | None] = {
    "Default":  None,
    "Albedo 1": "Albedo-mission-control-background-1.png",
    "Albedo 2": "albedo-mission-control-background-2.png",
    "Albedo 3": "albedo-mission-control-background-3.png",
    "Albedo 4": "albedo-mission-control-background-4.png",
}


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

C_VIOLET     = "#BD00FF"   # plasma violet (standby indicator)

_STATE_COLOR = {
    "standby":    C_ORANGE,  # high-vis amber — always readable
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

CANVAS_SIZE = 300
ICON_RADIUS = 82
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
        self.geometry("600x680")
        self.minsize(560, 480)
        self.resizable(True, True)
        self.configure(fg_color=C_PANEL)
        self.grab_set()
        self.focus_set()
        self._build()

    # ── helper: labelled password-style entry with show/hide toggle ────────
    def _api_entry(self, parent, label: str, env_key: str) -> ctk.StringVar:
        import os as _os
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=(4, 2))
        ctk.CTkLabel(row, text=label, font=("Courier New", 11), width=140,
                     text_color=C_TEXT, anchor="w").pack(side="left")
        var = ctk.StringVar(value=_os.getenv(env_key, ""))
        entry = ctk.CTkEntry(row, textvariable=var, show="●",
                             font=("Courier New", 11), fg_color=C_BG,
                             border_color=C_BORDER, text_color=C_TEXT,
                             width=300)
        entry.pack(side="left", padx=(6, 4))
        # Right-click context menu — paste API keys
        _ctx = tk.Menu(entry, tearoff=0, bg=C_BG, fg=C_TEXT,
                       activebackground=C_CYAN_DIM, activeforeground=C_TEXT,
                       font=("Courier New", 10))
        _ctx.add_command(label="Paste",
                         command=lambda v=var, e=entry: v.set(e.clipboard_get()))
        _ctx.add_command(label="Clear",
                         command=lambda v=var: v.set(""))
        _ctx.add_command(label="Select All",
                         command=lambda e=entry: e.select_range(0, "end"))

        def _popup(ev, m=_ctx):
            m.tk_popup(ev.x_root, ev.y_root)

        # Bind to the CTkEntry frame AND every child widget inside it
        entry.bind("<Button-3>", _popup)
        for _ch in entry.winfo_children():
            _ch.bind("<Button-3>", _popup)
        # show / hide toggle
        _visible = [False]
        def _toggle(e=entry, v=_visible):
            v[0] = not v[0]
            e.configure(show="" if v[0] else "●")
        ctk.CTkButton(row, text="👁", width=34, height=28,
                      font=("Courier New", 11),
                      fg_color=C_BORDER, hover_color=C_CYAN_DIM,
                      command=_toggle).pack(side="left")
        return var

    def _build(self) -> None:
        import os as _os
        from dotenv import load_dotenv as _ldenv
        _ldenv(override=False)

        # Scrollable inner frame so the dialog is usable at any height
        scroll = ctk.CTkScrollableFrame(self, fg_color=C_PANEL, border_width=0)
        scroll.pack(fill="both", expand=True, padx=0, pady=0)
        p = {"padx": 24, "pady": 5}

        def _section(title: str) -> None:
            ctk.CTkFrame(scroll, fg_color=C_BORDER, height=1).pack(
                fill="x", padx=24, pady=(14, 4))
            ctk.CTkLabel(scroll, text=title, font=("Courier New", 15, "bold"),
                         text_color=C_CYAN).pack(pady=(4, 2))

        # ── Obsidian vault ─────────────────────────────────────────────────
        ctk.CTkLabel(scroll, text="OBSIDIAN VAULT",
                     font=("Courier New", 15, "bold"),
                     text_color=C_CYAN).pack(pady=(20, 2))
        ctk.CTkLabel(scroll, text="Obsidian notes folder — indexed for local RAG",
                     font=("Courier New", 10), text_color=C_MUTED).pack(**p)
        self._var_vault = ctk.StringVar(value=_os.getenv("OBSIDIAN_VAULT_PATH", ""))
        ctk.CTkEntry(scroll, textvariable=self._var_vault,
                     font=("Courier New", 11), fg_color=C_BG,
                     border_color=C_BORDER, text_color=C_TEXT).pack(
                         fill="x", padx=24, pady=(0, 6))
        ctk.CTkButton(scroll, text="RE-INDEX NOW", width=160,
                      font=("Courier New", 12, "bold"),
                      fg_color=C_CYAN_DIM, hover_color=C_CYAN,
                      command=self._reindex).pack(padx=24, pady=(0, 4))

        # ── Persona / wake word ────────────────────────────────────────────
        _section("PERSONA  &  WAKE WORD")
        ctk.CTkLabel(scroll, text="Changes voice model and wake word simultaneously.",
                     font=("Courier New", 10), text_color=C_MUTED).pack(**p)
        active = self._parent._settings.get("active_persona", "cortana").capitalize()
        if active not in PERSONA_MAP:
            active = "Cortana"
        self._persona_var = ctk.StringVar(value=active)
        ctk.CTkOptionMenu(scroll,
                          variable=self._persona_var,
                          values=_PERSONA_DISPLAY,
                          font=("Courier New", 12),
                          fg_color=C_BG, text_color=C_TEXT,
                          button_color=C_BORDER, button_hover_color=C_CYAN_DIM,
                          dropdown_fg_color=C_BG,
                          dropdown_text_color=C_TEXT).pack(
                              padx=24, fill="x", pady=(0, 4))

        # ── API Keys ───────────────────────────────────────────────────────
        _section("API KEYS")
        ctk.CTkLabel(scroll,
                     text="Keys are saved to .env and take effect immediately on save.",
                     font=("Courier New", 10), text_color=C_MUTED).pack(**p)

        self._var_gemini  = self._api_entry(scroll, "Gemini API Key",  "GEMINI_API_KEY")
        self._var_groq    = self._api_entry(scroll, "Groq API Key",    "GROQ_API_KEY")
        self._var_together= self._api_entry(scroll, "Together API Key","TOGETHER_API_KEY")

        # ── Auto-update schedule ───────────────────────────────────────────
        _section("AUTO UPDATE")
        ctk.CTkLabel(scroll,
                     text="How often Albedo checks GitHub for new commits.",
                     font=("Courier New", 10), text_color=C_MUTED).pack(**p)
        _AU_OPTIONS = ["On startup only", "Every 1 hour", "Every 6 hours",
                       "Every 24 hours", "Disabled"]
        current_au = self._parent._settings.get("auto_update", "On startup only")
        if current_au not in _AU_OPTIONS:
            current_au = "On startup only"
        self._var_autoupdate = ctk.StringVar(value=current_au)
        ctk.CTkOptionMenu(scroll,
                          variable=self._var_autoupdate,
                          values=_AU_OPTIONS,
                          font=("Courier New", 12),
                          fg_color=C_BG, text_color=C_TEXT,
                          button_color=C_BORDER, button_hover_color=C_CYAN_DIM,
                          dropdown_fg_color=C_BG,
                          dropdown_text_color=C_TEXT).pack(
                              padx=24, fill="x", pady=(0, 6))
        self._parent._update_btn = ctk.CTkButton(
            scroll, text="UPDATE", width=160,
            font=("Courier New", 12, "bold"),
            fg_color=C_BORDER, hover_color=C_GREEN,
            command=self._parent._run_update)
        self._parent._update_btn.pack(padx=24, pady=(0, 4))

        # ── Background image ───────────────────────────────────────────────
        _section("BACKGROUND")
        ctk.CTkLabel(scroll, text="Border image shown around the main UI.",
                     font=("Courier New", 10), text_color=C_MUTED).pack(**p)
        current_bg = self._parent._settings.get("background", "Default")
        if current_bg not in _BG_FILES:
            current_bg = "Default"
        self._var_bg = ctk.StringVar(value=current_bg)
        ctk.CTkOptionMenu(scroll,
                          variable=self._var_bg,
                          values=list(_BG_FILES.keys()),
                          font=("Courier New", 12),
                          fg_color=C_BG, text_color=C_TEXT,
                          button_color=C_BORDER, button_hover_color=C_CYAN_DIM,
                          dropdown_fg_color=C_BG,
                          dropdown_text_color=C_TEXT).pack(
                              padx=24, fill="x", pady=(0, 6))

        # ── Buttons ────────────────────────────────────────────────────────
        ctk.CTkFrame(scroll, fg_color=C_BORDER, height=1).pack(
            fill="x", padx=24, pady=(14, 6))
        btn = ctk.CTkFrame(scroll, fg_color="transparent")
        btn.pack(pady=(4, 8))
        ctk.CTkButton(btn, text="SAVE", width=130,
                      font=("Courier New", 12, "bold"),
                      command=self._save).pack(side="left", padx=10)
        ctk.CTkButton(btn, text="RESTART", width=130,
                      font=("Courier New", 12, "bold"),
                      fg_color="#330000", hover_color="#660000",
                      text_color="#FF4444",
                      command=self._parent._restart_app).pack(side="left", padx=10)
        self._msg = ctk.CTkLabel(scroll, text="", font=("Courier New", 10),
                                 text_color=C_MUTED)
        self._msg.pack(pady=(0, 12))

    def _save(self) -> None:
        _update_env("OBSIDIAN_VAULT_PATH", self._var_vault.get().strip())
        _update_env("GEMINI_API_KEY",      self._var_gemini.get().strip())
        _update_env("GROQ_API_KEY",        self._var_groq.get().strip())
        _update_env("TOGETHER_API_KEY",    self._var_together.get().strip())

        import importlib, albedo.config as _cfg
        importlib.reload(_cfg)

        # Reinitialise swarm clients so new keys take effect without restart
        try:
            from swarm import reinit_swarm_clients
            reinit_swarm_clients()
        except Exception as exc:
            print(f"[settings] swarm reinit error: {exc}")

        self._parent._settings["auto_update"] = self._var_autoupdate.get()
        bg_choice = self._var_bg.get()
        self._parent._settings["background"] = bg_choice
        self._parent._apply_background(bg_choice)
        _save_settings(self._parent._settings)
        self._parent._apply_persona(self._persona_var.get())
        self._parent._update_check_ran = False  # allow re-run after settings change
        self._parent._reschedule_update_check()
        self._msg.configure(text="Saved. API clients reloaded.",
                            text_color=C_GREEN)

    def _reindex(self) -> None:
        self._msg.configure(text="Indexing...", text_color=C_CYAN)
        self.update()
        def _run() -> None:
            from memory import index_obsidian_vault
            status = index_obsidian_vault()
            self.after(0, lambda: self._msg.configure(
                text=status, text_color=C_GREEN))
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
        self.geometry("900x560")
        self.minsize(600, 380)
        self.configure(fg_color=C_PANEL)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build()
        # Populate with buffered history from before the dialog was opened
        if parent._console_buf:
            self._append("".join(parent._console_buf))
        # Position to the right of the Mission Control window (or left if off-screen)
        self._place_beside_parent()

    def _build(self) -> None:
        hdr = ctk.CTkFrame(self, fg_color=C_BG, corner_radius=0, height=46)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="DEVELOPER CONSOLE  //  stdout / stderr",
                     font=("Courier New", 13, "bold"),
                     text_color=C_CYAN).pack(side="left", padx=16, pady=10)
        ctk.CTkButton(hdr, text="CLEAR", width=76, height=30,
                      font=("Courier New", 11, "bold"),
                      fg_color=C_BORDER, hover_color=C_DANGER,
                      command=self._clear).pack(side="right", padx=12, pady=8)

        self._txt = ctk.CTkTextbox(self, font=("Courier New", 13),
                                   fg_color=C_BG, text_color=C_TEXT,
                                   wrap="word", state="disabled", border_width=0,
                                   scrollbar_button_color=C_BORDER)
        self._txt.pack(fill="both", expand=True, padx=6, pady=6)

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

    def _place_beside_parent(self) -> None:
        self.update_idletasks()
        px = self._parent.winfo_x()
        py = self._parent.winfo_y()
        pw = self._parent.winfo_width()
        dw = self.winfo_width()
        dh = self.winfo_height()
        sw = self.winfo_screenwidth()
        # Try right side first; fall back to left if it would clip off-screen
        x = px + pw + 8
        if x + dw > sw:
            x = max(0, px - dw - 8)
        self.geometry(f"+{x}+{py}")
        self.lift()
        self.focus_force()

    def _on_close(self) -> None:
        self._parent._console_win = None
        self.destroy()


# ── Radial telemetry dial ──────────────────────────────────────────────────

class RadialDial(tk.Canvas):
    """
    Circular arc gauge drawn on a tk.Canvas.
    set(value) accepts 0.0 – 1.0 and redraws immediately.
    The arc starts at 12 o'clock and sweeps clockwise.
    """

    def __init__(self, parent, size: int = 64,
                 fill_color: str = C_CYAN,
                 track_color: str = "#1A1A1A",
                 ring_width: int = 6, **kw) -> None:
        super().__init__(parent, width=size, height=size,
                         bg=C_BG, highlightthickness=0, **kw)
        self._size  = size
        self._fill  = fill_color
        self._track = track_color
        self._rw    = ring_width
        self._value = 0.0
        self._draw()

    def set(self, value: float) -> None:
        self._value = max(0.0, min(1.0, float(value)))
        self._draw()

    def get(self) -> float:
        return self._value

    def _draw(self) -> None:
        self.delete("all")
        m  = self._rw + 3
        x0, y0, x1, y1 = m, m, self._size - m, self._size - m

        # Background track — full ring
        self.create_arc(x0, y0, x1, y1,
                        start=90, extent=359.9,
                        outline=self._track, width=self._rw,
                        style=tk.ARC)

        # Value arc — clockwise from 12 o'clock
        if self._value > 0:
            self.create_arc(x0, y0, x1, y1,
                            start=90, extent=-self._value * 359.9,
                            outline=self._fill, width=self._rw,
                            style=tk.ARC)

        # Centre percentage label — font scales with dial size
        cx = cy = self._size // 2
        font_sz = max(8, self._size // 9)
        self.create_text(cx, cy,
                         text=f"{int(self._value * 100)}%",
                         fill=self._fill,
                         font=("Consolas", font_sz, "bold"))


# ── Main window ────────────────────────────────────────────────────────────

class AlbedoGUI(ctk.CTk):

    def __init__(self) -> None:
        super().__init__()
        self.title("ALBEDO  //  MISSION CONTROL")
        self.geometry("1000x800")
        self.minsize(860, 640)
        self.configure(fg_color=C_BG)

        self._state        = "standby"
        self._ui_queue: queue.Queue = queue.Queue()
        self._voice_stop   = threading.Event()
        self._abort_flag   = threading.Event()
        self._canvas       = None   # no orb canvas in dashboard layout
        self._hud_ram_dial      = None   # set by _build_ui
        self._hud_ssd_dial      = None   # set by _build_ui
        self._gemini_tbar_lbl   = None   # set by _build_ui
        self._audio_stream = None   # AudioStream, lazy-init
        self._settings_win = None
        self._hardware_win = None
        self._console_win  = None   # kept for compat; panel replaces it
        self._console_buf: list[str] = []
        self._panel_visible = False
        self._side_panel: ctk.CTkFrame | None = None
        self._update_btn: ctk.CTkButton | None = None
        self._update_available = False
        self._update_check_after_id: str | None = None
        self._update_check_ran = False  # guard: only one startup check

        # Capture the git HEAD at launch so we can detect disk-level code changes
        # even when local HEAD == remote HEAD (same-machine push workflow).
        try:
            import subprocess as _sp_init
            _hc = _sp_init.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=5,
                cwd=str(ROOT), creationflags=_sp_init.CREATE_NO_WINDOW,
            )
            self._startup_commit: str = _hc.stdout.strip() if _hc.returncode == 0 else ""
        except Exception:
            self._startup_commit = ""
        # Event-loop hygiene — tracked so _on_close() can cancel cleanly
        self._closing       = False
        self._poll_after_id = None
        self._pulse_phase  = 0.0
        self._icon_photo   = None   # ImageTk ref kept alive
        self._settings     = _load_settings()
        self._scan_btn     = None   # set by _build_ui
        self._audio_btn    = None   # AUDIO ON/MUTE toggle — set by _build_ui
        self._audio_muted  = False  # TTS kill-switch
        self._audio_streamed_for_current_response = False
        self._tts_override: str | None = None  # spoken prose override (e.g. audit)
        # Hardware labels — detected once at boot for the telemetry HUD
        try:
            from system_stats import get_cpu_name, get_gpu_name
            self._hw_cpu_label = get_cpu_name()
            self._hw_gpu_label = get_gpu_name()
        except Exception:
            self._hw_cpu_label = "CPU"
            self._hw_gpu_label = "SYS GPU"
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
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Pre-warm Vosk in background so first MIC press is instant
        threading.Thread(target=self._prewarm_vosk, daemon=True).start()

        # Start live HUD bar updates (CPU %) and check first-boot last
        self._update_hud_bars()
        self.after(150, self._show_startup_messages)
        self._check_first_boot()

        self._bg_pil   = None   # PIL Image for background.png (kept for resize)
        self._bg_photo = None   # ImageTk reference (must stay alive)

    # ── First-boot onboarding (single-root) ───────────────────────────────

    def _check_first_boot(self) -> None:
        """
        If .env lacks GEMINI_API_KEY or OBSIDIAN_VAULT_PATH, hide the main
        window and show the onboarding wizard as a CTkToplevel.  This keeps
        exactly ONE CTk() root alive for the entire process lifetime, which
        eliminates the check_dpi_scaling ghost-thread errors.
        """
        env_file = ROOT / ".env"

        def _env_complete() -> bool:
            if not env_file.exists():
                return False
            from dotenv import dotenv_values
            cfg = dotenv_values(env_file)
            return (bool(cfg.get("GEMINI_API_KEY",     "").strip()) and
                    bool(cfg.get("OBSIDIAN_VAULT_PATH", "").strip()))

        if _env_complete():
            return

        self.withdraw()
        from onboarding import OnboardingWizard
        OnboardingWizard(self, on_complete=self._on_onboarding_done)

    def _on_onboarding_done(self) -> None:
        """Called by OnboardingWizard after it destroys itself."""
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=ROOT / ".env", override=True)
        self.deiconify()

    def _show_startup_messages(self) -> None:
        self._log_append("system", "Albedo Mission Control online.")
        self._log_append("system",
            "Type a query and press SEND (or Return).  "
            "Prefix with  web:  to force live web search.")
        self._log_append("system",
            "Press MIC to start recording. Press STOP (or go silent) to send.")

    # ── Live HUD telemetry ─────────────────────────────────────────────────

    def _set_gemini_active(self) -> None:
        """Mark the GEMINI telemetry tile as active (called on main thread)."""
        try:
            self._gemini_tbar_lbl.configure(
                text="GEMINI: ACTIVE", text_color=C_CYAN)
        except Exception:
            pass

    def _set_gemini_standby(self) -> None:
        """Revert the GEMINI telemetry tile to standby (called on main thread)."""
        try:
            self._gemini_tbar_lbl.configure(
                text="GEMINI: STANDBY", text_color=C_ORANGE)
            self.update_idletasks()
        except Exception:
            pass

    def _update_hud_bars(self) -> None:
        """Refresh all four HUD gauges every 2 s via psutil + GPUtil."""
        if self._closing:
            return
        try:
            import psutil
            self._hud_cpu_dial.set(psutil.cpu_percent() / 100.0)
            if self._hud_ram_dial:
                self._hud_ram_dial.set(psutil.virtual_memory().percent / 100.0)
            if self._hud_ssd_dial:
                self._hud_ssd_dial.set(psutil.disk_usage("C:").percent / 100.0)
        except Exception:
            pass
        try:
            from system_stats import get_gpu_load
            self._hud_vram_dial.set(get_gpu_load())
        except Exception:
            pass
        self.after(2000, self._update_hud_bars)

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ══════════════════════════════════════════════════════════════════
        # BACKGROUND CANVAS — fills the window, shows background.png and
        # corner HUD brackets.  All content sits inside it with padding so
        # the image is visible as a visible border around the UI.
        # ══════════════════════════════════════════════════════════════════
        _bg = tk.Canvas(self, bg=C_BG, highlightthickness=0)
        _bg.pack(fill='both', expand=True)
        self._bg_canvas = _bg

        # Load whichever background the user last selected (or none for Default)
        _bg_choice = self._settings.get("background", "Default")
        _bg_fname  = _BG_FILES.get(_bg_choice)
        if _bg_fname:
            _bg_path = ROOT / _bg_fname
            if _bg_path.exists():
                try:
                    self._bg_pil = Image.open(_bg_path).convert('RGB')
                    print(f'[bg] {_bg_fname} loaded')
                except Exception as exc:
                    print(f'[bg] failed to load {_bg_fname}: {exc}')

        _last_bg_sz = [0, 0]

        def _draw_bg(event=None, force: bool = False):
            w, h = _bg.winfo_width(), _bg.winfo_height()
            if w < 2 or h < 2 or ([w, h] == _last_bg_sz and not force):
                return
            _last_bg_sz[:] = [w, h]
            _bg.delete('bg_img', 'hud')

            # Background image (stretched to window size)
            if self._bg_pil is not None:
                try:
                    img = self._bg_pil.resize((w, h), Image.LANCZOS)
                    self._bg_photo = ImageTk.PhotoImage(img)
                    _bg.create_image(0, 0, image=self._bg_photo,
                                     anchor='nw', tags='bg_img')
                except Exception:
                    pass

            # Corner HUD brackets drawn in the visible border area
            M, ARM = 8, 36
            CMID = '#004855'
            for x, y, sx, sy in [(M, M, 1, 1), (w-M, M, -1, 1),
                                  (M, h-M, 1, -1), (w-M, h-M, -1, -1)]:
                t = ARM // 3
                _bg.create_line(x, y, x+sx*ARM, y,
                                fill=C_CYAN, width=2, tags='hud', capstyle='round')
                _bg.create_line(x, y, x, y+sy*ARM,
                                fill=C_CYAN, width=2, tags='hud', capstyle='round')
                _bg.create_line(x+sx*t, y, x+sx*t, y+sy*8,
                                fill=CMID, width=1, tags='hud')
                _bg.create_line(x, y+sy*t, x+sx*8, y+sy*t,
                                fill=CMID, width=1, tags='hud')
                _bg.create_oval(x-3, y-3, x+3, y+3,
                                fill=C_CYAN, outline='', tags='hud')

            # Edge lines connecting corners (broken in centre)
            GAP = 80
            for x0, x1 in [(M+ARM+4, w//2-GAP), (w//2+GAP, w-M-ARM-4)]:
                _bg.create_line(x0, M,   x1, M,   fill=CMID, width=1, tags='hud')
                _bg.create_line(x0, h-M, x1, h-M, fill=CMID, width=1, tags='hud')
            for y0, y1 in [(M+ARM+4, h//2-GAP), (h//2+GAP, h-M-ARM-4)]:
                _bg.create_line(M,   y0, M,   y1, fill=CMID, width=1, tags='hud')
                _bg.create_line(w-M, y0, w-M, y1, fill=CMID, width=1, tags='hud')

        _bg.bind('<Configure>', lambda e: _draw_bg())
        self._draw_bg = _draw_bg   # allow _apply_background to force a redraw

        # ══════════════════════════════════════════════════════════════════
        # ROOT HORIZONTAL LAYOUT: main column ║ side panel ║ toggle strip
        # Content is inset so the background canvas border is visible.
        # ══════════════════════════════════════════════════════════════════
        BORDER = 50   # px of visible background image around the content
        _root_h = ctk.CTkFrame(_bg, fg_color=C_BG, corner_radius=2)
        _root_h.pack(fill="both", expand=True, padx=BORDER, pady=BORDER)
        _root_h.grid_columnconfigure(0, weight=1)   # main content — elastic
        _root_h.grid_columnconfigure(1, weight=0)   # side panel — fixed 265px
        _root_h.grid_columnconfigure(2, weight=0)   # toggle strip — always 18px
        _root_h.grid_rowconfigure(0, weight=1)

        # Main content column — receives all dashboard / chat / input widgets
        _main = ctk.CTkFrame(_root_h, fg_color=C_BG, corner_radius=0)
        _main.grid(row=0, column=0, sticky="nsew")

        # Side panel — built now, hidden until toggled
        self._side_panel = ctk.CTkFrame(
            _root_h, fg_color=C_PANEL, corner_radius=0,
            border_width=1, border_color=C_BORDER, width=210)
        self._side_panel.grid(row=0, column=1, sticky="nsew")
        self._side_panel.grid_propagate(False)
        self._side_panel.grid_remove()          # hidden by default
        self._build_side_panel(self._side_panel)

        # Toggle strip — always visible, 18px
        _tstrip = ctk.CTkFrame(_root_h, fg_color=C_BORDER, corner_radius=0, width=18)
        _tstrip.grid(row=0, column=2, sticky="nsew")
        _tstrip.grid_propagate(False)
        self._toggle_arrow_lbl = ctk.CTkLabel(
            _tstrip, text="◄", font=("Courier New", 11, "bold"), text_color=C_CYAN)
        self._toggle_arrow_lbl.place(relx=0.5, rely=0.5, anchor="center")
        _tstrip.bind("<Button-1>", lambda e: self._toggle_side_panel())
        self._toggle_arrow_lbl.bind("<Button-1>", lambda e: self._toggle_side_panel())

        # Schedule update check according to user preference (5 s grace on startup)
        self.after(5000, self._reschedule_update_check)

        # ══════════════════════════════════════════════════════════════════
        # UNIFIED DASHBOARD — 3-column grid above chat feed
        # ══════════════════════════════════════════════════════════════════
        dash = ctk.CTkFrame(_main, fg_color=C_BG, corner_radius=0)
        dash.pack(fill="x", expand=False)

        dash.grid_columnconfigure(0, weight=1)
        dash.grid_columnconfigure(1, weight=0)
        dash.grid_columnconfigure(2, weight=1)
        dash.grid_rowconfigure(0, weight=1)
        dash.grid_rowconfigure(1, weight=0)

        def _make_dial(parent, label: str, color: str) -> RadialDial:
            col = ctk.CTkFrame(parent, fg_color="transparent")
            col.pack(side="left", expand=True, fill="x")
            dial = RadialDial(col, size=120, ring_width=10,
                              fill_color=color, track_color="#1A1A1A")
            dial.set(0.0)
            dial.pack()
            ctk.CTkLabel(col, text=label,
                         font=("Consolas", 11, "bold"), text_color=color).pack()
            return dial

        # ── Col 0 — Left flank: CPU + VRAM ───────────────────────────────
        left = ctk.CTkFrame(dash, fg_color="transparent")
        left.grid(row=0, column=0, sticky="ew", padx=(8, 0), pady=8)
        left_dials = ctk.CTkFrame(left, fg_color="transparent")
        left_dials.pack(fill="x", expand=True)
        self._hud_cpu_dial  = _make_dial(left_dials, self._hw_cpu_label, C_CYAN)
        self._hud_vram_dial = _make_dial(left_dials, self._hw_gpu_label, C_PURPLE)

        # ── Col 1 — Center: logo + title + state chip + LOGS ─────────────
        center = ctk.CTkFrame(dash, fg_color="transparent")
        center.grid(row=0, column=1, sticky="nsew", pady=10)

        logo_path = ROOT / "albedo_logo.png"
        _logo_shown = False
        if logo_path.exists():
            try:
                _pil = Image.open(logo_path).convert("RGBA").resize(
                    (180, 180), Image.LANCZOS)
                self._hdr_logo = ctk.CTkImage(_pil, size=(180, 180))
                ctk.CTkLabel(center, image=self._hdr_logo,
                             text="").pack(pady=(4, 2))
                _logo_shown = True
            except Exception:
                pass
        if not _logo_shown:
            ctk.CTkLabel(center, text="▸ A",
                         font=("Courier New", 72, "bold"),
                         text_color=C_CYAN).pack(pady=(4, 2))

        ctk.CTkLabel(center, text="ALBEDO  //  MISSION CONTROL",
                     font=("Courier New", 12, "bold"),
                     text_color=C_CYAN).pack()

        chip_row = ctk.CTkFrame(center, fg_color="transparent")
        chip_row.pack(pady=(2, 4))
        self._state_chip = ctk.CTkLabel(
            chip_row, text="STANDBY",
            font=("Courier New", 12, "bold"), text_color=C_ORANGE)
        self._state_chip.pack(side="left", padx=(0, 10))
        ctk.CTkButton(
            chip_row, text="LOGS", width=60, height=26,
            font=("Courier New", 11, "bold"),
            fg_color=C_BORDER, hover_color=C_CYAN_DIM, text_color=C_CYAN,
            command=self._open_console).pack(side="left")

        # ── Col 2 — Right flank: RAM + SSD ───────────────────────────────
        right = ctk.CTkFrame(dash, fg_color="transparent")
        right.grid(row=0, column=2, sticky="ew", padx=(0, 8), pady=8)
        right_dials = ctk.CTkFrame(right, fg_color="transparent")
        right_dials.pack(fill="x", expand=True)
        self._hud_ram_dial = _make_dial(right_dials, "SYS RAM", C_GREEN)
        self._hud_ssd_dial = _make_dial(right_dials, "SSD C:",  C_ORANGE)

        # ── Row 1 — Full-width telemetry status bar ───────────────────────
        tbar = ctk.CTkFrame(dash, fg_color="transparent")
        tbar.grid(row=1, column=0, columnspan=3, sticky="ew", padx=8, pady=(0, 8))

        for _txt, _col in [
            ("UPLINK: SECURE",  C_CYAN),
            ("EDGE-TTS: READY", C_GREEN),
            ("VEC_DB: ONLINE",  C_CYAN),
        ]:
            _tc = ctk.CTkFrame(tbar, fg_color="transparent")
            _tc.pack(side="left", expand=True, fill="x")
            ctk.CTkLabel(_tc, text=_txt, text_color=_col,
                         font=("Consolas", 11, "bold"),
                         anchor="center").pack(fill="x")

        # GEMINI tile — kept as an instance attribute so _set_gemini_active()
        # can update it live without rebuilding the widget.
        _gtc = ctk.CTkFrame(tbar, fg_color="transparent")
        _gtc.pack(side="left", expand=True, fill="x")
        self._gemini_tbar_lbl = ctk.CTkLabel(
            _gtc, text="GEMINI: STANDBY",
            font=("Consolas", 11, "bold"),
            text_color=C_ORANGE, anchor="center",
        )
        self._gemini_tbar_lbl.pack(fill="x")

        # Thin 1 px structural border below the dashboard
        ctk.CTkFrame(_main, fg_color=C_BORDER, height=1).pack(fill="x", expand=False)

        # ── Output log (borderless; only CMD_INPUT row carries the cyan border) ─
        log_outer = ctk.CTkFrame(_main, fg_color=C_PANEL, corner_radius=8,
                                 border_width=0)
        log_outer.pack(fill="both", expand=True, padx=16, pady=(14, 6))

        # HUD corner tags inside the log panel
        log_hdr = ctk.CTkFrame(log_outer, fg_color="transparent", height=20)
        log_hdr.pack(fill="x", padx=6, pady=(4, 0))
        log_hdr.pack_propagate(False)
        ctk.CTkLabel(log_hdr, text="// CHAT_FEED",
                     font=("Courier New", 12, "bold"), text_color=C_CYAN).pack(side="left")
        ctk.CTkLabel(log_hdr, text="[ STREAM: ACTIVE ]",
                     font=("Courier New", 12, "bold"), text_color=C_ORANGE).pack(side="right")

        self._log = ctk.CTkTextbox(log_outer, font=("Consolas", 14),
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
        cmd_hdr = ctk.CTkFrame(_main, fg_color="transparent", height=18)
        cmd_hdr.pack(fill="x", expand=False, padx=18)
        cmd_hdr.pack_propagate(False)
        ctk.CTkLabel(cmd_hdr, text="[ CMD_INPUT ]",
                     font=("Courier New", 12, "bold"), text_color=C_CYAN).pack(side="left")
        ctk.CTkLabel(cmd_hdr, text="// INPUT_READY",
                     font=("Courier New", 12, "bold"), text_color=C_GREEN).pack(side="right")

        # ── Input row (neon border on entry) ────────────────────────────────
        row = ctk.CTkFrame(_main, fg_color=C_PANEL, corner_radius=8,
                           border_width=2, border_color=C_CYAN)
        row.pack(fill="x", expand=False, padx=16, pady=(2, 12))

        self._mic_btn = ctk.CTkButton(row, text="MIC", width=68, height=48,
                                      font=("Courier New", 15, "bold"),
                                      fg_color=C_BORDER, hover_color=C_CYAN,
                                      command=self._handle_mic)
        self._mic_btn.pack(side="left", padx=(10, 4), pady=10)

        self._scan_btn = ctk.CTkButton(row, text="SCAN", width=68, height=48,
                                       font=("Courier New", 13, "bold"),
                                       fg_color=C_BORDER, hover_color=C_CYAN,
                                       command=self._handle_scan)
        self._scan_btn.pack(side="left", padx=(0, 4), pady=10)

        self._entry = ctk.CTkEntry(row,
                                   placeholder_text="Type a query or press MIC...",
                                   font=("Consolas", 18),
                                   fg_color=C_BG, border_color=C_CYAN,
                                   text_color=C_TEXT, height=48)
        self._entry.pack(side="left", fill="x", expand=True, padx=4, pady=10)
        self._entry.bind("<Return>", lambda _: self._handle_send())

        self._send_btn = ctk.CTkButton(row, text="SEND", width=78, height=48,
                                       font=("Courier New", 13, "bold"),
                                       fg_color=C_CYAN_DIM, hover_color=C_CYAN,
                                       text_color="#000000",
                                       command=self._handle_send)
        self._send_btn.pack(side="left", padx=4, pady=10)

        self._audio_btn = ctk.CTkButton(
            row, text="AUDIO: ON", width=110, height=48,
            font=("Courier New", 13, "bold"),
            fg_color=C_GREEN, hover_color="#22CC00",
            text_color="#000000",
            command=self._toggle_audio_mute,
        )
        self._audio_btn.pack(side="left", padx=(0, 10), pady=10)

    # ── Circuit board background ───────────────────────────────────────────

    def _draw_circuit_board(self) -> None:
        """
        Draw an intricate PCB-style circuit board behind the orb icon.
        All elements use tag='circuit' so they sit below 'ring' and 'icon'.

        Geometry (300 px canvas, ICON_RADIUS=82, KEEP=96):
          - Outer perimeter buses at ±44 px from edges  (always clear of keep-out)
          - Secondary signal buses stop at x≈75/225, y≈75/225  (keep-out boundary)
          - Three concentric orbital rings route around the core
          - Cardinal glow spokes bridge secondary buses to the orbital ring
        """
        cv = self._canvas
        W  = CANVAS_SIZE
        CX = CY = W // 2
        KEEP = ICON_RADIUS + 14   # 96 for 300 px canvas

        # Palette — deep blues/cyans blended toward C_BG (#0A0E17)
        T_GRID   = "#0A1A2E"   # barely-visible dot grid
        T_DEEP   = "#071C3A"   # power/ground bus (darkest)
        T_DIM    = "#0A2E5E"   # background signal traces
        T_MED    = "#0C4888"   # medium routed traces
        T_BRIGHT = "#0870B0"   # bright corner routes
        T_HOT    = "#0898D0"   # hot connection traces
        T_CYAN   = "#00BCDE"   # primary data lines / spokes
        PAD_C    = "#00486A"   # via / pad fill
        PAD_HOT  = "#00A8C8"   # via inner glow
        CHIP_F   = "#040C1C"   # IC body fill
        CHIP_O   = "#0A2E5A"   # IC body outline (normal)
        CHIP_HOT = "#0C4880"   # IC body outline (data interface)

        def ln(pts, col=T_MED, w=1):
            cv.create_line(*pts, fill=col, width=w, tags="circuit",
                           capstyle="round", joinstyle="round")

        def gln(pts, col_bg, col_fg, w_bg=6, w_fg=2):
            """Glow trace: wide dim underlay then narrow bright line on top."""
            ln(pts, col_bg, w_bg)
            ln(pts, col_fg, w_fg)

        def pad(x, y, r=2, col=PAD_C):
            cv.create_oval(x-r, y-r, x+r, y+r, fill=col, outline="", tags="circuit")

        def via(x, y):
            cv.create_oval(x-4, y-4, x+4, y+4, fill=PAD_C,
                           outline=T_HOT, width=1, tags="circuit")
            cv.create_oval(x-1, y-1, x+1, y+1, fill=PAD_HOT,
                           outline="", tags="circuit")

        def chip(x1, y1, x2, y2, hot=False):
            o = CHIP_HOT if hot else CHIP_O
            cv.create_rectangle(x1, y1, x2, y2,
                                fill=CHIP_F, outline=o, width=1, tags="circuit")
            mx, nr = (x1+x2)//2, min(5, (x2-x1)//5)
            cv.create_arc(mx-nr, y1-nr//2, mx+nr, y1+nr//2,
                          start=0, extent=180, fill=CHIP_F, outline=o,
                          width=1, tags="circuit")

        # ── 1. Dot grid (skip keep-out + small margin) ─────────────────────
        for gx in range(12, W, 12):
            for gy in range(12, W, 12):
                if (gx-CX)**2 + (gy-CY)**2 > (KEEP+8)**2:
                    cv.create_oval(gx-1, gy-1, gx+1, gy+1,
                                   fill=T_GRID, outline="", tags="circuit")

        # ── 2. IC bodies ───────────────────────────────────────────────────
        # Corner large chips
        chip(4,    4,    64,    42)
        chip(W-64, 4,    W-4,   42)
        chip(4,    W-42, 64,    W-4)
        chip(W-64, W-42, W-4,   W-4)
        # Mid-edge data interface chips (hot border — they feed the core)
        chip(4,     CY-28, 42,     CY+28, hot=True)
        chip(W-42,  CY-28, W-4,    CY+28, hot=True)
        chip(CX-32, 4,     CX+32,  30,    hot=True)
        chip(CX-32, W-30,  CX+32,  W-4,   hot=True)
        # Auxiliary small chips on the outer buses (safely >120 px from center)
        chip(4,     CY-72, 30,     CY-50)
        chip(4,     CY+50, 30,     CY+72)
        chip(W-30,  CY-72, W-4,    CY-50)
        chip(W-30,  CY+50, W-4,    CY+72)

        # ── 3. Main perimeter power/ground buses ───────────────────────────
        ln([0,    44,   W,     44],   T_DEEP, 3)
        ln([0,    W-44, W,     W-44], T_DEEP, 3)
        ln([44,   0,    44,    W],    T_DEEP, 3)
        ln([W-44, 0,    W-44,  W],    T_DEEP, 3)

        # ── 4. Secondary signal buses (partial — stop at keep-out boundary) ─
        # At y=90: keep-out boundary ≈ x=75 and x=225
        ln([0,    90,   75,    90],   T_MED, 2)
        ln([W,    90,   225,   90],   T_MED, 2)
        ln([0,    W-90, 75,    W-90], T_MED, 2)
        ln([W,    W-90, 225,   W-90], T_MED, 2)
        # At x=90: keep-out boundary ≈ y=75 and y=225
        ln([90,   0,    90,    75],   T_MED, 2)
        ln([W-90, 0,    W-90,  75],   T_MED, 2)
        ln([90,   W,    90,    225],  T_MED, 2)
        ln([W-90, W,    W-90,  225],  T_MED, 2)

        # ── 5. Corner L-route traces ────────────────────────────────────────
        ln([44,   44,   90,   44,   90,   90],             T_BRIGHT, 2)
        ln([W-44, 44,   W-90, 44,   W-90, 90],             T_BRIGHT, 2)
        ln([44,   W-44, 90,   W-44, 90,   W-90],           T_BRIGHT, 2)
        ln([W-44, W-44, W-90, W-44, W-90, W-90],           T_BRIGHT, 2)

        # ── 6. Connector traces from mid-edge chips to secondary buses ──────
        ln([42,   CY,   75,   CY],   T_MED, 2)
        ln([W-42, CY,   225,  CY],   T_MED, 2)
        ln([CX,   30,   CX,   75],   T_MED, 2)
        ln([CX,   W-30, CX,   225],  T_MED, 2)

        # ── 7. Data spokes to core (glow effect) ────────────────────────────
        gln([75,  CY,  CX-KEEP, CY],  T_DIM, T_CYAN)
        gln([225, CY,  CX+KEEP, CY],  T_DIM, T_CYAN)
        gln([CX,  75,  CX, CY-KEEP],  T_DIM, T_CYAN)
        gln([CX,  225, CX, CY+KEEP],  T_DIM, T_CYAN)

        # ── 8. Orbital ring traces routing around the core ──────────────────
        for r, col, w in [(KEEP+2, T_DIM, 1), (KEEP+7, T_MED, 1), (KEEP+14, T_BRIGHT, 2)]:
            cv.create_oval(CX-r, CY-r, CX+r, CY+r,
                           outline=col, width=w, fill="", tags="circuit")

        # ── 9. IC pin stubs ────────────────────────────────────────────────
        # Corner chip bottom-edge pins
        for px in range(10, 60, 8):
            ln([px, 42, px, 58], T_BRIGHT); pad(px, 58)
            ln([px, W-42, px, W-58], T_BRIGHT); pad(px, W-58)
        for px in range(W-58, W-8, 8):
            ln([px, 42, px, 58], T_BRIGHT); pad(px, 58)
            ln([px, W-42, px, W-58], T_BRIGHT); pad(px, W-58)
        # Mid-edge chip side pins
        for py in range(CY-24, CY+26, 8):
            ln([42, py, 58, py], T_BRIGHT); pad(58, py)
            ln([W-42, py, W-58, py], T_BRIGHT); pad(W-58, py)
        # Top/bottom mid chip bottom pins
        for px in range(CX-28, CX+30, 8):
            ln([px, 30, px, 48], T_BRIGHT); pad(px, 48)
            ln([px, W-30, px, W-48], T_BRIGHT); pad(px, W-48)

        # ── 10. Via pads at bus intersections ──────────────────────────────
        for x in [44, 90, CX, W-90, W-44]:
            via(x, 44); via(x, W-44)
        for y in [90, CY, W-90]:
            via(44, y); via(W-44, y)
        # Corner L-route junction vias
        via(90, 90); via(W-90, 90); via(90, W-90); via(W-90, W-90)
        # Spoke terminus vias (at orbital ring boundary)
        via(CX-KEEP, CY); via(CX+KEEP, CY)
        via(CX, CY-KEEP); via(CX, CY+KEEP)
        # Spoke root vias (at secondary bus ends)
        via(75, CY); via(225, CY)
        via(CX, 75); via(CX, 225)

        # ── 11. Bus stub traces along perimeter buses ───────────────────────
        for bx in range(66, W-65, 22):
            ln([bx, 44, bx, 60], T_DIM); pad(bx, 60)
            ln([bx, W-44, bx, W-60], T_DIM); pad(bx, W-60)
        for by in range(66, W-65, 22):
            ln([44, by, 60, by], T_DIM); pad(60, by)
            ln([W-44, by, W-60, by], T_DIM); pad(W-60, by)

    # ── Icon loading ───────────────────────────────────────────────────────

    def _load_icon(self) -> None:
        self._draw_circuit_board()   # PCB traces behind the icon
        logo = ROOT / "albedo_logo.png"
        if logo.exists():
            try:
                img = (Image.open(logo)
                           .convert("RGBA")
                           .resize((ICON_RADIUS * 2, ICON_RADIUS * 2), Image.LANCZOS))
                self._icon_photo = ImageTk.PhotoImage(img)
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
        if self._canvas is None:
            return
        self._pulse_phase = (self._pulse_phase + 0.07) % (2 * math.pi)
        self._canvas.delete("ring")
        color = _STATE_COLOR[self._state]

        if self._state == "standby":
            r = ICON_RADIUS + 10
            self._canvas.create_oval(CENTER - r, CENTER - r,
                                     CENTER + r, CENTER + r,
                                     outline=C_BORDER, width=1, tags="ring")
        elif self._state == "processing":
            # Inner pulsing rings
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
            # Outer spinning arcs — "thinking" indicator
            cw_deg  = (math.degrees(self._pulse_phase * 3.5)) % 360
            ccw_deg = (-math.degrees(self._pulse_phase * 2.2)) % 360
            r1, r2  = ICON_RADIUS + 52, ICON_RADIUS + 61
            self._canvas.create_arc(
                CENTER - r1, CENTER - r1, CENTER + r1, CENTER + r1,
                start=cw_deg,  extent=80,  outline=C_CYAN,     width=2,
                style="arc", tags="ring",
            )
            self._canvas.create_arc(
                CENTER - r2, CENTER - r2, CENTER + r2, CENTER + r2,
                start=ccw_deg, extent=50, outline=C_CYAN_DIM,  width=1,
                style="arc", tags="ring",
            )
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

        # SEND ↔ ABORT transformation
        if state == "standby":
            self._send_btn.configure(
                text="SEND", fg_color=C_CYAN_DIM, hover_color=C_CYAN,
                text_color="#000000", command=self._handle_send, state="normal",
            )
        elif busy:
            self._send_btn.configure(
                text="ABORT", fg_color="#8B0000", hover_color="#AA0000",
                text_color="#ffffff", command=self._handle_abort, state="normal",
            )
        elif state == "listening":
            self._send_btn.configure(state="disabled")

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

    def _log_stream_response(self, text: str, speak_text: str | None,
                             voice: str | None, device) -> None:
        """
        Type an Albedo response word-by-word into the chat log, then start
        TTS after a short head-start so text and audio feel synchronised.
        Runs entirely on the UI thread via self.after() scheduling.
        """
        ts  = datetime.now().strftime("%H:%M")
        tb  = self._log._textbox
        WORD_MS = 38   # ~26 words/sec — fast typewriter, easy to follow
        # Start TTS after 12 words have appeared or 600 ms, whichever comes first
        words = text.strip().split()
        tts_start_ms = min(12 * WORD_MS, 600)

        # Write the coloured timestamp + role prefix immediately
        self._log.configure(state="normal")
        tb.insert("end", f"\n[{ts}] ALBEDO  ", "albedo")
        self._log.configure(state="disabled")
        tb.see("end")

        def _type(i: int) -> None:
            if self._abort_flag.is_set():
                return
            if i >= len(words):
                self._log.configure(state="normal")
                tb.insert("end", "\n\n")
                self._log.configure(state="disabled")
                tb.see("end")
                # If muted, transition to standby here
                if self._audio_muted or speak_text is None:
                    self._set_state("standby")
                return
            self._log.configure(state="normal")
            tb.insert("end", words[i] + (" " if i < len(words) - 1 else ""))
            self._log.configure(state="disabled")
            tb.see("end")
            self.after(WORD_MS, lambda: _type(i + 1))

        def _launch_tts() -> None:
            if self._audio_muted or self._abort_flag.is_set() or speak_text is None:
                return
            from albedo.audio.tts import enqueue_speech, audio_queue
            enqueue_speech(speak_text, voice_model=voice, device=device)
            self._set_state("speaking")

            def _wait() -> None:
                try:
                    audio_queue.join()
                except Exception:
                    pass
                finally:
                    self._ui(lambda: self._set_state("standby"))

            threading.Thread(target=_wait, daemon=True, name="tts-drain").start()

        _type(0)
        self.after(tts_start_ms, _launch_tts)

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
            # Bail out if the root window is destroyed — background threads
            # may still be flushing the queue after the user closed the GUI.
            if self._closing or not self.winfo_exists():
                return
            try:
                while True:
                    fn = self._ui_queue.get_nowait()
                    if self._closing or not self.winfo_exists():
                        return
                    try:
                        fn()
                    except Exception as exc:
                        print(f"[gui] UI callable error: {exc}")
            except queue.Empty:
                pass
            if not self._closing and self.winfo_exists():
                self._poll_after_id = self.after(40, _poll)
        self._poll_after_id = self.after(40, _poll)

    def _ui(self, fn) -> None:
        self._ui_queue.put(fn)

    # ── Text input ─────────────────────────────────────────────────────────

    def _intercept_prompt(self, text: str) -> tuple[str, bool]:
        """
        Front-end prompt rewrite — runs on the main thread before anything
        reaches the swarm.  Returns (rewritten_text, is_direct_search).

        is_direct_search=True means the caller should bypass autonomous_commander()
        and call direct_gemini_search() directly (avoids the ReAct agent loop).
        """
        import os
        lower = text.lower()
        loc   = os.getenv("NODE_LOCATION", "Raymond, Washington")

        # ALL weather queries — canonicalize into an explicit location query so
        # DDG gets a clean search string and Groq never sees filler words or
        # STT mishearings like "and" instead of "in".
        if "weather" in lower:
            import re as _re
            # Resolve proximity phrases to NODE_LOCATION BEFORE stripping, so
            # "near me" / "nearby" don't get reduced to bare "near" after "me" is removed.
            _prox = _re.compile(
                r'\b(near\s+me|near\s+here|near\s+by|nearby|my\s+location|'
                r'my\s+area|my\s+city|my\s+town|where\s+i\s+am|'
                r'locally|around\s+here|around\s+me)\b',
                _re.IGNORECASE,
            )
            text_r = _prox.sub(loc, text)
            # Strip Vosk filler + common mishearings; keep location words
            stripped = _re.sub(
                r'\b(what|whats|is|the|weather|tell|me|give|current|forecast|'
                r'today|please|check|and(?=\s+\w+\s+\w))\b',
                '', text_r, flags=_re.IGNORECASE,
            ).strip()
            # Guard: lone prepositions / proximity words are not valid locations
            _NOT_LOC = {"near", "here", "there", "nearby", "local",
                        "locally", "around", "close", "by", "in"}
            location = (
                stripped
                if len(stripped) > 3 and stripped.lower() not in _NOT_LOC
                else loc
            )
            text = (
                f"What is the current weather in {location}? "
                "Answer in one sentence using Fahrenheit."
            )
            print(f"[UI INTERCEPT] Weather rewrite → {text}")
            return text, True

        # General location trigger — swap vague phrases for concrete location
        import re as _re
        text = _re.sub(
            r'\b(near me|my location|where I am|my area|my city|my town|locally|nearby)\b',
            f'in {loc}', text, flags=_re.IGNORECASE,
        )
        return text, False

    def _handle_send(self) -> None:
        text = self._entry.get().strip()
        if not text or self._state in ("processing", "speaking"):
            return
        text, is_direct = self._intercept_prompt(text)
        self._entry.delete(0, "end")
        use_web = text.lower().startswith("web:")
        query   = text[4:].strip() if use_web else text
        self._log_append("user", query)
        self._abort_flag.clear()
        self._set_state("processing")
        if self._gemini_tbar_lbl is not None:
            self._gemini_tbar_lbl.configure(text="GEMINI: ACTIVE",
                                            text_color=C_CYAN)
            self.update_idletasks()
        threading.Thread(target=self._run_pipeline,
                         args=(query, use_web, is_direct), daemon=True).start()

    def _handle_abort(self) -> None:
        """Set abort flag, kill TTS, log, instantly restore SEND button."""
        self._abort_flag.set()
        try:
            from albedo.audio.tts import stop_audio
            stop_audio()
        except Exception as exc:
            print(f"[gui] abort stop_audio error: {exc}")
        self._log_append("system", "[ABORT] Operation terminated by user.")
        self._set_state("standby")

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

            query, is_direct = self._intercept_prompt(query)
            q = query
            self._ui(lambda: self._log_append("user", q))
            self._ui(lambda: self._set_gemini_active())
            self._run_pipeline(query, use_web=False, is_direct=is_direct)

        except Exception as exc:
            msg = str(exc)
            self._ui(lambda: self._log_append(
                "error", f"Microphone error: {msg}  --  check sounddevice / mic permissions"))
            self._ui(lambda: self._set_state("standby"))

    # ── Swarm Commander routing ────────────────────────────────────────────

    def _route_query(self, query: str, use_web: bool) -> str:
        """
        Route the query through the Gemini Commander when GEMINI_API_KEY is
        set.  The Commander returns a JSON decision:
          'direct'   → Gemini answers directly; skip all local processing.
          'groq'     → forward the refined payload to Groq (fast scripting).
          'together' → forward to Together AI (complex reasoning / debug).
          'memory'   → semantic search against the Obsidian vault index.
          'local'    → existing Ollama + RAG pipeline (default fallback).

        "index vault" / "reindex vault" typed by the user triggers a fresh
        ChromaDB index of the Obsidian vault before routing completes.

        On any import error, API failure, or missing key the method falls
        through silently to the local pipeline so Albedo never goes dark.
        """
        q_lower = query.strip().lower()

        # ── Local machine interceptors — MUST run before autonomous_commander ──
        # Cloud LLMs have zero access to this machine. Route all hardware,
        # file, and OS-control queries to local Python tools first.
        try:
            from albedo.pipeline import (
                _is_identity_query, _IDENTITY_RESPONSE,
                _is_audit_query, _extract_file_ext, _count_files_by_ext,
                _handle_launch, _handle_kill_process, _handle_top_processes,
                _handle_disk_cleanup, _is_oc_query, _run_oc_query, _strip_markdown,
            )

            if _is_identity_query(query):
                return _IDENTITY_RESPONSE

            if _is_audit_query(query):
                try:
                    import sys as _sys, os as _pios
                    _sys.path.insert(0, str(_pios.path.dirname(
                        _pios.path.dirname(_pios.path.abspath(__file__)))))
                    from diagnostics import run_tactical_audit, get_spoken_audit
                    self._tts_override = get_spoken_audit()
                    return _strip_markdown(run_tactical_audit())
                except Exception as exc:
                    self._tts_override = None
                    return f"Audit error: {exc}"

            _launch = _handle_launch(query)
            if _launch is not None:
                return _launch

            _kill = _handle_kill_process(query)
            if _kill is not None:
                return _kill

            _top = _handle_top_processes(query)
            if _top is not None:
                return _top

            _clean = _handle_disk_cleanup(query)
            if _clean is not None:
                return _clean

            _ext = _extract_file_ext(query)
            if _ext:
                return _count_files_by_ext(_ext)

            if _is_oc_query(query):
                return _strip_markdown(_run_oc_query(query))

        except Exception as _local_exc:
            print(f"[gui] Local intercept error: {_local_exc}")

        # ── Vault index intercept ─────────────────────────────────────────────
        if any(q_lower == kw or q_lower.startswith(kw + " ")
               for kw in ("index vault", "reindex vault", "re-index vault")):
            try:
                from memory import index_obsidian_vault
                status = index_obsidian_vault()
                return f"[OBSIDIAN VAULT]\n{status}"
            except Exception as exc:
                return f"[OBSIDIAN VAULT] Indexing failed: {exc}"

        # ── Dream cycle intercept ─────────────────────────────────────────────
        if any(q_lower == kw or q_lower.startswith(kw + " ")
               for kw in ("dream cycle", "rem cycle", "initiate dream", "run dream")):
            try:
                from operative_dream import initiate_rem_cycle
                return initiate_rem_cycle()
            except Exception as exc:
                return f"[dream] REM cycle failed: {exc}"

        from telemetry import log_trace

        _offline_mode = False
        try:
            from swarm import autonomous_commander, query_gemini_stream, query_groq, query_together
            self._ui(lambda: self._set_gemini_active())
            result       = autonomous_commander(query)
            route        = result["route"]
            payload      = result["payload"]
            _offline_mode = result.get("_offline", False)

            if route == "direct":
                log_trace(query, route, success=True)
                if not self._audio_muted and not self._abort_flag.is_set():
                    from albedo.audio.tts import audio_queue, _stop_event
                    _stop_event.clear()
                    _voice = self._get_tts_voice()
                    _dev   = self._settings.get("audio_output_device")
                    def _on_sent(sentence: str) -> None:
                        if not self._abort_flag.is_set():
                            audio_queue.put((sentence, _voice, _dev))
                    self._audio_streamed_for_current_response = True
                    self._ui(lambda: self._set_state("speaking"))
                    result_text = query_gemini_stream(payload, on_sentence=_on_sent)
                    self._ui(lambda: self._set_gemini_standby())
                    return result_text
                result_text = query_gemini_stream(payload)
                self._ui(lambda: self._set_gemini_standby())
                return result_text
            if route == "groq":
                response = "[GROQ EXECUTING]\n" + query_groq(payload)
                log_trace(query, route, success=not response.startswith("[swarm]"))
                self._ui(lambda: self._set_gemini_standby())
                return response
            if route == "together":
                response = "[TOGETHER EVALUATING]\n" + query_together(payload)
                log_trace(query, route, success=not response.startswith("[swarm]"))
                self._ui(lambda: self._set_gemini_standby())
                return response
            if route == "memory":
                try:
                    from memory import search_memory
                    chunks = search_memory(payload)
                    if chunks:
                        body = "\n\n---\n\n".join(chunks)
                        log_trace(query, route, success=True)
                        self._ui(lambda: self._set_gemini_standby())
                        return f"[OBSIDIAN VAULT]\n{body}"
                    log_trace(query, route, success=False)
                    self._ui(lambda: self._set_gemini_standby())
                    return "[OBSIDIAN VAULT] No relevant notes found. Try 'index vault' first."
                except Exception as exc:
                    print(f"[gui] Memory search error: {exc}")
                    log_trace(query, route, success=False)
            # route == "local" — fall through to Ollama below
            self._ui(lambda: self._set_gemini_standby())
        except Exception as exc:
            self._ui(lambda: self._set_gemini_standby())
            print(f"[gui] Commander routing error (falling back to local): {exc}")

        from albedo.pipeline import run as pipeline_run
        history_snapshot = list(self._chat_history)
        try:
            response = pipeline_run(
                query,
                use_web=use_web and not _offline_mode,
                history=history_snapshot,
            )
            log_trace(query, "local", success=bool(response and response.strip()))
            if _offline_mode:
                return f"[SYS - OFFLINE FALLBACK ENGAGED]\n{response}"
            return response
        except Exception as exc:
            log_trace(query, "local", success=False)
            raise

    def _run_direct_search(self, query: str) -> str:
        """
        Bypass autonomous_commander() entirely — call direct_gemini_search()
        and return the plain-text answer.  Ensures GEMINI label updates fire
        correctly on this code path.
        """
        try:
            from swarm import direct_gemini_search
            answer = direct_gemini_search(query)
            if not self._audio_muted and not self._abort_flag.is_set():
                from albedo.audio.tts import audio_queue, _stop_event
                _stop_event.clear()
                _voice = self._get_tts_voice()
                _dev   = self._settings.get("audio_output_device")
                audio_queue.put((answer, _voice, _dev))
                self._audio_streamed_for_current_response = True
                self._ui(lambda: self._set_state("speaking"))
            self._ui(lambda: self._set_gemini_standby())
            return answer
        except Exception as exc:
            self._ui(lambda: self._set_gemini_standby())
            return f"[swarm] Direct search error: {exc}"

    # ── Pipeline runner (always on a background thread) ────────────────────

    def _run_pipeline(self, query: str, use_web: bool, is_direct: bool = False) -> None:
        try:
            if self._abort_flag.is_set():
                return

            self._audio_streamed_for_current_response = False
            self._tts_override = None

            if is_direct:
                response = self._run_direct_search(query)
            else:
                response = self._route_query(query, use_web)

            if self._abort_flag.is_set():
                self._ui(lambda: self._set_state("standby"))
                return

            # Guarantee response is always a non-empty string
            if not isinstance(response, str) or not response.strip():
                response = "[Albedo] No response returned. Is Ollama running?"

            # Update rolling context (trim to last 10 turns = 20 messages)
            self._chat_history.append({"role": "user",      "content": query})
            self._chat_history.append({"role": "assistant", "content": response})
            if len(self._chat_history) > 20:
                self._chat_history = self._chat_history[-20:]

            resp = response
            _speak_text = self._tts_override if self._tts_override else resp
            self._tts_override = None
            _voice = self._get_tts_voice()
            _dev   = self._settings.get("audio_output_device")

            if not self._audio_streamed_for_current_response:
                # Non-streaming path: word-by-word typewriter + coordinated TTS
                _st = _speak_text if not self._audio_muted else None
                self._ui(lambda r=resp, s=_st, v=_voice, d=_dev:
                         self._log_stream_response(r, s, v, d))
            else:
                # Gemini streaming already handled TTS — just show full text
                self._ui(lambda: self._log_append("albedo", resp))
                self._ui(lambda: self._set_state("standby"))

        except Exception as exc:
            msg = str(exc)
            self._ui(lambda: self._log_append("error", msg))
            self._ui(lambda: self._set_state("standby"))

    # ── Vosk pre-warming ────────────────────────────────────────────────

    def _prewarm_vosk(self) -> None:
        """Load (or auto-download) the Vosk model so the first MIC press is instant."""
        try:
            from albedo.audio.stt import is_cached, prewarm
            if is_cached():
                self._ui(lambda: self._log_append(
                    "system", "[SYS] Loading Vosk STT..."))
            else:
                self._ui(lambda: self._log_append(
                    "system",
                    "[SYS] Vosk model not found — auto-downloading (~40 MB). "
                    "Check the LOGS console for progress."))
            prewarm()   # _ensure_model() runs inside here if needed
            self._ui(lambda: self._log_append("system", "[SYS] Vosk online."))
        except Exception as exc:
            msg = str(exc)
            self._ui(lambda: self._log_append(
                "system", f"[SYS] Vosk pre-warm failed: {msg}"))

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

            if not self._audio_muted:
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
        _update_env("WAKE_WORDS",        persona["wake_word"])

        # Hot-swap the Vosk wake word for the current session
        try:
            from albedo.audio import wakeword as _ww
            _ww.set_active_model(persona["wake_word"])
        except Exception as exc:
            print(f"[gui] wake word hot-swap failed (non-fatal): {exc}")

        if key != old_key:
            self._log_append(
                "system",
                f"[SYS] Persona updated: {display_name}. "
                "Voice and Wake Word synchronized.",
            )

    # ── Side panel ─────────────────────────────────────────────────────────

    def _build_side_panel(self, panel: ctk.CTkFrame) -> None:
        """Populate the collapsible right side panel — system controls only."""
        # Header bar
        hdr = ctk.CTkFrame(panel, fg_color=C_BG, corner_radius=0, height=46)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="// SYS_PANEL",
                     font=("Courier New", 13, "bold"),
                     text_color=C_CYAN).pack(expand=True, pady=10)

        ctk.CTkFrame(panel, fg_color=C_BORDER, height=1).pack(fill="x")

        # Spacer so buttons sit centred vertically
        ctk.CTkFrame(panel, fg_color="transparent").pack(expand=True)

        # System action buttons
        btn_f = ctk.CTkFrame(panel, fg_color="transparent")
        btn_f.pack(fill="x", padx=12, pady=0)

        _BTN_FONT = ("Courier New", 15, "bold")
        _BTN_H    = 52

        ctk.CTkButton(btn_f, text="LOGS", height=_BTN_H,
                      font=_BTN_FONT,
                      fg_color=C_BORDER, hover_color=C_CYAN_DIM,
                      text_color=C_CYAN,
                      command=self._open_console).pack(fill="x", pady=(0, 6))

        ctk.CTkButton(btn_f, text="SETTINGS", height=_BTN_H,
                      font=_BTN_FONT,
                      fg_color=C_BORDER, hover_color=C_CYAN,
                      command=self._open_settings).pack(fill="x", pady=(0, 6))

        ctk.CTkButton(btn_f, text="HARDWARE", height=_BTN_H,
                      font=_BTN_FONT,
                      fg_color=C_BORDER, hover_color=C_CYAN,
                      command=self._open_hardware_settings).pack(fill="x", pady=(0, 6))

        # Bottom spacer
        ctk.CTkFrame(panel, fg_color="transparent").pack(expand=True)

    def _toggle_side_panel(self) -> None:
        if self._panel_visible:
            self._side_panel.grid_remove()
            self._panel_visible = False
            self._toggle_arrow_lbl.configure(text="◄")
        else:
            self._side_panel.grid()
            self._panel_visible = True
            self._toggle_arrow_lbl.configure(text="►")

    # ── Update check & apply ───────────────────────────────────────────────

    _AU_INTERVALS: dict[str, int] = {
        "On startup only": 0,
        "Every 1 hour":    3_600_000,
        "Every 6 hours":  21_600_000,
        "Every 24 hours": 86_400_000,
        "Disabled":        0,
    }

    def _reschedule_update_check(self) -> None:
        """Cancel any pending check and set up the next one per current settings."""
        # Cancel previous scheduled call if any
        if self._update_check_after_id:
            try:
                self.after_cancel(self._update_check_after_id)
            except Exception:
                pass
            self._update_check_after_id = None

        setting = self._settings.get("auto_update", "On startup only")
        if setting == "Disabled":
            return

        # Guard: for "On startup only" run exactly once across all callers
        if setting == "On startup only" and self._update_check_ran:
            return
        self._update_check_ran = True

        # Run the check now (silent)
        self._check_for_updates(_manual=False)

        # Schedule the next recurring check if an interval is set
        interval_ms = self._AU_INTERVALS.get(setting, 0)
        if interval_ms > 0:
            self._update_check_after_id = self.after(
                interval_ms, self._reschedule_update_check)

    def _check_for_updates(self, _manual: bool = False) -> None:
        """Run git fetch in background; alert user if commits are available."""
        def _worker():
            import subprocess as _sp

            def _run(cmd):
                return _sp.run(
                    cmd, capture_output=False,
                    stdout=_sp.PIPE, stderr=_sp.STDOUT,
                    text=True, timeout=20,
                    cwd=str(ROOT), creationflags=_sp.CREATE_NO_WINDOW,
                )

            try:
                # Verify we are inside a git repo
                check = _run(["git", "rev-parse", "--is-inside-work-tree"])
                if check.returncode != 0:
                    print("[update] Not a git repository — opening releases page.")
                    import webbrowser
                    webbrowser.open(
                        "https://github.com/Dracon420/The-Albedo-AI-Project/releases/latest")
                    self._ui(lambda: self._reset_update_btn("UPDATE"))
                    return

                # Get current HEAD and compare to what was on disk at launch
                current_head = _run(["git", "rev-parse", "HEAD"]).stdout.strip()
                print(f"[update] Launch commit: {self._startup_commit[:7] if self._startup_commit else '?'}")
                print(f"[update] Current HEAD:  {current_head[:7] if current_head else '?'}")

                if self._startup_commit and current_head and current_head != self._startup_commit:
                    # Code was committed (and possibly pushed) from this machine since launch —
                    # the running process has stale bytecode; offer a restart.
                    local = _run(["git", "log", "-1", "--oneline"])
                    print(f"[update] Disk code changed since launch → {local.stdout.strip()}")
                    print("[update] Restart required to apply new code.")
                    self._update_available = True
                    self._ui(self._notify_update_available)
                    return

                # Show current local commit
                local = _run(["git", "log", "-1", "--oneline"])
                print(f"[update] Local:  {local.stdout.strip()}")

                # Fetch from remote
                print("[update] Fetching from remote...")
                fetch = _run(["git", "fetch"])
                if fetch.stdout.strip():
                    print(f"[update] fetch: {fetch.stdout.strip()}")
                if fetch.returncode != 0:
                    print(f"[update] Fetch failed (returncode {fetch.returncode}).")
                    if _manual:
                        self._ui(lambda: self._reset_update_btn("FETCH FAILED"))
                    return

                # Determine remote branch (origin/HEAD or origin/<branch>)
                branch = _run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
                remote_ref = branch.stdout.strip() if branch.returncode == 0 else "origin/master"
                print(f"[update] Tracking: {remote_ref}")

                # Count new commits on remote
                log = _run(["git", "log", f"HEAD..{remote_ref}", "--oneline"])
                new_commits = log.stdout.strip()

                if new_commits:
                    count = len(new_commits.splitlines())
                    print(f"[update] {count} new commit(s) available:\n{new_commits}")
                    self._update_available = True
                    self._ui(self._notify_update_available)
                else:
                    remote_log = _run(["git", "log", "-1", "--oneline", remote_ref])
                    print(f"[update] Remote: {remote_log.stdout.strip()}")
                    print("[update] Already up to date.")
                    if _manual:
                        self._ui(lambda: self._reset_update_btn("UP TO DATE"))

            except FileNotFoundError:
                print("[update] git not found on PATH.")
                if _manual:
                    self._ui(lambda: self._reset_update_btn("GIT NOT FOUND"))
            except Exception as exc:
                print(f"[update] check error: {exc}")
                if _manual:
                    self._ui(lambda: self._reset_update_btn("CHECK FAILED"))

        threading.Thread(target=_worker, daemon=True, name="update-check").start()

    def _reset_update_btn(self, label: str = "UPDATE") -> None:
        btn = self._update_btn
        if not btn:
            return
        try:
            if not btn.winfo_exists():
                self._update_btn = None
                return
        except Exception:
            self._update_btn = None
            return
        btn.configure(text=label, fg_color=C_BORDER,
                      hover_color=C_GREEN, text_color=C_TEXT)
        if label not in ("UPDATE", "CHECKING..."):
            self.after(4000, lambda: self._reset_update_btn("UPDATE"))

    def _notify_update_available(self) -> None:
        """Flash the update button and log an alert in the chat feed."""
        btn = self._update_btn
        if btn:
            try:
                if btn.winfo_exists():
                    btn.configure(text="UPDATE AVAILABLE", fg_color="#005500",
                                  hover_color=C_GREEN, text_color=C_GREEN)
            except Exception:
                pass
        self._log_append(
            "system",
            "UPDATE AVAILABLE — Open Settings and click UPDATE to install and restart.")

    def _apply_background(self, name: str) -> None:
        """Load the selected background image and force a canvas redraw."""
        fname = _BG_FILES.get(name)
        if fname is None:
            self._bg_pil = None
        else:
            path = ROOT / fname
            if path.exists():
                try:
                    self._bg_pil = Image.open(path).convert('RGB')
                except Exception as exc:
                    print(f'[bg] failed to load {fname}: {exc}')
                    self._bg_pil = None
            else:
                print(f'[bg] file not found: {fname}')
                self._bg_pil = None
        self._bg_photo = None
        if hasattr(self, '_draw_bg'):
            self._bg_canvas.delete('bg_img')
            self._draw_bg(force=True)

    def _restart_app(self) -> None:
        """Spawn a fresh Albedo process then close this one."""
        import subprocess as _sp
        print("[restart] Launching new Albedo process...")
        _sp.Popen(
            [sys.executable, str(ROOT / "gui.py")],
            creationflags=_sp.CREATE_NO_WINDOW,
        )
        self._ui(self.destroy)

    def _run_update(self) -> None:
        """Single-click: check → pull (if needed) → restart. No two-step."""
        import subprocess as _sp

        self._ui(lambda: self._reset_update_btn("CHECKING..."))

        def _worker():
            def _run(cmd):
                return _sp.run(
                    cmd, stdout=_sp.PIPE, stderr=_sp.STDOUT,
                    text=True, timeout=30,
                    cwd=str(ROOT), creationflags=_sp.CREATE_NO_WINDOW,
                )

            try:
                # Disk-change detection (same-machine push workflow)
                current_head = _run(["git", "rev-parse", "HEAD"]).stdout.strip()
                if (self._startup_commit and current_head
                        and current_head != self._startup_commit):
                    print(f"[update] Code changed on disk since launch "
                          f"({self._startup_commit[:7]} → {current_head[:7]}) — restarting.")
                    self._restart_app()
                    return

                # Fetch + check remote
                check = _run(["git", "rev-parse", "--is-inside-work-tree"])
                if check.returncode != 0:
                    print("[update] Not a git repository — opening releases page.")
                    import webbrowser
                    webbrowser.open(
                        "https://github.com/Dracon420/The-Albedo-AI-Project/releases/latest")
                    self._ui(lambda: self._reset_update_btn("UPDATE"))
                    return

                print("[update] Fetching from remote...")
                fetch = _run(["git", "fetch"])
                if fetch.returncode != 0:
                    print(f"[update] Fetch failed.\n{fetch.stdout.strip()}")
                    self._ui(lambda: self._reset_update_btn("FETCH FAILED"))
                    return

                branch = _run(["git", "rev-parse", "--abbrev-ref",
                                "--symbolic-full-name", "@{u}"])
                remote_ref = (branch.stdout.strip()
                              if branch.returncode == 0 else "origin/master")

                new_commits = _run(
                    ["git", "log", f"HEAD..{remote_ref}", "--oneline"]
                ).stdout.strip()

                if not new_commits:
                    print("[update] Already up to date.")
                    self._ui(lambda: self._reset_update_btn("UP TO DATE"))
                    return

                # Updates available — pull immediately
                count = len(new_commits.splitlines())
                print(f"[update] {count} new commit(s) — pulling...")
                pull = _run(["git", "pull", "--ff-only"])
                print(f"[update] {pull.stdout.strip()}")
                if pull.returncode != 0:
                    print("[update] Pull failed — cannot fast-forward.")
                    self._ui(lambda: self._reset_update_btn("PULL FAILED"))
                    return

                self._restart_app()

            except FileNotFoundError:
                print("[update] git not found on PATH.")
                self._ui(lambda: self._reset_update_btn("GIT NOT FOUND"))
            except Exception as exc:
                print(f"[update] error: {exc}")
                self._ui(lambda: self._reset_update_btn("UPDATE FAILED"))

        threading.Thread(target=_worker, daemon=True, name="update-run").start()

    # ── Developer console ──────────────────────────────────────────────────

    def _console_write(self, text: str) -> None:
        """Buffer console output and forward to the floating ConsoleDialog if open."""
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

    def _toggle_audio_mute(self) -> None:
        """Toggle TTS mute. Kills edge-tts producer + sounddevice playback instantly."""
        self._audio_muted = not self._audio_muted
        if self._audio_muted:
            try:
                from albedo.audio.tts import stop_audio
                stop_audio()
            except Exception:
                pass
            self._audio_btn.configure(
                text="AUDIO: MUTE",
                fg_color=C_DANGER,
                hover_color="#CC2040",
                text_color="#FFFFFF",
            )
            self._log_append("system", "[SYS] Audio output muted.")
        else:
            self._audio_btn.configure(
                text="AUDIO: ON",
                fg_color=C_GREEN,
                hover_color="#22CC00",
                text_color="#000000",
            )
            self._log_append("system", "[SYS] Audio output restored.")

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
        # Mark closing so threaded UI callables and the queue poll bail out.
        self._closing = True

        # Cancel any tracked after() callbacks before destroying widgets.
        if self._poll_after_id is not None:
            try:
                self.after_cancel(self._poll_after_id)
            except Exception:
                pass
            self._poll_after_id = None

        sys.stdout = self._stdout_orig
        sys.stderr = self._stderr_orig

        # Stop TTS playback first so the audio thread isn't holding the device.
        try:
            from albedo.audio.tts import stop_audio
            stop_audio()
        except Exception:
            pass

        if self._audio_stream:
            try:
                self._audio_stream.stop()
            except Exception:
                pass

        try:
            self.quit()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass


# ── Entry point ────────────────────────────────────────────────────────────

def main() -> None:
    app = AlbedoGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
