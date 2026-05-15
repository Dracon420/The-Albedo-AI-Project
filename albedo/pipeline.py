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

import re
from pathlib import Path

from albedo.rag.retriever import query_all
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

_GREETINGS = frozenset({
    "hello", "hi", "hey", "howdy", "sup", "yo",
    "thanks", "thank you", "ty", "thx", "cheers", "appreciate it",
    "ok", "okay", "got it", "understood", "sure", "alright", "sounds good",
    "yes", "no", "nope", "yep", "yeah", "yup",
    "bye", "goodbye", "cya", "later", "see you",
    "good morning", "good afternoon", "good evening", "good night",
    "how are you", "how are you doing", "how's it going", "hows it going",
    "what can you do", "who are you", "what are you",
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

def _build_standard_prompt(query: str, rag_results: dict,
                            web_results: list[dict]) -> str:
    sections = []

    for collection, chunks in rag_results.items():
        if not chunks:
            continue
        label = collection.replace("_", " ").title()
        block = "\n\n".join(
            f"({c['source']})\n{c['text'].strip()}" for c in chunks
        )
        sections.append(f"--- LOCAL {label.upper()} KNOWLEDGE ---\n{block}")

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
})
_AUDIT_VERB = frozenset({
    "optimize", "optimise", "check", "scan",
    "diagnose", "analyse", "analyze", "clean", "audit",
})
_AUDIT_NOUN = frozenset({
    "computer", "system", "pc", "rig", "machine", "hardware",
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
# STL file count interceptor
# Resolves the real count directly in Python — never lets the LLM guess CWD.
# ---------------------------------------------------------------------------

_STL_COUNT_SIGNALS = frozenset({
    "stl", ".stl", "3d print", "3d model", "3d file",
    "chaotic", "printing directory", "model file", "gcode",
})

_FILE_COUNT_SIGNALS = frozenset({
    "how many", "count", "number of", "total", "how much",
    "list", "show me", "find", "do i have",
})


def _is_stl_count_query(query: str) -> bool:
    """True when the user is asking for a file count in the 3D printing directory."""
    q = query.lower()
    has_stl   = any(s in q for s in _STL_COUNT_SIGNALS)
    has_count = any(s in q for s in _FILE_COUNT_SIGNALS)
    return has_stl and has_count


def _count_stl_files() -> tuple[int, str]:
    """
    Count .stl files under CHAOTIC_3D_PATH using pathlib.
    Returns (count, path_str). count is -1 if path is not configured.
    """
    from albedo.config import CHAOTIC_3D_PATH
    p = Path(CHAOTIC_3D_PATH)
    if not p.exists() or str(p) in ("", "."):
        return -1, str(p)
    count = sum(1 for _ in p.rglob("*.stl"))
    return count, str(p)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(query: str, use_web: bool = False,
        history: list[dict] | None = None) -> str:
    # ── 0. Conversational bypass ─────────────────────────────────────────────
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

    # ── 0c. STL file count — resolve in Python, present via direct_reply ─────
    if _is_stl_count_query(query):
        count, path = _count_stl_files()
        if count < 0:
            fact = (
                "The 3D Printing directory is not configured. "
                "Set CHAOTIC_3D_PATH in your .env file and re-index."
            )
        else:
            noun = "file" if count == 1 else "files"
            fact = f"Found {count} STL {noun} in your 3D Printing directory at {path}."
        return _strip_markdown(direct_reply(fact, history=history))

    # ── 1. Hardware Verify protocol ──────────────────────────────────────────
    if is_hardware_query(query):
        print("[Albedo] Verify protocol engaged.")
        verify_data = run_verify(query)
        return _strip_markdown(bridge_chat(verify_data["synthesis_prompt"],
                                           history=history))

    # ── 2. Standard RAG + optional web search ────────────────────────────────
    # Skip RAG for very short inputs — no useful embedding match and can
    # cause n_results=0 crashes in ChromaDB.
    rag_results = {} if len(query) < 5 else query_all(query)
    web_results = web_search(query) if use_web else []

    prompt = _build_standard_prompt(query, rag_results, web_results)
    return _strip_markdown(bridge_chat(prompt, history=history))
