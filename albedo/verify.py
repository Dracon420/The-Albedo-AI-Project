"""
Verify Protocol — cross-references Obsidian vault knowledge with live web data
before delivering any hardware diagnosis. Triggered automatically when a query
contains hardware-related keywords.
"""

from albedo.config import HARDWARE_KEYWORDS
from memory import search_memory
from albedo.web.search import web_search, format_web_results


def is_hardware_query(query: str) -> bool:
    lower = query.lower()
    return any(kw in lower for kw in HARDWARE_KEYWORDS)


def _format_local_context(chunks: list[str]) -> str:
    if not chunks:
        return "No relevant knowledge found in local vault."
    return "\n\n".join(f"[Local {i}]\n{c.strip()}" for i, c in enumerate(chunks, 1))


def run_verify(query: str) -> dict:
    """
    Returns a dict with:
      - local_context: str  (Obsidian vault RAG results)
      - web_context:   str  (DuckDuckGo results)
      - synthesis_prompt: str  (ready-to-send prompt for the LLM)
    """
    local_chunks = search_memory(query)
    web_results = web_search(query)

    local_context = _format_local_context(local_chunks)
    web_context = format_web_results(web_results)

    synthesis_prompt = f"""[VERIFY PROTOCOL ACTIVE]

You are diagnosing a hardware issue. You MUST cross-reference both sources below before
answering. Do not speculate beyond what these sources support.

--- LOCAL KNOWLEDGE (OBSIDIAN VAULT) ---
{local_context}

--- LIVE WEB DATA ---
{web_context}

--- USER QUERY ---
{query}

Synthesize both sources. If they conflict, state the conflict explicitly.
Flag any hardware state that requires immediate attention.
"""

    return {
        "local_context": local_context,
        "web_context": web_context,
        "synthesis_prompt": synthesis_prompt,
    }
