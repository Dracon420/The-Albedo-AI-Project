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
import webbrowser
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
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                          creationflags=subprocess.CREATE_NO_WINDOW, **kw)


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
    """
    Detect Ollama via four escalating strategies.

    shell=True on strategy 1 is the critical fix for pythonw.exe: the
    windowless launcher strips the user PATH, so shutil.which and direct
    [exe] calls both miss ollama.exe. Routing through the Windows shell
    ('cmd /c ollama --version') uses the full system PATH and succeeds
    even when the subprocess environment is stripped.

    Return True the instant any strategy succeeds so the wizard never
    triggers a download for an already-installed instance.
    """
    # Strategy 1: shell=True — Windows shell resolves the full user PATH.
    # This is the fix for pythonw.exe's stripped environment.
    try:
        r = subprocess.run(
            "ollama --version",
            capture_output=True, text=True, timeout=10, shell=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if r.returncode == 0:
            return True
    except Exception:
        pass

    # Strategy 2: shutil.which + explicit binary invocation
    exe = shutil.which("ollama")
    if exe:
        try:
            r = subprocess.run([exe, "--version"],
                               capture_output=True, text=True, timeout=10,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            if r.returncode == 0:
                return True
        except Exception:
            pass

    # Strategy 3: well-known Windows install location.
    # If the binary exists at the standard path, treat it as installed
    # regardless of --version exit code — the file presence is sufficient.
    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        candidate = Path(local_app) / "Programs" / "Ollama" / "ollama.exe"
        if candidate.is_file():
            return True

    # Strategy 4: REST probe — daemon is already running.
    # Handles the case where ollama.exe is completely off PATH but the
    # service was started by the system or a previous session.
    try:
        import urllib.request as _ur
        with _ur.urlopen("http://localhost:11434/api/version", timeout=3) as resp:
            if resp.status == 200:
                return True
    except Exception:
        pass

    return False


def _check_git() -> bool:
    try:
        return _run(["git", "--version"]).returncode == 0
    except FileNotFoundError:
        return False


def _kill_locked_processes() -> None:
    # Do NOT kill pythonw.exe — the setup wizard itself runs under pythonw.exe
    # (launched via pyw.exe), so taskkill /IM pythonw.exe would kill the wizard.
    # Any other locked processes (e.g. old ollama sessions) are handled by
    # their respective install steps.
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


def _write_env(
    gemini_key: str,
    groq_key: str,
    together_key: str,
    vault_path: str,
    piper_bin: str,
    persona: str,
    node_location: str = "",
) -> None:
    env_path   = ROOT / ".env"
    example    = ROOT / ".env.example"
    voices_dir = ROOT / "voices"

    cortana_voice = str(voices_dir / "en_US-kristin-medium.onnx")
    jarvis_voice  = str(voices_dir / "en_US-ryan-medium.onnx")
    active_voice  = jarvis_voice if persona == "jarvis" else cortana_voice
    wake_words    = "jarvis" if persona == "jarvis" else "cortana,jarvis"

    lines = (example.read_text(encoding="utf-8").splitlines()
             if example.exists() else [])
    overrides = {
        # ── Swarm Matrix / onboarding keys ──────────────────────────────
        "GEMINI_API_KEY":       gemini_key,
        "GROQ_API_KEY":         groq_key,
        "TOGETHER_API_KEY":     together_key,
        "OBSIDIAN_VAULT_PATH":  vault_path,
        "NODE_LOCATION":        node_location or "an unspecified location",
        # ── Audio / voice ────────────────────────────────────────────────
        "PIPER_BINARY":         piper_bin,
        "PIPER_VOICE_MODEL":    active_voice,
        "PIPER_VOICE_CORTANA":  cortana_voice,
        "PIPER_VOICE_JARVIS":   jarvis_voice,
        "WAKE_WORDS":           wake_words,
        "OLLAMA_MODEL":         "llama3.2:3b",
        "VOSK_MODEL_PATH":      str(ROOT.resolve() / "vosk_models" / "vosk-model-small-en-us-0.15"),
        # Phase 4 N+1: TTS engine selector. Piper stays default for v2.x
        # backward compatibility; users opt into Kokoro by editing .env.
        "AUDIO_TTS":            "piper",
        "KOKORO_MODEL_PATH":    str(ROOT.resolve() / "voices" / "kokoro-v1.0.onnx"),
        "KOKORO_VOICES_PATH":   str(ROOT.resolve() / "voices" / "voices-v1.0.bin"),
        "KOKORO_VOICE":         "af_sky",
        "KOKORO_SPEED":         "1.0",
        # Phase 4 N+2: STT engine selector. Vosk stays default for v2.x
        # backward compatibility. Users opt into Deepgram (cloud, with
        # whisper failover) or whisper (offline-only) by editing .env.
        # DEEPGRAM_API_KEY is intentionally NOT pre-filled — the dispatcher
        # falls back to Vosk silently when the key is absent.
        "AUDIO_STT":            "vosk",
        "DEEPGRAM_MODEL":       "nova-2",
        "DEEPGRAM_LANGUAGE":    "en",
        "DEEPGRAM_TIMEOUT":     "10",
        # Phase 2 alpha: UI selector. Tk remains the default until the Eel
        # frontend ships out of alpha. Users opt in with ALBEDO_UI=eel.
        "ALBEDO_UI":            "tk",
    }
    def _env_format(val: str) -> str:
        # python-dotenv interprets \v \n \t etc inside DOUBLE quotes —
        # which corrupts Windows paths. Convert backslashes to forward
        # slashes (Python pathlib handles both on Windows) and skip quoting.
        return val.replace("\\", "/") if "\\" in val else val

    result: list[str] = [
        f"# Generated by setup_utility.py -- {datetime.now():%Y-%m-%d %H:%M}", ""]
    written: set[str] = set()
    for line in lines:
        k = line.split("=")[0].strip().lstrip("#").strip()
        if k in overrides:
            result.append(f'{k}={_env_format(overrides[k])}')
            written.add(k)
        else:
            result.append(line)
    for k, v in overrides.items():
        if k not in written:
            result.append(f'{k}={_env_format(v)}')
    env_path.write_text("\n".join(result) + "\n", encoding="utf-8")

    # Belt-and-suspenders: use python-dotenv set_key for the four keys the
    # gui.py boot intercept checks.  By _step_env time pip has already run,
    # so dotenv is importable from the active interpreter.
    try:
        from dotenv import set_key
        for _k, _v in [
            ("GEMINI_API_KEY",      gemini_key),
            ("GROQ_API_KEY",        groq_key),
            ("TOGETHER_API_KEY",    together_key),
            ("OBSIDIAN_VAULT_PATH", vault_path),
        ]:
            set_key(str(env_path), _k, _v)
    except Exception:
        pass  # stdlib write above is the authoritative path


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
                # Re-verify with the full four-strategy check before downloading.
                # If Ollama is already installed but was missed by the initial
                # PATH scan (pythonw.exe stripped env), skip the winget call
                # entirely — avoids triggering a 2 GB upgrade unnecessarily.
                if not _check_ollama():
                    try:
                        subprocess.run(
                            ["winget", "install", "Ollama.Ollama",
                             "--accept-source-agreements",
                             "--accept-package-agreements", "--silent"],
                            timeout=120,
                            creationflags=subprocess.CREATE_NO_WINDOW)
                    except Exception:
                        pass
            if not self._results.get("Python 3.12"):
                try:
                    subprocess.run(
                        ["winget", "install", "Python.Python.3.12",
                         "--accept-source-agreements",
                         "--accept-package-agreements", "--silent"],
                        timeout=180,
                        creationflags=subprocess.CREATE_NO_WINDOW)
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
        self._gemini_var   = tk.StringVar(value="")
        self._groq_var     = tk.StringVar(value="")
        self._together_var = tk.StringVar(value="")
        self._vault_var    = tk.StringVar(value="")
        self._piper_var    = tk.StringVar(value=str(ROOT / "piper" / "piper.exe"))
        self._persona_var  = tk.StringVar(value="Cortana")
        self._location_var = tk.StringVar(value="")
        self._build()

    def _build(self) -> None:
        _lbl(self, "STEP 2  --  API KEYS & VAULT",
             size=14, bold=True, color=C_CYAN).pack(pady=(24, 4))
        _lbl(self,
             "Enter your Swarm Matrix API keys and select your Obsidian vault.",
             color=C_MUTED).pack(pady=(0, 12))

        box = tk.Frame(self, bg=C_PANEL, bd=0)
        box.pack(fill="x", padx=24, pady=4)

        self._api_row(box, "Gemini API Key",
                      self._gemini_var,
                      "https://aistudio.google.com/app/apikey")
        self._api_row(box, "Groq API Key",
                      self._groq_var,
                      "https://console.groq.com/keys")
        self._api_row(box, "Together API Key",
                      self._together_var,
                      "https://api.together.xyz/settings/api-keys")

        tk.Frame(box, height=1, bg=C_BORDER).pack(fill="x", padx=16, pady=8)

        self._dir_row(box, "Obsidian Vault Path  (your Markdown knowledge base)",
                      self._vault_var, is_dir=True)

        tk.Frame(box, height=1, bg=C_BORDER).pack(fill="x", padx=16, pady=8)

        self._path_row(box, "Piper binary path", self._piper_var)

        # Node location
        tk.Frame(box, height=1, bg=C_BORDER).pack(fill="x", padx=16, pady=8)
        loc_row = tk.Frame(box, bg=C_PANEL)
        loc_row.pack(fill="x", padx=16, pady=4)
        _lbl(loc_row, "Node Location  (City, State, Country)",
             size=10, bg=C_PANEL).pack(anchor="w")
        loc_entry = tk.Entry(loc_row, textvariable=self._location_var, bg=C_BG, fg=C_TEXT,
                             insertbackground=C_CYAN, relief="flat", bd=2,
                             font=FONT_SMALL)
        loc_entry.pack(fill="x")
        self._bind_paste(loc_entry)
        _lbl(loc_row,
             "Used for weather and local context queries. Can be left blank.",
             size=9, color=C_MUTED, bg=C_PANEL).pack(anchor="w", pady=(2, 0))

        # Persona dropdown
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
             "Gemini key is required. Vault Path and others can be added later in Settings.",
             color=C_MUTED, size=10).pack(pady=(8, 0))

    def _api_row(self, parent: tk.Widget, label: str,
                 var: tk.StringVar, help_url: str) -> None:
        """Entry row with a trailing [?] button that opens the dev console."""
        row = tk.Frame(parent, bg=C_PANEL)
        row.pack(fill="x", padx=16, pady=4)
        _lbl(row, label, size=10, bg=C_PANEL).pack(anchor="w")
        inner = tk.Frame(row, bg=C_PANEL)
        inner.pack(fill="x")
        _ent = tk.Entry(inner, textvariable=var, bg=C_BG, fg=C_TEXT,
                        insertbackground=C_CYAN, relief="flat", bd=2,
                        font=FONT_SMALL, show="•")
        _ent.pack(side="left", fill="x", expand=True, padx=(0, 4))

        # Right-click context menu for pasting API keys
        _ctx = tk.Menu(_ent, tearoff=0, bg=C_BG, fg=C_TEXT,
                       activebackground=C_CYAN, activeforeground="#000000",
                       font=FONT_SMALL)
        _ctx.add_command(label="Paste",
                         command=lambda v=var, e=_ent: v.set(e.clipboard_get()))
        _ctx.add_command(label="Clear", command=lambda v=var: v.set(""))
        _ent.bind("<Button-3>",
                  lambda ev, m=_ctx: m.tk_popup(ev.x_root, ev.y_root))

        _btn(inner, " ? ", lambda u=help_url: webbrowser.open(u),
             width=3).pack(side="left")

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

    def _bind_paste(self, entry: tk.Entry) -> None:
        menu = tk.Menu(self, tearoff=0, bg=C_PANEL, fg=C_TEXT,
                       activebackground=C_CYAN, activeforeground="#000000",
                       relief="flat", font=FONT_SMALL)
        menu.add_command(label="Paste", command=lambda: self._paste_into(entry))
        entry.bind("<Button-3>", lambda e, m=menu: m.tk_popup(e.x_root, e.y_root), add=True)

    def _paste_into(self, entry: tk.Entry) -> None:
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return
        entry.delete(0, "end")
        entry.insert(0, text)

    def get_values(self) -> dict[str, str]:
        return {
            "gemini_key":   self._gemini_var.get().strip(),
            "groq_key":     self._groq_var.get().strip(),
            "together_key": self._together_var.get().strip(),
            "vault_path":   self._vault_var.get().strip(),
            "piper_bin":    self._piper_var.get().strip(),
            "persona":      self._persona_var.get().strip().lower(),
            "location":     self._location_var.get().strip(),
        }


# ── Page 3: Installing ───────────────────────────────────────────────────────

class InstallPage(Page):
    def __init__(self, parent: tk.Widget, wizard: "SetupWizard") -> None:
        super().__init__(parent, wizard)
        self._q: queue.Queue = queue.Queue()
        self._polling = False
        self._started = False
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
        if self._started:
            return
        self._started = True
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
            self._step_env(dirs)
            self._step_download_voices()
            self._step_download_kokoro()
            self._step_vosk_model()
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
        if VENV.exists() and VENV_PY.exists():
            self._push("  Existing .venv detected -- reusing.", "info", 0.08)
        else:
            if VENV.exists() and not VENV_PY.exists():
                self._push("  .venv exists but python.exe missing -- recreating...", "info", 0.08)
            else:
                self._push("Creating virtual environment...", "info", 0.10)
            r = subprocess.run([py, "-m", "venv", str(VENV), "--clear"],
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               creationflags=subprocess.CREATE_NO_WINDOW)
            if r.returncode != 0:
                raise RuntimeError(f"venv creation failed:\n{r.stderr}")
            self._push("  .venv created.", "ok")

    def _step_build_tools(self) -> None:
        self._push("Upgrading pip / wheel / setuptools...", "info", 0.15)
        try:
            # Use 'python -m pip' instead of pip.exe to avoid the
            # "To modify pip" warning when installed under Program Files.
            self._stream_pip([str(VENV_PY), "-m", "pip", "install", "--upgrade",
                              "pip", "wheel", "setuptools",
                              "--no-cache-dir", "--quiet"])
            self._push("  Build tools up to date.", "ok")
        except RuntimeError as exc:
            self._push(f"  pip upgrade skipped (non-fatal): {exc}", "info")

    def _step_requirements(self) -> None:
        self._push("Installing Python dependencies...", "info", 0.20)
        self._push("  (this takes 3-10 minutes on first run)", "info")
        req = ROOT / "requirements.txt"
        self._stream_pip([str(VENV_PY), "-m", "pip", "install",
                          "-r", str(req), "--prefer-binary", "--no-cache-dir"],
                         end_pct=0.75)
        self._push("  Dependencies installed.", "ok", 0.75)
        self._verify_customtkinter()

    def _verify_customtkinter(self) -> None:
        """Force-reinstall customtkinter if its asset files are missing."""
        icon = (VENV / "Lib" / "site-packages" / "customtkinter" /
                "assets" / "icons" / "CustomTkinter_icon_Windows.ico")
        if not icon.exists():
            self._push("  customtkinter assets missing — reinstalling...", "warn")
            self._stream_pip([str(VENV_PY), "-m", "pip", "install",
                              "--force-reinstall", "--no-cache-dir", "customtkinter==5.2.2"])
            self._push("  customtkinter reinstalled.", "ok")

    def _step_playwright(self) -> None:
        self._push("Installing Playwright browser...", "info", 0.77)
        try:
            r = subprocess.run(
                [str(VENV_PY), "-m", "playwright", "install", "chromium"],
                capture_output=True, text=True, timeout=120,
                encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW)
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

    def _step_download_kokoro(self) -> None:
        """
        Download the Kokoro TTS model + voices files (~340 MB total) from
        the kokoro-onnx GitHub release, into <project_root>/voices/.

        Skipped silently if both files already exist. Failures are
        non-fatal — the dispatcher falls back to Piper when Kokoro
        files are missing, so the install still completes.
        """
        target_dir = ROOT / "voices"
        target_dir.mkdir(parents=True, exist_ok=True)
        files = [
            ("kokoro-v1.0.onnx",
             "https://github.com/thewh1teagle/kokoro-onnx/releases/"
             "download/model-files-v1.0/kokoro-v1.0.onnx",
             311 * 1024 * 1024),       # rough expected size for progress message
            ("voices-v1.0.bin",
             "https://github.com/thewh1teagle/kokoro-onnx/releases/"
             "download/model-files-v1.0/voices-v1.0.bin",
             27 * 1024 * 1024),
        ]
        all_present = all((target_dir / name).exists() for name, _, _ in files)
        if all_present:
            self._push("  Kokoro model files already present — skipping.", "ok", 0.835)
            return

        self._push("Downloading Kokoro TTS model (~340 MB, one-time)...",
                   "info", 0.832)
        for name, url, _ in files:
            dest = target_dir / name
            if dest.exists():
                self._push(f"  {name} already present — skipping.", "info")
                continue
            self._push(f"  Fetching {name}...", "info")
            try:
                urllib.request.urlretrieve(url, dest)
                self._push(f"  {name} downloaded ({dest.stat().st_size // (1024*1024)} MB).",
                           "ok")
            except Exception as exc:
                self._push(
                    f"  {name} download failed (non-fatal): {exc}.  "
                    "Kokoro will be unavailable until you fetch it manually from "
                    "github.com/thewh1teagle/kokoro-onnx/releases.",
                    "info")
                # Remove partial file so a retry doesn't see a stale 0-byte dest.
                try:
                    dest.unlink()
                except OSError:
                    pass

    def _step_vosk_model(self) -> None:
        """
        Download and unzip vosk-model-small-en-us-0.15 (~40 MB) into
        <project_root>/vosk_models/.  Skipped if already present.
        Vosk is now the single STT + wake word engine — replaces both
        faster-whisper and openwakeword from earlier builds.
        """
        import zipfile

        target_root = ROOT / "vosk_models"
        model_dir   = target_root / "vosk-model-small-en-us-0.15"
        zip_path    = target_root / "vosk-model-small-en-us-0.15.zip"
        url         = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"

        self._push("[SYS] Verifying/Downloading Vosk STT model (~40 MB)...", "info", 0.85)

        if model_dir.exists():
            self._push("  Vosk model already present — skipping download.", "ok", 0.86)
            return

        try:
            target_root.mkdir(parents=True, exist_ok=True)
            self._push(f"  Fetching {url}", "info")
            urllib.request.urlretrieve(url, zip_path)
            self._push("  Download complete. Extracting...", "info")
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(target_root)
            try:
                zip_path.unlink()
            except OSError:
                pass
            if model_dir.exists():
                self._push("  Vosk model ready.", "ok", 0.86)
            else:
                self._push("  Vosk extracted but expected directory missing.", "info", 0.86)
        except Exception as exc:
            self._push(f"  Vosk download skipped (non-fatal): {exc}", "info", 0.86)

    def _step_env(self, dirs: dict[str, str]) -> None:
        self._push("Writing .env configuration...", "info", 0.84)
        persona = dirs.get("persona", "cortana")
        _write_env(
            gemini_key=dirs.get("gemini_key", ""),
            groq_key=dirs.get("groq_key", ""),
            together_key=dirs.get("together_key", ""),
            vault_path=dirs.get("vault_path", ""),
            piper_bin=dirs.get("piper_bin", ""),
            persona=persona,
            node_location=dirs.get("location", ""),
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

    def _step_ollama(self) -> None:
        self._push("Pulling Ollama model (llama3.2:3b)...", "info", 0.90)
        self._push("  This may take 5-15 minutes. Do not close this window.",
                   "info")
        try:
            proc = subprocess.Popen(
                ["ollama", "pull", "llama3.2:3b"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW)
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
                text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW)
            for line in proc.stdout:
                stripped = line.strip()
                if stripped:
                    self._push(f"  {stripped}", "info")
            proc.wait()
            if proc.returncode != 0:
                raise RuntimeError(
                    f"pip exited with code {proc.returncode}. "
                    "Check your internet connection and try again.")
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"pip error: {exc}") from exc
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
                 str(ROOT / "Launch-Albedo.ps1")],
                creationflags=subprocess.CREATE_NO_WINDOW)
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
