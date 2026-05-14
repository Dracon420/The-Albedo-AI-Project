"""
Verify Protocol — cross-references local Exotic OS telemetry with live web data
before delivering any hardware diagnosis. Triggered automatically when a query
contains hardware-related keywords (defined in config.HARDWARE_KEYWORDS).
"""

from albedo.config import HARDWARE_KEYWORDS
from albedo.rag.retriever import query_exotic_os
from albedo.web.search import web_search, format_web_results


def is_hardware_query(query: str) -> bool:
    lower = query.lower()
    return any(kw in lower for kw in HARDWARE_KEYWORDS)


def _format_local_context(chunks: list[dict]) -> str:
    if not chunks:
        return "No relevant Exotic OS telemetry found in local index."
    lines = []
    for i, c in enumerate(chunks, 1):
        source = c.get("source", "unknown")
        lines.append(f"[Local {i}] ({source})\n{c['text'].strip()}")
    return "\n\n".join(lines)


def run_verify(query: str) -> dict:
    """
    Returns a dict with:
      - local_context: str  (Exotic OS RAG results)
      - web_context:   str  (DuckDuckGo results)
      - synthesis_prompt: str  (ready-to-send prompt for the LLM)
    """
    local_chunks = query_exotic_os(query)
    web_results = web_search(query)

    local_context = _format_local_context(local_chunks)
    web_context = format_web_results(web_results)

    synthesis_prompt = f"""[VERIFY PROTOCOL ACTIVE]

You are diagnosing a hardware issue. You MUST cross-reference both sources below before
answering. Do not speculate beyond what these sources support.

--- LOCAL EXOTIC OS TELEMETRY ---
{local_context}

--- LIVE WEB DATA ---
{web_context}

--- USER QUERY ---
{query}

Synthesize both sources. If they conflict, state the conflict explicitly. If local telemetry
confirms a pattern also documented online, say so. Flag any hardware state that requires
immediate attention.
"""

    return {
        "local_context": local_context,
        "web_context": web_context,
        "synthesis_prompt": synthesis_prompt,
    }
