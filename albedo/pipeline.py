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
# Public entry point
# ---------------------------------------------------------------------------

def run(query: str, use_web: bool = False,
        history: list[dict] | None = None) -> str:
    # ── 0. Conversational bypass ─────────────────────────────────────────────
    if _is_conversational(query):
        return _strip_markdown(direct_reply(query, history=history))

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
