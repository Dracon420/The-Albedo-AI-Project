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
from albedo.verify import is_hardware_query, run_verify
from albedo.bridge import bridge_chat, direct_reply

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
    "I can launch and terminate programs, manage files, monitor and kill processes, "
    "and execute shell commands. "
    "I perform live hardware audits using sensor data to report your CPU, GPU, RAM, "
    "thermals, and storage, and I can give you overclocking and optimization guidance "
    "tailored to your exact hardware. "
    "I have access to your Obsidian knowledge vault through a local vector search index, "
    "live web search for current information, weather via real-time data feeds, "
    "voice recognition through Vosk, and speech synthesis through Edge-TTS. "
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
                            web_results: list[dict]) -> str:
    sections = []

    if memory_chunks:
        block = "\n\n".join(chunk.strip() for chunk in memory_chunks)
        sections.append(f"--- LOCAL KNOWLEDGE (OBSIDIAN VAULT) ---\n{block}")

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
})
_AUDIT_VERB = frozenset({
    "optimize", "optimise", "check", "scan",
    "diagnose", "analyse", "analyze", "clean", "audit",
    "detect", "identify", "report", "display", "show",
    "list", "find", "get", "tell", "give",
    "what", "which", "how",   # interrogatives: "what cpu do I have", "how much ram"
})
_AUDIT_NOUN = frozenset({
    "computer", "system", "pc", "rig", "machine", "hardware",
    "specs", "spec", "specifications", "components", "info",
    "vitals", "cpu", "gpu", "ram", "memory", "vram", "processor",
    "graphics card", "graphics", "storage", "drive", "ssd", "hdd",
})


def _is_audit_query(query: str) -> bool:
    """True when the user wants a hardware audit / system optimisation."""
    q = query.lower()
    if any(s in q for s in _AUDIT_EXACT):
        return True
    has_verb = any(s in q for s in _AUDIT_VERB)
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


def _handle_launch(query: str) -> str | None:
    """Return a confirmation string if query is a launch command, else None."""
    m = _LAUNCH_RE.match(query.strip())
    if not m:
        return None
    target = m.group(1).strip()
    exe    = _APP_MAP.get(target.lower(), target)
    try:
        if exe.endswith(".msc"):
            subprocess.Popen(["mmc", exe], shell=False)
        else:
            subprocess.Popen(exe, shell=True)
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
    # ── 0. Identity query — hardcoded, instant, no LLM call ─────────────────
    if _is_identity_query(query):
        return _IDENTITY_RESPONSE

    # ── 0a. Conversational bypass ────────────────────────────────────────────
    if _is_conversational(query):
        return _strip_markdown(direct_reply(query, history=history))

    # ── 0b. Tactical Hardware Audit — bypass Ollama, return SitRep directly ──
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

    # ── 0c. File count — resolve via pathlib, never via LLM ─────────────────
    _ext = _extract_file_ext(query)
    if _ext:
        return _count_files_by_ext(_ext)

    # ── 0d. Launch / open a program ──────────────────────────────────────────
    _launch_result = _handle_launch(query)
    if _launch_result is not None:
        return _launch_result

    # ── 0e. Kill a process ───────────────────────────────────────────────────
    _kill_result = _handle_kill_process(query)
    if _kill_result is not None:
        return _kill_result

    # ── 0f. Top processes list ───────────────────────────────────────────────
    _top_result = _handle_top_processes(query)
    if _top_result is not None:
        return _top_result

    # ── 0g. Disk / temp cleanup ──────────────────────────────────────────────
    _clean_result = _handle_disk_cleanup(query)
    if _clean_result is not None:
        return _clean_result

    # ── 0h. Overclocking / optimization — inject real hardware specs ─────────
    if _is_oc_query(query):
        return _strip_markdown(_run_oc_query(query))

    # ── 1. Hardware Verify protocol ──────────────────────────────────────────
    if is_hardware_query(query):
        print("[Albedo] Verify protocol engaged.")
        verify_data = run_verify(query)
        return _strip_markdown(bridge_chat(verify_data["synthesis_prompt"],
                                           history=history))

    # ── 2. Obsidian vault RAG + optional web search ──────────────────────────
    # Skip RAG for very short inputs — no useful embedding match and can
    # cause n_results=0 crashes in ChromaDB.
    memory_chunks = [] if len(query) < 5 else search_memory(query)
    web_results   = web_search(query) if use_web else []

    prompt = _build_standard_prompt(query, memory_chunks, web_results)
    return _strip_markdown(bridge_chat(prompt, history=history))
