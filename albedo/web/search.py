"""
Web search backend.

Priority:
  1. Tavily (if TAVILY_API_KEY set) — structured, AI-optimised results, 1000/month free
  2. DuckDuckGo (ddgs) — unofficial, no key required, used as fallback

Get a free Tavily key at: https://app.tavily.com
"""

from __future__ import annotations

import os

from albedo.config import WEB_SEARCH_MAX_RESULTS

# Read at import time; changing the env var at runtime won't re-read.
_TAVILY_KEY = os.getenv("TAVILY_API_KEY", "").strip()


def _tavily_search(query: str, max_results: int) -> list[dict]:
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=_TAVILY_KEY)
        resp = client.search(query, max_results=max_results, search_depth="basic")
        return [
            {
                "title":   r.get("title", ""),
                "url":     r.get("url", ""),
                "snippet": r.get("content", ""),
            }
            for r in resp.get("results", [])
        ]
    except Exception as exc:
        print(f"[web_search] Tavily error (falling back to DDG): {exc}")
        return []


def _ddg_search(query: str, max_results: int) -> list[dict]:
    try:
        from ddgs import DDGS
        raw = DDGS().text(query, max_results=max_results)
        return [
            {
                "title":   r.get("title", ""),
                "url":     r.get("href", ""),
                "snippet": r.get("body", ""),
            }
            for r in (raw or [])
        ]
    except Exception as exc:
        print(f"[web_search] DDG error (returning empty results): {exc}")
        return []


def web_search(query: str, max_results: int = WEB_SEARCH_MAX_RESULTS) -> list[dict]:
    """Return search results as [{title, url, snippet}].

    Uses Tavily when TAVILY_API_KEY is set; falls back to DuckDuckGo otherwise.
    Returns an empty list on failure rather than propagating exceptions.
    """
    if _TAVILY_KEY:
        results = _tavily_search(query, max_results)
        if results:
            return results
    return _ddg_search(query, max_results)


def format_web_results(results: list[dict]) -> str:
    if not results:
        return "No web results found."
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] {r['title']}\n    {r['url']}\n    {r['snippet']}")
    return "\n\n".join(lines)
