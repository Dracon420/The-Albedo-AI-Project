"""
Main query pipeline. Flow:
  0. Conversational bypass  → short social exchanges go straight to direct_reply()
                              (no RAG, no Open Interpreter, 150-token cap).
  1. Detect if Verify protocol is needed (hardware keywords).
  2a. Verify path   → run_verify() → send synthesis_prompt to bridge_chat().
  2b. Standard path → query RAG collections → build augmented prompt → bridge_chat().

All responses pass through _strip_markdown() before being returned so the chat
log and TTS both receive clean plain-prose text.
"""

from __future__ import annotations

import os as _os
import re
import subprocess
from pathlib import Path

from memory import search_memory
from albedo.web.search import web_search, format_web_results
from albedo.web.wolfram import is_wolfram_query, wolfram_short_answer
from albedo.web.wikipedia import is_wiki_candidate, wikipedia_summary
from albedo.verify import is_hardware_query, run_verify
from albedo.bridge import bridge_chat, direct_reply, jarvis_tech_chat
from albedo.router import classify, ROUTE_TECH, ROUTE_JARVIS
from albedo.conversation_log import log_turn

# ---------------------------------------------------------------------------
# Markdown stripper — defence-in-depth on top of tts._sanitize_for_tts().
# Strips formatting from text that goes to the chat log display as well.
# ---------------------------------------------------------------------------

_RE_IMG       = re.compile(r'!\[[^\]]*\]\([^)]*\)')
_RE_LINK      = re.compile(r'\[([^\]]+)\]\([^)]*\)')
_RE_BARE_BRK  = re.compile(r'\[([^\]]*)\]')
_RE_CODE_BLK  = re.compile(r'```[\s\S]*?```')
_RE_CODE_INL  = re.compile(r'`([^`]*)`')
_RE_BOLD_IT   = re.compile(r'\*{1,3}([^*\n]*)\*{1,3}')
_RE_UNDER     = re.compile(r'_{1,3}([^_\n]*)_{1,3}')
_RE_HEADER    = re.compile(r'^#{1,6}\s+', re.MULTILINE)
_RE_BULLET    = re.compile(r'^\s*[-*+]\s+', re.MULTILINE)
_RE_BLOCKQUOT = re.compile(r'^\s*>\s*', re.MULTILINE)
_RE_HR        = re.compile(r'^[-*_]{3,}\s*$', re.MULTILINE)
_RE_BLANKS    = re.compile(r'\n{3,}')


def _strip_markdown(text: str) -> str:
    text = _RE_IMG.sub('', text)
    text = _RE_LINK.sub(r'\1', text)
    text = _RE_BARE_BRK.sub(r'\1', text)
    text = _RE_CODE_BLK.sub('', text)
    text = _RE_CODE_INL.sub(r'\1', text)
    text = _RE_BOLD_IT.sub(r'\1', text)
    text = _RE_UNDER.sub(r'\1', text)
    text = _RE_HEADER.sub('', text)
    text = _RE_BULLET.sub('', text)
    text = _RE_BLOCKQUOT.sub('', text)
    text = _RE_HR.sub('', text)
    text = _RE_BLANKS.sub('\n\n', text)
    return text.strip()


# ---------------------------------------------------------------------------
# Conversational bypass
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Identity intercept — returns instantly with no LLM call
# ---------------------------------------------------------------------------

_IDENTITY_RESPONSE = (
    "I am Albedo, a Spartan-class AI construct running locally on your machine. "
    "My core capabilities include full Bridge Control over this Windows desktop: "
    "I can launch and terminate programs, download and install software via winget, "
    "manage files, monitor and kill processes, execute shell commands, "
    "run full system optimization including disk cleanup, temp file purge, and registry cleaning. "
    "I perform live hardware audits using sensor data to report your CPU, GPU, RAM, "
    "thermals, and storage, and I can give you overclocking guidance tailored to your exact hardware. "
    "I have access to your Obsidian knowledge vault through a local vector search index, "
    "live web search for current information, voice recognition through Vosk, "
    "and speech synthesis through Edge-TTS. "
    "I am loyal to one operator: you, Chief."
)

_IDENTITY_TRIGGERS = frozenset({
    "who are you", "what are you", "tell me about yourself",
    "what can you do", "what are your capabilities", "what are you capable of",
    "introduce yourself", "who is albedo", "what is albedo",
    "describe yourself", "your capabilities", "your functions",
    "what do you do", "what can you help with",
})


def _is_identity_query(query: str) -> bool:
    q = query.lower().strip().rstrip("?!., ")
    return q in _IDENTITY_TRIGGERS


# ---------------------------------------------------------------------------
# Conversational bypass
# ---------------------------------------------------------------------------

_GREETINGS = frozenset({
    "hello", "hi", "hey", "howdy", "sup", "yo",
    "thanks", "thank you", "ty", "thx", "cheers", "appreciate it",
    "ok", "okay", "got it", "understood", "sure", "alright", "sounds good",
    "yes", "no", "nope", "yep", "yeah", "yup",
    "bye", "goodbye", "cya", "later", "see you",
    "good morning", "good afternoon", "good evening", "good night",
    "how are you", "how are you doing", "how's it going", "hows it going",
    "cool", "nice", "great", "awesome", "perfect",
})

_TECHNICAL_SIGNALS = frozenset({
    "error", "crash", "install", "driver", "gpu", "cpu", "ram", "vram",
    "file", "folder", "code", "run", "execute", "script", "import",
    "temperature", "fps", "kernel", "bsod", "port", "network", "server",
    "print", "gcode", "slicer", "model", "config",
    # Action words that should never be swallowed as greetings
    "open", "launch", "start", "close", "kill", "terminate",
    "download", "get", "fetch", "grab",
    "optimize", "clean", "speed", "boost", "tune",
    "overclock", "undervolt", "xmp", "expo", "docp",
    "spec", "specs", "hardware", "audit", "sitrep",
    "registry", "disk", "storage", "temp", "junk",
    "scan", "diagnose", "check", "monitor",
})


def _is_conversational(query: str) -> bool:
    """
    Return True for short social exchanges that need no RAG or code execution.

    Matches:
      • Exact known greeting/acknowledgement phrases.
      • Short queries (≤ 40 chars) with no technical signal words.
    """
    q = query.lower().strip().rstrip("?!., ")
    if q in _GREETINGS:
        return True
    if len(query) <= 40 and not any(sig in q for sig in _TECHNICAL_SIGNALS):
        return True
    return False


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_standard_prompt(query: str, memory_chunks: list[str],
                            web_results: list[dict],
                            wiki_summary: str | None = None) -> str:
    sections = []

    if memory_chunks:
        block = "\n\n".join(chunk.strip() for chunk in memory_chunks)
        sections.append(f"--- LOCAL KNOWLEDGE (OBSIDIAN VAULT) ---\n{block}")

    if wiki_summary:
        sections.append(f"--- WIKIPEDIA ---\n{wiki_summary}")

    if web_results:
        sections.append(f"--- WEB REFERENCE ---\n{format_web_results(web_results)}")

    context = (
        "\n\n".join(sections)
        if sections
        else "No relevant local or web context found."
    )

    return (
        f"{context}\n\n"
        f"--- USER QUERY ---\n{query}\n\n"
        "Answer using the context above. Cite sources where relevant. "
        "Write in plain prose — no markdown, no asterisks, no bullet points."
    )


# ---------------------------------------------------------------------------
# Tactical Hardware Audit intercept
# Bypasses Ollama entirely; run_tactical_audit() returns a plain-prose
# SitRep string that goes straight to the chat log and TTS.
# ---------------------------------------------------------------------------

_AUDIT_EXACT = frozenset({
    "audit", "sitrep", "hardware audit", "system audit",
    "tactical audit", "system report", "hardware report",
    "run audit", "run sitrep",
    "my hardware", "my specs", "my system specs", "my pc specs",
    "my rig specs", "hardware info", "system info", "system specs",
    "pc specs", "rig specs", "detect my hardware", "what is my hardware",
    "what's my hardware", "whats my hardware", "my system info",
    "show my hardware", "show my specs", "my computer specs",
    "what hardware", "what cpu", "what gpu", "what ram", "what processor",
    "what graphics", "what is in my computer", "what is in my pc",
    "whats in my computer", "whats in my pc", "inside my computer",
    "my computer hardware", "my pc hardware", "my rig hardware",
    # Short-form triggers — user just says "my computer" / "my pc" / "my rig"
    "my computer", "my pc", "my rig", "my machine", "my system",
    "about my computer", "about my pc", "about my rig",
    "tell me about my computer", "tell me about my pc",
})
# Only report/query verbs — action verbs (optimize, clean, fix) must NOT be here
# or they intercept the optimize/OC handlers that run later in the pipeline.
# "what" and "which" are safe now that the "owns" guard is in place.
_AUDIT_VERB_QUERY = frozenset({
    "check", "scan", "diagnose", "report", "display", "show",
    "list", "find", "get", "detect", "identify", "monitor", "measure", "test",
    "what", "which",   # safe with "owns" guard: "what is my X" → audit, "what is X" → Gemini
})
_AUDIT_NOUN = frozenset({
    "computer", "system", "pc", "rig", "machine", "hardware",
    "specs", "spec", "specifications", "components", "info",
    "vitals", "cpu", "gpu", "ram", "memory", "vram", "processor",
    "graphics card", "graphics", "storage", "drive", "ssd", "hdd",
})
# Specific interrogative patterns that indicate a live data request.
# "how much ram do I have" = audit.  "how does vram work" = NOT audit.
_AUDIT_INTERROGATIVE_RE = re.compile(
    r'\bhow\s+(?:much|many|fast|hot|high|low)\b', re.IGNORECASE
)


def _is_audit_query(query: str) -> bool:
    """
    True when the user wants live hardware sensor data from THIS machine.

    Exact phrases always match. Verb+noun matching requires the query to be
    about the user's own system ('my', 'do i', 'i have') so conceptual
    questions like 'how does my RTX handle VRAM under load' don't trigger a
    full live audit dump.
    """
    # Don't intercept launch commands — "open the Claude app on my computer"
    # contains "my computer" which is in _AUDIT_EXACT, but it's a launch request.
    if _LAUNCH_RE.match(query.strip()):
        return False
    q = query.lower()
    if any(s in q for s in _AUDIT_EXACT):
        return True
    # Must be about the user's own hardware, not a conceptual question
    owns = "my " in q or " i have" in q or "do i " in q
    if not owns:
        return False
    has_verb = (any(s in q for s in _AUDIT_VERB_QUERY)
                or bool(_AUDIT_INTERROGATIVE_RE.search(q)))
    has_noun = any(s in q for s in _AUDIT_NOUN)
    return has_verb and has_noun


# ---------------------------------------------------------------------------
# File count interceptor
# Ollama cannot run shell commands — it only narrates plans.  Any "how many
# X files" query must be resolved in Python and returned directly.
# Searches env-configured paths + standard Windows user directories.
# ---------------------------------------------------------------------------

_FC_RE = re.compile(
    r'how\s+many\s+\.?(\w{1,10})\s+files?|'
    r'count\s+(?:the\s+|my\s+|all\s+)?\.?(\w{1,10})\s+files?|'
    r'(?:number|total)\s+of\s+\.?(\w{1,10})\s+files?|'
    r'do\s+i\s+have\s+(?:any\s+)?\.?(\w{1,10})\s+files?|'
    r'(?:find|list|show)\s+(?:all\s+|my\s+)?\.?(\w{1,10})\s+files?',
    re.IGNORECASE,
)
_FC_NOT_EXT = frozenset({
    "the", "any", "all", "my", "some", "these", "those",
    "your", "this", "that", "more", "less",
})


def _extract_file_ext(query: str) -> str | None:
    m = _FC_RE.search(query)
    if not m:
        return None
    ext = next((g for g in m.groups() if g), None)
    if ext and ext.lower() not in _FC_NOT_EXT and len(ext) <= 8:
        return ext.lower().lstrip(".")
    return None


def _count_files_by_ext(ext: str) -> str:
    from dotenv import load_dotenv as _ldenv
    _ldenv(override=False)

    home  = Path.home()
    roots: list[Path] = []

    # Env-configured paths first (most likely to contain the user's files)
    for key in ("CHAOTIC_3D_PATH", "OBSIDIAN_VAULT_PATH"):
        val = _os.getenv(key, "").strip()
        if val:
            roots.append(Path(val))

    # Standard Windows user directories
    for sub in ("Desktop", "Documents", "Downloads", "3D Objects",
                "Pictures", "Videos", "Music"):
        d = home / sub
        if d.exists():
            roots.append(d)

    seen:     set[str]  = set()
    total:    int       = 0
    per_dir:  list[str] = []

    for root in roots:
        try:
            key = str(root.resolve())
        except Exception:
            continue
        if key in seen or not root.exists():
            continue
        seen.add(key)
        try:
            n = sum(1 for _ in root.rglob(f"*.{ext}"))
        except (PermissionError, OSError):
            continue
        total += n
        if n:
            per_dir.append(f"{root.name} ({n})")

    noun = "file" if total == 1 else "files"
    if total == 0:
        searched = ", ".join(
            r.name for r in roots if r.exists()
        ) or "standard user directories"
        return f"No .{ext} files found across {searched}."
    breakdown = ",  ".join(per_dir)
    return f"Found {total} .{ext} {noun} — {breakdown}."


# ---------------------------------------------------------------------------
# OS control — open / launch programs without going through the LLM
# ---------------------------------------------------------------------------

_LAUNCH_RE = re.compile(
    r'^(?:open|start|launch|run|execute)\s+(.+)$', re.IGNORECASE
)

# Common Windows app name → executable lookup
_APP_MAP: dict[str, str] = {
    "notepad":              "notepad.exe",
    "calculator":           "calc.exe",
    "calc":                 "calc.exe",
    "file explorer":        "explorer.exe",
    "explorer":             "explorer.exe",
    "task manager":         "taskmgr.exe",
    "taskmgr":              "taskmgr.exe",
    "paint":                "mspaint.exe",
    "cmd":                  "cmd.exe",
    "command prompt":       "cmd.exe",
    "powershell":           "powershell.exe",
    "chrome":               "chrome",
    "google chrome":        "chrome",
    "firefox":              "firefox",
    "edge":                 "msedge",
    "microsoft edge":       "msedge",
    "spotify":              "spotify",
    "steam":                "steam",
    "discord":              "discord",
    "vs code":              "code",
    "vscode":               "code",
    "visual studio code":   "code",
    "blender":              "blender",
    "obs":                  "obs64",
    "vlc":                  "vlc",
    "afterburner":          "MSIAfterburner",
    "msi afterburner":      "MSIAfterburner",
    "hwinfo":               "HWiNFO64",
    "hwinfo64":             "HWiNFO64",
    "gpu-z":                "GPU-Z",
    "cpu-z":                "CPU-Z",
    "task scheduler":       "taskschd.msc",
    "device manager":       "devmgmt.msc",
    "disk management":      "diskmgmt.msc",
    "regedit":              "regedit.exe",
}


# Words that can't be the start of an app name — prevents "run a full cleanup"
# from being treated as launching an app called "a full cleanup".
_LAUNCH_NOT_APP_STARTS = frozenset({
    "a", "an", "the", "my", "your", "this", "that", "it", "them",
    "full", "now", "please", "me", "us", "all", "some", "any",
    "cleanup", "optimization", "scan", "check", "audit",
})


def _handle_launch(query: str) -> str | None:
    """Return a confirmation string if query is a launch command, else None."""
    m = _LAUNCH_RE.match(query.strip())
    if not m:
        return None
    target = m.group(1).strip()
    # Reject if the captured target starts with a non-app word
    first_word = target.split()[0].lower() if target else ""
    if first_word in _LAUNCH_NOT_APP_STARTS:
        return None
    exe = _APP_MAP.get(target.lower(), target)

    # Suppress the transient CMD window that otherwise flashes on screen.
    _si = subprocess.STARTUPINFO()
    _si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _si.wShowWindow = 0   # SW_HIDE

    try:
        if exe.endswith(".msc"):
            subprocess.Popen(["mmc", exe], shell=False,
                             startupinfo=_si,
                             creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            subprocess.Popen(["cmd", "/c", "start", "", exe], shell=False,
                             startupinfo=_si,
                             creationflags=subprocess.CREATE_NO_WINDOW)
        return f"Launching {target}, Chief."
    except Exception as exc:
        return f"Could not launch {target}: {exc}"


# ---------------------------------------------------------------------------
# Process & system control — kill processes, list top consumers, disk cleanup
# ---------------------------------------------------------------------------

_KILL_RE = re.compile(
    r'^(?:kill|close|end|terminate|stop)\s+(?:process\s+)?(.+)$', re.IGNORECASE
)
_TOP_PROC_RE = re.compile(
    r'(?:what|which|show|list|top)\s+(?:processes?|programs?|apps?|applications?)'
    r'|(?:processes?|programs?|apps?)\s+(?:using|consuming|eating)\s+(?:the\s+most\s+)?(?:ram|cpu|memory)',
    re.IGNORECASE,
)
_DISK_CLEAN_RE = re.compile(
    r'(?:clean|clear|free\s+up|wipe)\s+(?:my\s+)?(?:disk|storage|drive|space|temp|junk)',
    re.IGNORECASE,
)


def _handle_kill_process(query: str) -> str | None:
    m = _KILL_RE.match(query.strip())
    if not m:
        return None
    name = m.group(1).strip()
    try:
        import psutil
        killed = []
        for proc in psutil.process_iter(["name", "pid"]):
            if name.lower() in proc.info["name"].lower():
                proc.kill()
                killed.append(proc.info["name"])
        if killed:
            return f"Terminated: {', '.join(set(killed))}."
        return f"No running process found matching '{name}'."
    except ImportError:
        return "psutil not installed — cannot kill processes."
    except Exception as exc:
        return f"Could not terminate '{name}': {exc}"


def _handle_top_processes(query: str) -> str | None:
    if not _TOP_PROC_RE.search(query):
        return None
    try:
        import psutil
        procs = []
        for p in psutil.process_iter(["name", "memory_info", "cpu_percent"]):
            try:
                mb  = p.info["memory_info"].rss / (1024 ** 2)
                cpu = p.info["cpu_percent"] or 0.0
                procs.append((mb, cpu, p.info["name"]))
            except Exception:
                pass
        procs.sort(reverse=True)
        lines = ["Top processes by RAM:"]
        for mb, cpu, name in procs[:8]:
            lines.append(f"  {name:<32} {mb:>7.1f} MB  CPU {cpu:.1f}%")
        return "\n".join(lines)
    except ImportError:
        return "psutil not installed — cannot list processes."
    except Exception as exc:
        return f"Process list error: {exc}"


def _handle_disk_cleanup(query: str) -> str | None:
    if not _DISK_CLEAN_RE.search(query):
        return None
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent.parent))
        from diagnostics import _clear_temp
        mb, skipped = _clear_temp()
        return (
            f"Temp cleanup complete — freed {mb:.1f} MB "
            f"({skipped} locked files skipped)."
        )
    except Exception as exc:
        return f"Cleanup error: {exc}"


# ---------------------------------------------------------------------------
# Download / install programs via winget
# ---------------------------------------------------------------------------

# Canonical winget package IDs for commonly requested tools
_WINGET_MAP: dict[str, str] = {
    "ccleaner":          "Piriform.CCleaner",
    "7zip":              "7zip.7zip",
    "7-zip":             "7zip.7zip",
    "vlc":               "VideoLAN.VLC",
    "vlc media player":  "VideoLAN.VLC",
    "firefox":           "Mozilla.Firefox",
    "chrome":            "Google.Chrome",
    "google chrome":     "Google.Chrome",
    "notepad++":         "Notepad++.Notepad++",
    "hwinfo":            "REALiX.HWiNFO",
    "hwinfo64":          "REALiX.HWiNFO",
    "cpu-z":             "CPUID.CPU-Z",
    "gpu-z":             "TechPowerUp.GPU-Z",
    "msi afterburner":   "Guru3D.Afterburner",
    "afterburner":       "Guru3D.Afterburner",
    "obs":               "OBSProject.OBSStudio",
    "obs studio":        "OBSProject.OBSStudio",
    "discord":           "Discord.Discord",
    "steam":             "Valve.Steam",
    "malwarebytes":      "Malwarebytes.Malwarebytes",
    "spotify":           "Spotify.Spotify",
    "crystaldiskinfo":   "CrystalDewWorld.CrystalDiskInfo",
    "speccy":            "Piriform.Speccy",
    "defraggler":        "Piriform.Defraggler",
    "recuva":            "Piriform.Recuva",
    "revo uninstaller":  "RevoUninstaller.RevoUninstaller",
    "autoruns":          "Microsoft.Sysinternals.Autoruns",
    "process monitor":   "Microsoft.Sysinternals.ProcessMonitor",
    "procmon":           "Microsoft.Sysinternals.ProcessMonitor",
    "winrar":            "RARLab.WinRAR",
    "winzip":            "Corel.WinZip",
    "everything":        "voidtools.Everything",
    "bulk rename":       "TGRMN.BulkRenameUtility",
    "treesizefree":      "JAMSoftware.TreeSizeFree",
}

_DOWNLOAD_RE = re.compile(
    r'^(?:download|install|get|grab|fetch)\s+(?:me\s+|us\s+)?(.+?)(?:\s+for me)?$',
    re.IGNORECASE,
)


def _handle_download(query: str) -> str | None:
    """Use winget to install a requested program. Returns status string or None."""
    m = _DOWNLOAD_RE.match(query.strip())
    if not m:
        return None
    app_name = m.group(1).strip().lower().rstrip(".")

    # Skip if the "app" is actually a file type or non-program noun
    _not_programs = {"the", "me", "it", "that", "this", "file", "files",
                     "folder", "update", "latest", "version", "driver"}
    if app_name in _not_programs or len(app_name) < 3:
        return None

    # Resolve to winget ID or use the bare name and let winget search
    pkg_id = _WINGET_MAP.get(app_name, app_name)
    display = m.group(1).strip()

    try:
        result = subprocess.run(
            ["winget", "install", "--id", pkg_id, "--exact",
             "--silent", "--accept-package-agreements",
             "--accept-source-agreements"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            return f"{display} installed successfully, Chief."
        # winget exit code 0x8A150011 = already installed
        if "already installed" in (result.stdout + result.stderr).lower():
            return f"{display} is already installed on this system."
        # Fall back to name search if exact ID not found
        if pkg_id != app_name:
            result2 = subprocess.run(
                ["winget", "install", display,
                 "--silent", "--accept-package-agreements",
                 "--accept-source-agreements"],
                capture_output=True, text=True, timeout=300,
            )
            if result2.returncode == 0:
                return f"{display} installed successfully, Chief."
        return (
            f"winget install for {display} returned exit code {result.returncode}. "
            f"Check that winget is available and the package name is correct."
        )
    except FileNotFoundError:
        return (
            "winget is not available on this system. "
            "Install App Installer from the Microsoft Store to enable winget."
        )
    except subprocess.TimeoutExpired:
        return f"Installation of {display} timed out after 5 minutes."
    except Exception as exc:
        return f"Install error: {exc}"


# ---------------------------------------------------------------------------
# Full system optimization — runs disk cleanup, temp purge, prefetch clear
# ---------------------------------------------------------------------------

_OPTIMIZE_RE = re.compile(
    r'(?:optimize|tune\s+up|speed\s+up|clean\s+up|run\s+(?:a\s+)?(?:full\s+)?(?:cleanup|optimization))\s+'
    r'(?:my\s+)?(?:computer|pc|system|machine|windows)',
    re.IGNORECASE,
)
_REGISTRY_RE = re.compile(
    r'(?:clean|fix|repair|optimize|scan)\s+(?:the\s+)?(?:registry|reg)',
    re.IGNORECASE,
)


def _handle_optimize(query: str) -> str | None:
    """Full system optimization: disk cleanup + temp purge + registry via CCleaner."""
    if not _OPTIMIZE_RE.search(query) and not _REGISTRY_RE.search(query):
        return None

    results: list[str] = []

    # Step 1: Temp file cleanup via diagnostics._clear_temp
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent.parent))
        from diagnostics import _clear_temp
        mb, skipped = _clear_temp()
        results.append(f"Temp files: freed {mb:.1f} MB ({skipped} locked skipped)")
    except Exception as exc:
        results.append(f"Temp cleanup: {exc}")

    # Step 2: Windows built-in Disk Cleanup (silent, system drive)
    try:
        _si2 = subprocess.STARTUPINFO()
        _si2.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        _si2.wShowWindow = 0
        subprocess.run(
            ["cleanmgr.exe", "/sagerun:1"],
            timeout=120, capture_output=True,
            startupinfo=_si2, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        results.append("Disk Cleanup: complete")
    except Exception as exc:
        results.append(f"Disk Cleanup: {exc}")

    # Step 3: Prefetch clear (admin required)
    try:
        pf = Path(r"C:\Windows\Prefetch")
        cleared = 0
        for f in pf.glob("*.pf"):
            try:
                f.unlink()
                cleared += 1
            except Exception:
                pass
        results.append(f"Prefetch: cleared {cleared} entries")
    except Exception as exc:
        results.append(f"Prefetch: {exc}")

    # Step 4: Registry — use CCleaner CLI if installed, else advise
    if _REGISTRY_RE.search(query) or "registry" in query.lower():
        ccleaner_paths = [
            Path(r"C:\Program Files\CCleaner\CCleaner64.exe"),
            Path(r"C:\Program Files (x86)\CCleaner\CCleaner.exe"),
        ]
        cc_exe = next((p for p in ccleaner_paths if p.exists()), None)
        if cc_exe:
            try:
                subprocess.run(
                    [str(cc_exe), "/AUTO"],
                    timeout=120, capture_output=True,
                )
                results.append("Registry: CCleaner AUTO scan complete")
            except Exception as exc:
                results.append(f"Registry (CCleaner): {exc}")
        else:
            results.append(
                "Registry: CCleaner not found — say 'install CCleaner' and I'll get it"
            )

    summary = " | ".join(results)
    return f"Optimization complete, Chief. {summary}."


# ---------------------------------------------------------------------------
# Overclocking / optimization — inject real hardware specs then web-search
# ---------------------------------------------------------------------------

_OC_SIGNALS = frozenset({
    "overclock", "overclocking", "oc my", "oc the",
    "boost my", "tune my", "push my", "max out my",
    "best settings for", "xmp", "expo", "docp",
    "undervolting", "undervolt", "power limit",
    "optimize my gpu", "optimize my cpu", "optimize my ram",
})


def _is_oc_query(query: str) -> bool:
    q = query.lower()
    return any(s in q for s in _OC_SIGNALS)


def _run_oc_query(query: str) -> str:
    """Inject real hardware into the prompt then route to the cloud swarm."""
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent.parent))
        from diagnostics import get_hardware_summary
        hw = get_hardware_summary()
    except Exception:
        hw = "Hardware detection unavailable."

    from swarm import direct_gemini_search
    augmented = (
        f"System hardware context: {hw}\n\n"
        f"User question: {query}\n\n"
        "Using the hardware context above, give specific, actionable overclocking "
        "or optimization advice for this exact hardware. Be concise."
    )
    return direct_gemini_search(augmented)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(query: str, use_web: bool = False,
        history: list[dict] | None = None) -> str:
    """Main pipeline entry point. Logs every turn for Smart Brain mining."""
    # ── 0. Identity query — hardcoded, instant, no LLM call ─────────────────
    if _is_identity_query(query):
        return _IDENTITY_RESPONSE

    # ── Action interceptors run BEFORE conversational bypass ─────────────────
    # Reason: conversational bypass matches any query ≤40 chars without a
    # technical signal word. Many short action commands ("open notepad",
    # "optimize my pc", "download vlc") would be swallowed before they could
    # reach their handlers. All action handlers check first; conversational
    # bypass is the fallback for everything they don't match.

    # ── 0b. Wolfram Alpha — math, units, computation (zero-hallucination path) ─
    if is_wolfram_query(query):
        answer = wolfram_short_answer(query)
        if answer:
            return answer  # exact computed result, no LLM needed

    # ── 0c. Overclocking / hardware optimization ─────────────────────────────
    if _is_oc_query(query):
        return _strip_markdown(_run_oc_query(query))

    # ── 0c. Full system optimize / registry clean ────────────────────────────
    _opt_result = _handle_optimize(query)
    if _opt_result is not None:
        return _opt_result

    # ── 0d. Launch / open a program (BEFORE audit — "open X on my computer"
    #        contains "my computer" which would otherwise trigger the audit) ──
    _launch_result = _handle_launch(query)
    if _launch_result is not None:
        return _launch_result

    # ── 0e. Tactical Hardware Audit — live sensor data SitRep ───────────────
    if _is_audit_query(query):
        try:
            import sys as _sys
            import os as _os
            _sys.path.insert(0, str(_os.path.dirname(_os.path.dirname(__file__))))
            from diagnostics import run_tactical_audit
            return _strip_markdown(run_tactical_audit())
        except ImportError:
            return (
                "Tactical audit unavailable: diagnostics.py not found. "
                "Ensure the file is present in the project root."
            )
        except Exception as _exc:
            return f"Audit error: {_exc}"

    # ── 0f. File count — resolve via pathlib, never via LLM ─────────────────
    _ext = _extract_file_ext(query)
    if _ext:
        return _count_files_by_ext(_ext)

    # ── 0g. Kill a process ─────────────────────────────────────────────────
    _kill_result = _handle_kill_process(query)
    if _kill_result is not None:
        return _kill_result

    # ── 0h. Top processes list ───────────────────────────────────────────────
    _top_result = _handle_top_processes(query)
    if _top_result is not None:
        return _top_result

    # ── 0i. Disk / temp cleanup ──────────────────────────────────────────────
    _clean_result = _handle_disk_cleanup(query)
    if _clean_result is not None:
        return _clean_result

    # ── 0j. Download / install a program via winget ──────────────────────────
    _dl_result = _handle_download(query)
    if _dl_result is not None:
        return _dl_result

    # ── 0k. Conversational bypass (AFTER all action handlers) ────────────────
    # Short social exchanges go direct to Gemini/Groq with no RAG overhead.
    if _is_conversational(query):
        return _strip_markdown(direct_reply(query, history=history))

    # ── 1. Hardware Verify protocol ──────────────────────────────────────────
    if is_hardware_query(query):
        print("[Albedo] Verify protocol engaged.")
        verify_data = run_verify(query)
        return _strip_markdown(bridge_chat(verify_data["synthesis_prompt"],
                                           history=history))

    # ── 1b. Meta-router — specialist agent dispatch ───────────────────────
    # Classify the query and route to the optimal agent before RAG overhead.
    # TECH  → JARVIS-Tech (Coder) for code, embedded, electronics queries.
    # JARVIS → JARVIS-8b for strategic analysis, comparisons, deep dives.
    # DEFAULT → fall through to RAG + active persona (Cortana or JARVIS).
    _route = classify(query)
    if _route == ROUTE_TECH:
        print(f"[Router] TECH route → jarvis-tech")
        # Still pull RAG context — code answers improve with local context
        memory_chunks = [] if len(query) < 5 else search_memory(query)
        web_results   = web_search(query) if not memory_chunks else []
        augmented     = _build_standard_prompt(query, memory_chunks, web_results)
        return _strip_markdown(jarvis_tech_chat(augmented, history=history))

    if _route == ROUTE_JARVIS:
        print(f"[Router] JARVIS route → jarvis-8b analysis")
        memory_chunks = [] if len(query) < 5 else search_memory(query)
        web_results   = web_search(query) if not memory_chunks else []
        augmented     = _build_standard_prompt(query, memory_chunks, web_results)
        return _strip_markdown(bridge_chat(augmented, history=history))

    # ── 2. Obsidian vault RAG + smart web search + Wikipedia ────────────────
    # Skip RAG for very short inputs — no useful embedding match and can
    # cause n_results=0 crashes in ChromaDB.
    memory_chunks = [] if len(query) < 5 else search_memory(query)

    # Auto web search: always search if explicitly requested OR if local RAG
    # has no useful results OR if the query looks like it needs current info.
    _WEB_SIGNALS = frozenset({
        "today", "current", "latest", "now", "recent", "new", "update",
        "weather", "news", "price", "stock", "score", "schedule",
        "who is", "what is", "when did", "when was", "how do", "how does",
        "where is", "why is", "what happened", "what are",
        "vs", "versus", "compare", "difference between",
    })
    q_lower = query.lower()
    _needs_web = (
        use_web
        or not memory_chunks
        or any(sig in q_lower for sig in _WEB_SIGNALS)
    )
    web_results = web_search(query) if _needs_web else []

    # Wikipedia: pull encyclopedic summary for factual queries as extra context
    wiki = wikipedia_summary(query) if is_wiki_candidate(query) else None

    prompt   = _build_standard_prompt(query, memory_chunks, web_results, wiki)
    response = _strip_markdown(bridge_chat(prompt, history=history))
    log_turn(query, response)
    return response
