from ddgs import DDGS
from albedo.config import WEB_SEARCH_MAX_RESULTS


def web_search(query: str, max_results: int = WEB_SEARCH_MAX_RESULTS) -> list[dict]:
    """Return DuckDuckGo results as [{title, url, snippet}]."""
    raw = DDGS().text(query, max_results=max_results)
    return [
        {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
        for r in (raw or [])
    ]


def format_web_results(results: list[dict]) -> str:
    if not results:
        return "No web results found."
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] {r['title']}\n    {r['url']}\n    {r['snippet']}")
    return "\n\n".join(lines)
