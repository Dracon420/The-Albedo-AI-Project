"""
setup_utility.py  --  Albedo First-Run Setup Wizard

Stdlib-only: runs with any Python 3.8+ before the venv is created.
No third-party imports at all. Uses only tkinter, tkinter.ttk,
tkinter.scrolledtext, and tkinter.filedialog.

Pages:
  1  System Check  -- Python 3.12, Ollama, Git
  2  Directories   -- RAG knowledge-base folders, Piper, wake word
  3  Installing    -- live pip output + progress bar
  4  Complete      -- launch shortcut / exit

Errno 13 fix: all pip commands use --no-cache-dir so no wheel file
in the pip cache directory is ever held open when another process
has already locked it.
"""
from __future__ import annotations

import json as _json
import os
import queue
import shutil
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, scrolledtext, ttk

# ---------------------------------------------------------------------------
# Colors / fonts
# ---------------------------------------------------------------------------

C_BG     = "#0A0F2C"
C_PANEL  = "#0E1330"
C_CYAN   = "#00F5FF"
C_DIM    = "#0099BB"
C_BORDER = "#1A2050"
C_TEXT   = "#C8D4E8"
C_MUTED  = "#3A4570"
C_GREEN  = "#00CC66"
C_WARN   = "#FFAA00"
C_DANGER = "#FF3A5C"
C_BTN    = "#1A3060"

FONT_MONO   = ("Courier New", 11)
FONT_BOLD   = ("Courier New", 11, "bold")
FONT_TITLE  = ("Courier New", 14, "bold")
FONT_HEADER = ("Courier New", 17, "bold")
FONT_SMALL  = ("Courier New", 10)

ROOT     = Path(__file__).parent
VENV     = ROOT / ".venv"
VENV_PY  = VENV / "Scripts" / "python.exe"
VENV_PIP = VENV / "Scripts" / "pip.exe"


# ---------------------------------------------------------------------------
# Backend helpers
# ---------------------------------------------------------------------------

def _run(cmd: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30, **kw)


def _find_python312() -> str | None:
    try:
        r = _run(["py", "-3.12", "-c", "import sys; print(sys.executable)"])
        if r.returncode == 0:
            return r.stdout.strip()
    except FileNotFoundError:
        pass
    for name in ("python3.12", "python"):
        exe = shutil.which(name)
        if exe:
            try:
                r = _run([exe, "-c",
                          "import sys; v=sys.version_info; "
                          "print(sys.executable if (v.major,v.minor)==(3,12) else '')"])
                if r.returncode == 0 and r.stdout.strip():
                    return r.stdout.strip()
            except Exception:
                pass
    return None


def _check_ollama() -> bool:
    try:
        return _run(["ollama", "--version"]).returncode == 0
    except FileNotFoundError:
        return False


def _check_git() -> bool:
    try:
        return _run(["git", "--version"]).returncode == 0
    except FileNotFoundError:
        return False


def _kill_locked_processes() -> None:
    for name in ("pythonw.exe",):
        try:
            subprocess.run(["taskkill", "/F", "/IM", name],
                           capture_output=True, timeout=5)
        except Exception:
            pass


_HF_BASE = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US"
)
_VOICE_FILES = [
    ("kristin/medium/en_US-kristin-medium.onnx",      "en_US-kristin-medium.onnx"),
    ("kristin/medium/en_US-kristin-medium.onnx.json", "en_US-kristin-medium.onnx.json"),
    ("ryan/medium/en_US-ryan-medium.onnx",             "en_US-ryan-medium.onnx"),
    ("ryan/medium/en_US-ryan-medium.onnx.json",        "en_US-ryan-medium.onnx.json"),
]


def _download_voice_models() -> list[str]:
    """Download both persona voice models from HuggingFace into ROOT/voices/.
    Returns a list of human-readable messages for any files that failed."""
    voices_dir = ROOT / "voices"
    voices_dir.mkdir(exist_ok=True)
    failed: list[str] = []
    for rel, filename in _VOICE_FILES:
        dest = voices_dir / filename
        if dest.exists():
            continue
        url = f"{_HF_BASE}/{rel}"
        try:
            urllib.request.urlretrieve(url, dest)
        except Exception as exc:
            failed.append(f"{filename}: {exc}")
            if dest.exists():
                try:
                    dest.unlink()
                except OSError:
                    pass
    return failed


def _write_env(chaotic: str, exotic: str, piper_bin: str, persona: str) -> None:
    env_path   = ROOT / ".env"
    example    = ROOT / ".env.example"
    voices_dir = ROOT / "voices"
    ww_dir     = ROOT / "wakeword_models"

    cortana_voice = str(voices_dir / "en_US-kristin-medium.onnx")
    jarvis_voice  = str(voices_dir / "en_US-ryan-medium.onnx")

    if persona == "jarvis":
        active_voice    = jarvis_voice
        active_wakeword = "hey_jarvis"
    else:
        active_voice    = cortana_voice
        cortana_onnx    = ww_dir / "hey_core_tah_nuh.onnx"
        active_wakeword = str(cortana_onnx) if cortana_onnx.exists() else "hey_jarvis"

    lines = (example.read_text(encoding="utf-8").splitlines()
             if example.exists() else [])
    overrides = {
        "CHAOTIC_3D_PATH":      chaotic,
        "EXOTIC_OS_PATH":       exotic,
        "PIPER_BINARY":         piper_bin,
        "PIPER_VOICE_MODEL":    active_voice,
        "PIPER_VOICE_CORTANA":  cortana_voice,
        "PIPER_VOICE_JARVIS":   jarvis_voice,
        "WAKEWORD_MODEL":       active_wakeword,
        "OLLAMA_MODEL":         "llama3.2:3b",
        "WHISPER_MODEL_SIZE":   "small",
        "WHISPER_DEVICE":       "cuda",
        "WHISPER_COMPUTE_TYPE": "int8_float16",
    }
    result: list[str] = [
        f"# Generated by setup_utility.py -- {datetime.now():%Y-%m-%d %H:%M}", ""]
    written: set[str] = set()
    for line in lines:
        k = line.split("=")[0].strip().lstrip("#").strip()
        if k in overrides:
            result.append(f'{k}="{overrides[k]}"')
            written.add(k)
        else:
            result.append(line)
    for k, v in overrides.items():
        if k not in written:
            result.append(f'{k}="{v}"')
    env_path.write_text("\n".join(result) + "\n", encoding="utf-8")


def _create_shortcut(install_root: Path) -> None:
    launcher = install_root / "Launch-Albedo.ps1"
    desktop  = Path(os.path.expandvars("%USERPROFILE%")) / "Desktop"
    lnk_path = desktop / "Albedo Mission Control.lnk"
    ico_path = install_root / "albedo_icon.ico"

    if lnk_path.exists():
        lnk_path.unlink()

    try:
        import win32com.client  # type: ignore
        shell    = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(str(lnk_path))
        shortcut.TargetPath       = "powershell.exe"
        shortcut.Arguments        = (f'-ExecutionPolicy Bypass -WindowStyle Normal '
                                     f'-File "{launcher}"')
        shortcut.WorkingDirectory = str(install_root)
        shortcut.Description      = "Launch Albedo -- Spartan-Class Local AI"
        shortcut.IconLocation     = (f"{ico_path},0" if ico_path.exists()
                                     else "powershell.exe,0")
        shortcut.Save()
    except Exception:
        try:
            ps = (
                f'$ws=New-Object -ComObject WScript.Shell; '
                f'$lnk=$ws.CreateShortcut("{lnk_path}"); '
                f'$lnk.TargetPath="powershell.exe"; '
                f'$lnk.Arguments='
                f'"-ExecutionPolicy Bypass -WindowStyle Normal -File `"{launcher}`""; '
                f'$lnk.WorkingDirectory="{install_root}"; '
                f'$lnk.IconLocation="{ico_path},0"; '
                f'$lnk.Save()'
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=15)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Widget factory helpers
# ---------------------------------------------------------------------------

def _lbl(parent: tk.Widget, text: str, size: int = 11, color: str = C_TEXT,
         bold: bool = False, bg: str = C_BG, **kw) -> tk.Label:
    weight = "bold" if bold else "normal"
    return tk.Label(parent, text=text, fg=color, bg=bg,
                    font=("Courier New", size, weight), **kw)


def _btn(parent: tk.Widget, text: str, command,
         bg: str = C_BTN, fg: str = C_TEXT,
         width: int | None = None, **kw) -> tk.Button:
    b = tk.Button(parent, text=text, command=command,
                  bg=bg, fg=fg,
                  activebackground=C_DIM, activeforeground=C_TEXT,
                  relief="flat", cursor="hand2", font=FONT_BOLD,
                  padx=10, pady=5, **kw)
    if width is not None:
        b.configure(width=width)
    return b


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

class Page(tk.Frame):
    def __init__(self, parent: tk.Widget, wizard: "SetupWizard") -> None:
        super().__init__(parent, bg=C_BG)
        self.wizard = wizard

    def on_enter(self) -> None:
        pass


# ── Page 1: System Check ────────────────────────────────────────────────────

class SystemCheckPage(Page):
    def __init__(self, parent: tk.Widget, wizard: "SetupWizard") -> None:
        super().__init__(parent, wizard)
        self._results: dict[str, bool | None] = {
            "Python 3.12": None, "Ollama": None, "Git": None,
        }
        self._labels: dict[str, tk.Label] = {}
        self._build()

    def _build(self) -> None:
        _lbl(self, "STEP 1  --  SYSTEM CHECK",
             size=14, bold=True, color=C_CYAN).pack(pady=(24, 4))
        _lbl(self, "Verifying required dependencies before installation.",
             color=C_MUTED).pack(pady=(0, 16))

        box = tk.Frame(self, bg=C_PANEL, bd=0)
        box.pack(fill="x", padx=24, pady=8)

        for name in self._results:
            row = tk.Frame(box, bg=C_PANEL)
            row.pack(fill="x", padx=16, pady=6)
            _lbl(row, f"  {name}", bg=C_PANEL).pack(side="left")
            lbl = _lbl(row, "CHECKING...", color=C_MUTED, bg=C_PANEL)
            lbl.pack(side="right", padx=8)
            self._labels[name] = lbl

        self._fix_btn = _btn(self, "FIX MISSING DEPENDENCIES",
                             self._fix, bg=C_WARN, fg="#000000", width=28)
        self._fix_btn.pack(pady=12)
        self._fix_btn.configure(state="disabled")

        self._note = _lbl(self, "", color=C_MUTED, size=10)
        self._note.pack(pady=4)

    def on_enter(self) -> None:
        for name, lbl in self._labels.items():
            lbl.configure(text="CHECKING...", fg=C_MUTED)
        self.wizard.set_next_enabled(False)
        threading.Thread(target=self._run_checks, daemon=True).start()

    def _run_checks(self) -> None:
        checks = {
            "Python 3.12": _find_python312() is not None,
            "Ollama":       _check_ollama(),
            "Git":          _check_git(),
        }
        for name, ok in checks.items():
            self._results[name] = ok
            color = C_GREEN if ok else C_DANGER
            text  = "OK" if ok else "MISSING"
            self.after(0, lambda lbl=self._labels[name], t=text, c=color:
                       lbl.configure(text=t, fg=c))

        all_ok = all(checks.values())
        self.after(0, lambda: self._fix_btn.configure(
            state="disabled" if all_ok else "normal"))
        self.after(0, lambda: self.wizard.set_next_enabled(all_ok))
        if all_ok:
            self.after(0, lambda: self._note.configure(
                text="All dependencies found. Click NEXT to continue.",
                fg=C_GREEN))
        else:
            self.after(0, lambda: self._note.configure(
                text="Click FIX to auto-install missing tools, or install manually.",
                fg=C_WARN))

    def _fix(self) -> None:
        self._fix_btn.configure(state="disabled", text="Installing...")
        self._note.configure(text="Installing missing tools via winget...", fg=C_WARN)

        def _run() -> None:
            if not self._results.get("Ollama"):
                try:
                    subprocess.run(
                        ["winget", "install", "Ollama.Ollama",
                         "--accept-source-agreements",
                         "--accept-package-agreements", "--silent"],
                        timeout=120)
                except Exception:
                    pass
            if not self._results.get("Python 3.12"):
                try:
                    subprocess.run(
                        ["winget", "install", "Python.Python.3.12",
                         "--accept-source-agreements",
                         "--accept-package-agreements", "--silent"],
                        timeout=180)
                except Exception:
                    pass
            self.after(0, self.on_enter)
            self.after(0, lambda: self._fix_btn.configure(
                text="FIX MISSING DEPENDENCIES"))

        threading.Thread(target=_run, daemon=True).start()


# ── Page 2: Directory Selection ─────────────────────────────────────────────

class DirectoryPage(Page):
    _PERSONAS = ["Cortana", "Jarvis"]

    def __init__(self, parent: tk.Widget, wizard: "SetupWizard") -> None:
        super().__init__(parent, wizard)
        self._3d_var      = tk.StringVar(value="")
        self._os_var      = tk.StringVar(value="")
        self._piper_var   = tk.StringVar(value=r"C:\piper\piper.exe")
        self._persona_var = tk.StringVar(value="Cortana")
        self._build()

    def _build(self) -> None:
        _lbl(self, "STEP 2  --  DIRECTORY SELECTION",
             size=14, bold=True, color=C_CYAN).pack(pady=(24, 4))
        _lbl(self, "Choose your knowledge-base source folders.",
             color=C_MUTED).pack(pady=(0, 12))

        box = tk.Frame(self, bg=C_PANEL, bd=0)
        box.pack(fill="x", padx=24, pady=4)

        self._dir_row(box, "Chaotic 3D Folder  (STL / gcode / slicer)",
                      self._3d_var, is_dir=True)
        self._dir_row(box, "Exotic OS Folder   (Python / logs / reptile records)",
                      self._os_var, is_dir=True)

        tk.Frame(box, height=1, bg=C_BORDER).pack(fill="x", padx=16, pady=8)

        self._path_row(box, "Piper binary path", self._piper_var)

        # Persona dropdown -- drives both TTS voice and wake word model
        prow = tk.Frame(box, bg=C_PANEL)
        prow.pack(fill="x", padx=16, pady=4)
        _lbl(prow, "Initial persona  (sets voice model + wake word)",
             size=10, bg=C_PANEL).pack(anchor="w")
        opt = tk.OptionMenu(prow, self._persona_var, *self._PERSONAS)
        opt.configure(bg=C_BTN, fg=C_TEXT, activebackground=C_DIM,
                      activeforeground=C_TEXT, relief="flat",
                      font=FONT_SMALL, highlightthickness=0)
        opt["menu"].configure(bg=C_BTN, fg=C_TEXT, font=FONT_SMALL)
        opt.pack(fill="x", pady=(4, 0))
        _lbl(prow,
             "Voice models are auto-downloaded during installation.",
             size=9, color=C_MUTED, bg=C_PANEL).pack(anchor="w", pady=(2, 0))

        _lbl(self,
             "Leave 3D / OS folders blank to configure later via SETTINGS.",
             color=C_MUTED, size=10).pack(pady=(8, 0))

    def _dir_row(self, parent: tk.Widget, label: str,
                 var: tk.StringVar, is_dir: bool = False) -> None:
        row = tk.Frame(parent, bg=C_PANEL)
        row.pack(fill="x", padx=16, pady=4)
        _lbl(row, label, size=10, bg=C_PANEL).pack(anchor="w")
        inner = tk.Frame(row, bg=C_PANEL)
        inner.pack(fill="x")
        tk.Entry(inner, textvariable=var, bg=C_BG, fg=C_TEXT,
                 insertbackground=C_CYAN, relief="flat", bd=2,
                 font=FONT_SMALL).pack(side="left", fill="x",
                                       expand=True, padx=(0, 4))
        if is_dir:
            cmd = lambda v=var: v.set(filedialog.askdirectory() or v.get())
        else:
            cmd = lambda v=var: v.set(filedialog.askopenfilename() or v.get())
        _btn(inner, "BROWSE", cmd, width=8).pack(side="left")

    def _path_row(self, parent: tk.Widget, label: str,
                  var: tk.StringVar) -> None:
        row = tk.Frame(parent, bg=C_PANEL)
        row.pack(fill="x", padx=16, pady=4)
        _lbl(row, label, size=10, bg=C_PANEL).pack(anchor="w")
        tk.Entry(row, textvariable=var, bg=C_BG, fg=C_TEXT,
                 insertbackground=C_CYAN, relief="flat", bd=2,
                 font=FONT_SMALL).pack(fill="x")

    def get_values(self) -> dict[str, str]:
        return {
            "chaotic":   self._3d_var.get().strip(),
            "exotic":    self._os_var.get().strip(),
            "piper_bin": self._piper_var.get().strip(),
            "persona":   self._persona_var.get().strip().lower(),  # "cortana" / "jarvis"
        }


# ── Page 3: Installing ───────────────────────────────────────────────────────

class InstallPage(Page):
    def __init__(self, parent: tk.Widget, wizard: "SetupWizard") -> None:
        super().__init__(parent, wizard)
        self._q: queue.Queue = queue.Queue()
        self._polling = False
        self._build()

    def _build(self) -> None:
        _lbl(self, "STEP 3  --  INSTALLING",
             size=14, bold=True, color=C_CYAN).pack(pady=(24, 4))

        self._status = _lbl(self, "Ready.", color=C_MUTED)
        self._status.pack(pady=(0, 8))

        self._bar = ttk.Progressbar(self,
                                    style="Albedo.Horizontal.TProgressbar",
                                    mode="determinate", maximum=100)
        self._bar.pack(fill="x", padx=24, pady=(0, 12))

        log_frame = tk.Frame(self, bg=C_PANEL, bd=0)
        log_frame.pack(fill="both", expand=True, padx=24, pady=(0, 12))

        self._log = scrolledtext.ScrolledText(
            log_frame, bg=C_PANEL, fg=C_TEXT,
            font=FONT_SMALL, relief="flat", state="disabled",
            wrap="word", insertbackground=C_CYAN)
        self._log.pack(fill="both", expand=True, padx=4, pady=4)
        self._log.tag_config("ok",   foreground=C_GREEN)
        self._log.tag_config("err",  foreground=C_DANGER)
        self._log.tag_config("info", foreground=C_TEXT)

    def on_enter(self) -> None:
        dirs = self.wizard.dir_page.get_values()
        self.wizard.set_next_enabled(False)
        self._bar["value"] = 0
        if not self._polling:
            self._polling = True
            self.after(50, self._poll)
        threading.Thread(target=self._install, args=(dirs,), daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                msg, tag, pct = self._q.get_nowait()
                self._append(msg, tag)
                if pct is not None:
                    self._bar["value"] = pct * 100
                    if msg.strip():
                        self._status.configure(text=msg[:60])
        except queue.Empty:
            pass
        self.after(50, self._poll)

    def _push(self, msg: str, tag: str = "info",
              pct: float | None = None) -> None:
        self._q.put((msg, tag, pct))

    def _append(self, text: str, tag: str = "info") -> None:
        self._log.configure(state="normal")
        self._log.insert("end", text.rstrip() + "\n", tag)
        self._log.configure(state="disabled")
        self._log.see("end")

    # ── Installation steps ────────────────────────────────────────────────

    def _install(self, dirs: dict[str, str]) -> None:
        try:
            self._step_kill_locked()
            self._step_venv()
            self._step_build_tools()
            self._step_requirements()
            self._step_playwright()
            self._step_wakeword_models()
            self._step_download_voices()
            self._step_env(dirs)
            self._step_shortcut()
            self._step_ollama()
            self._push("", "info", 1.0)
            self._push("Installation complete!", "ok")
            self.after(0, lambda: self.wizard.go_to_complete(success=True))
        except Exception as exc:
            self._push(f"FATAL: {exc}", "err")
            self.after(0, lambda: self.wizard.go_to_complete(success=False))

    def _step_kill_locked(self) -> None:
        self._push("Closing any running Albedo windows...", "info", 0.02)
        _kill_locked_processes()

    def _step_venv(self) -> None:
        self._push("Locating Python 3.12...", "info", 0.05)
        py = _find_python312()
        if py is None:
            raise RuntimeError(
                "Python 3.12 not found. Install it via winget or python.org "
                "then re-run this wizard.")
        self._push(f"  Found: {py}", "ok")
        if VENV.exists():
            self._push("  Existing .venv detected -- reusing.", "info", 0.08)
        else:
            self._push("Creating virtual environment...", "info", 0.10)
            r = subprocess.run([py, "-m", "venv", str(VENV)],
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            if r.returncode != 0:
                raise RuntimeError(f"venv creation failed:\n{r.stderr}")
            self._push("  .venv created.", "ok")

    def _step_build_tools(self) -> None:
        self._push("Upgrading pip / wheel / setuptools...", "info", 0.15)
        # Use 'python -m pip' instead of pip.exe to avoid the
        # "To modify pip" warning when installed under Program Files.
        self._stream_pip([str(VENV_PY), "-m", "pip", "install", "--upgrade",
                          "pip", "wheel", "setuptools",
                          "--no-cache-dir", "--quiet"])
        self._push("  Build tools up to date.", "ok")

    def _step_requirements(self) -> None:
        self._push("Installing Python dependencies...", "info", 0.20)
        self._push("  (this takes 3-10 minutes on first run)", "info")
        req = ROOT / "requirements.txt"
        self._stream_pip([str(VENV_PY), "-m", "pip", "install",
                          "-r", str(req), "--prefer-binary", "--no-cache-dir"],
                         end_pct=0.75)
        self._push("  Dependencies installed.", "ok", 0.75)

    def _step_playwright(self) -> None:
        self._push("Installing Playwright browser...", "info", 0.77)
        try:
            r = subprocess.run(
                [str(VENV_PY), "-m", "playwright", "install", "chromium"],
                capture_output=True, text=True, timeout=120,
                encoding="utf-8", errors="replace")
            if r.returncode == 0:
                self._push("  Playwright Chromium ready.", "ok")
            else:
                self._push("  Playwright install skipped (non-fatal).", "info")
        except Exception:
            self._push("  Playwright not installed (non-fatal).", "info")

    def _step_download_voices(self) -> None:
        self._push("Downloading Piper voice models (Cortana + Jarvis)...", "info", 0.82)
        self._push("  Fetching en_US-kristin-medium and en_US-ryan-medium from HuggingFace...",
                   "info")
        failed = _download_voice_models()
        if failed:
            for msg in failed:
                self._push(f"  Skipped (non-fatal): {msg}", "info")
            self._push("  Download voices manually: huggingface.co/rhasspy/piper-voices",
                       "info")
        else:
            self._push("  Voice models ready.", "ok", 0.83)

    def _step_wakeword_models(self) -> None:
        self._push("Pre-downloading OpenWakeWord base models...", "info", 0.80)
        try:
            r = subprocess.run(
                [str(VENV_PY), "-c",
                 "import openwakeword; openwakeword.utils.download_models()"],
                capture_output=True, text=True, timeout=120,
                encoding="utf-8", errors="replace")
            if r.returncode == 0:
                self._push("  Wake word models ready.", "ok")
            else:
                self._push("  Wake word pre-download skipped (non-fatal).", "info")
        except Exception:
            self._push("  OpenWakeWord models skipped (non-fatal).", "info")

    def _step_env(self, dirs: dict[str, str]) -> None:
        self._push("Writing .env configuration...", "info", 0.84)
        persona = dirs.get("persona", "cortana")
        _write_env(
            chaotic=dirs["chaotic"],
            exotic=dirs["exotic"],
            piper_bin=dirs["piper_bin"],
            persona=persona,
        )
        # Write initial settings.json so the GUI knows the active persona
        settings_path = ROOT / "settings.json"
        try:
            existing: dict = {}
            if settings_path.exists():
                try:
                    existing = _json.loads(settings_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            existing["active_persona"] = persona
            settings_path.write_text(_json.dumps(existing, indent=2), encoding="utf-8")
        except Exception as exc:
            self._push(f"  settings.json write skipped (non-fatal): {exc}", "info")
        self._push("  .env written.", "ok")

    def _step_shortcut(self) -> None:
        self._push("Creating desktop shortcut...", "info", 0.87)
        _create_shortcut(ROOT)
        self._push("  Albedo shortcut created on Desktop.", "ok")

    def _step_ollama(self) -> None:
        self._push("Pulling Ollama model (llama3.2:3b)...", "info", 0.90)
        self._push("  This may take 5-15 minutes. Do not close this window.",
                   "info")
        try:
            proc = subprocess.Popen(
                ["ollama", "pull", "llama3.2:3b"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace")
            for line in proc.stdout:
                self._push(f"  {line.rstrip()}", "info")
            proc.wait()
            if proc.returncode == 0:
                self._push("  Ollama model ready.", "ok", 0.98)
            else:
                self._push(
                    "  Ollama pull returned non-zero (may already be cached).",
                    "info", 0.98)
        except FileNotFoundError:
            self._push(
                "  Ollama not on PATH. Run 'ollama pull llama3.2:3b' after install.",
                "info", 0.98)

    def _stream_pip(self, cmd: list[str],
                    end_pct: float | None = None) -> None:
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace")
            for line in proc.stdout:
                stripped = line.strip()
                if stripped:
                    self._push(f"  {stripped}", "info")
            proc.wait()
            if proc.returncode != 0:
                self._push(f"  pip exited with code {proc.returncode}", "err")
        except Exception as exc:
            self._push(f"  pip error: {exc}", "err")
        if end_pct is not None:
            self._push("", "info", end_pct)


# ── Page 4: Complete ─────────────────────────────────────────────────────────

class CompletePage(Page):
    def __init__(self, parent: tk.Widget, wizard: "SetupWizard") -> None:
        super().__init__(parent, wizard)
        self._success_frame: tk.Frame | None = None
        self._fail_frame: tk.Frame | None = None
        self._build()

    def _build(self) -> None:
        self._success_frame = tk.Frame(self, bg=C_BG)
        _lbl(self._success_frame, "INSTALLATION COMPLETE",
             size=16, bold=True, color=C_GREEN).pack(pady=(40, 12))
        _lbl(self._success_frame,
             "Albedo Mission Control is ready.\n"
             "Double-click the Albedo shortcut on your Desktop to launch.",
             color=C_TEXT, justify="center").pack(pady=8)
        _btn(self._success_frame, "LAUNCH ALBEDO NOW",
             self._launch, bg=C_GREEN, fg="#000000", width=20).pack(pady=16)
        _btn(self._success_frame, "Exit",
             self.wizard.destroy, width=10).pack()

        self._fail_frame = tk.Frame(self, bg=C_BG)
        _lbl(self._fail_frame, "INSTALLATION FAILED",
             size=16, bold=True, color=C_DANGER).pack(pady=(40, 12))
        _lbl(self._fail_frame,
             "Review the log on the previous page for details.\n"
             "Common fixes: run as Administrator, ensure winget is available.",
             color=C_TEXT, justify="center").pack(pady=8)
        _btn(self._fail_frame, "Back",
             lambda: self.wizard.view_log(), width=10).pack(pady=12)
        _btn(self._fail_frame, "Exit",
             self.wizard.destroy, width=10).pack()

    def show(self, success: bool) -> None:
        if success:
            self._fail_frame.pack_forget()
            self._success_frame.pack(fill="both", expand=True)
        else:
            self._success_frame.pack_forget()
            self._fail_frame.pack(fill="both", expand=True)

    def _launch(self) -> None:
        try:
            subprocess.Popen(
                ["powershell.exe", "-ExecutionPolicy", "Bypass",
                 "-WindowStyle", "Normal", "-File",
                 str(ROOT / "Launch-Albedo.ps1")])
        except Exception:
            pass
        self.wizard.destroy()


# ---------------------------------------------------------------------------
# Wizard shell
# ---------------------------------------------------------------------------

class SetupWizard(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ALBEDO  //  SETUP WIZARD")
        self.geometry("680x640")
        self.resizable(False, False)
        self.configure(bg=C_BG)

        # Progress bar dark style (must be configured after Tk.__init__)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Albedo.Horizontal.TProgressbar",
                        troughcolor=C_BORDER, background=C_CYAN,
                        thickness=16, borderwidth=0)

        self._page_idx = 0
        self._build_ui()

    def _build_ui(self) -> None:
        # Header bar
        hdr = tk.Frame(self, bg=C_PANEL, height=58)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="ALBEDO  //  SETUP WIZARD",
                 fg=C_CYAN, bg=C_PANEL,
                 font=FONT_HEADER).pack(side="left", padx=20, pady=12)
        self._step_lbl = tk.Label(hdr, text="1 / 4",
                                   fg=C_MUTED, bg=C_PANEL, font=FONT_MONO)
        self._step_lbl.pack(side="right", padx=20)

        # Navigation bar (packed before content so it anchors to the bottom)
        nav = tk.Frame(self, bg=C_PANEL, height=54)
        nav.pack(fill="x", side="bottom")
        nav.pack_propagate(False)

        self._cancel_btn = _btn(nav, "Cancel", self.destroy, width=8)
        self._cancel_btn.pack(side="left", padx=12, pady=10)

        self._back_btn = _btn(nav, "< Back", self._back, width=8)
        self._back_btn.pack(side="left", padx=4, pady=10)

        self._next_btn = _btn(nav, "Next >", self._next, width=12)
        self._next_btn.pack(side="right", padx=12, pady=10)

        # Content area
        self._content = tk.Frame(self, bg=C_BG)
        self._content.pack(fill="both", expand=True)

        # Build pages
        self.check_page    = SystemCheckPage(self._content, self)
        self.dir_page      = DirectoryPage(self._content, self)
        self.install_page  = InstallPage(self._content, self)
        self.complete_page = CompletePage(self._content, self)
        self._pages = [self.check_page, self.dir_page,
                       self.install_page, self.complete_page]

        self._show_page(0)

    def _show_page(self, idx: int) -> None:
        for p in self._pages:
            p.pack_forget()
        self._page_idx = idx
        page = self._pages[idx]
        page.pack(fill="both", expand=True)
        page.on_enter()
        self._step_lbl.configure(text=f"{idx + 1} / 4")
        self._back_btn.configure(state="normal" if idx > 0 else "disabled")
        if idx == 2:
            # Lock navigation while installing
            self._next_btn.configure(text="Installing...", state="disabled")
            self._back_btn.configure(state="disabled")
        elif idx == 3:
            self._next_btn.configure(state="disabled")
            self._cancel_btn.configure(state="disabled")
        else:
            self._next_btn.configure(text="Next >")

    def set_next_enabled(self, enabled: bool) -> None:
        self._next_btn.configure(state="normal" if enabled else "disabled")

    def _next(self) -> None:
        if self._page_idx < len(self._pages) - 1:
            self._show_page(self._page_idx + 1)

    def _back(self) -> None:
        if self._page_idx > 0:
            self._show_page(self._page_idx - 1)

    def go_page(self, idx: int) -> None:
        self._show_page(idx)

    def view_log(self) -> None:
        """Show the install log page without re-triggering the install."""
        for p in self._pages:
            p.pack_forget()
        self._page_idx = 2
        self.install_page.pack(fill="both", expand=True)
        self._step_lbl.configure(text="3 / 4")
        self._back_btn.configure(state="disabled")
        self._next_btn.configure(text="Installing...", state="disabled")
        self._cancel_btn.configure(state="normal")

    def go_to_complete(self, success: bool) -> None:
        self._show_page(3)
        self.complete_page.show(success)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = SetupWizard()
    app.mainloop()
