"""
Wikipedia REST API — completely free, no key required.

Used to pull clean encyclopedic summaries as supplemental context for factual
queries that ChromaDB + web search may not cover precisely.

API docs: https://en.wikipedia.org/api/rest_v1/
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

_WIKI_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{}"
_WIKI_SEARCH_URL  = "https://en.wikipedia.org/w/api.php"

# Patterns that suggest an encyclopedic/factual query
_FACTUAL_RE = re.compile(
    r"""\b(?:
        what\s+is|what\s+was|what\s+are|what\s+were
        |who\s+is|who\s+was|who\s+were
        |tell\s+me\s+about|explain|describe|define|definition\s+of
        |history\s+of|overview\s+of|background\s+on
        |how\s+does|how\s+did|how\s+do
    )\b""",
    re.IGNORECASE | re.VERBOSE,
)

# Strip these question-stem words to isolate the topic
_STEM_RE = re.compile(
    r"""^(?:
        what\s+(?:is|was|are|were)\s+(?:a\s+|an\s+|the\s+)?
        |who\s+(?:is|was|were)\s+(?:a\s+|an\s+|the\s+)?
        |tell\s+me\s+about\s+(?:a\s+|an\s+|the\s+)?
        |(?:explain|describe|define)\s+(?:a\s+|an\s+|the\s+)?
        |(?:history|overview|background)\s+of\s+(?:a\s+|an\s+|the\s+)?
        |how\s+does\s+(?:a\s+|an\s+|the\s+)?
        |how\s+did\s+(?:a\s+|an\s+|the\s+)?
    )""",
    re.IGNORECASE | re.VERBOSE,
)


def is_wiki_candidate(query: str) -> bool:
    """Return True for queries that likely have a good Wikipedia article."""
    return bool(_FACTUAL_RE.search(query)) and len(query.strip()) > 15


def _extract_topic(query: str) -> str:
    """Strip question stems to get a clean topic string for Wikipedia lookup."""
    topic = _STEM_RE.sub("", query.strip(), count=1)
    return topic.rstrip("?.!").strip()


def _direct_summary(topic: str) -> str | None:
    """Try fetching the Wikipedia summary page directly by title."""
    try:
        encoded = urllib.parse.quote(topic.replace(" ", "_"))
        url = _WIKI_SUMMARY_URL.format(encoded)
        req = urllib.request.Request(url, headers={"User-Agent": "Albedo/1.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("type") == "disambiguation":
                    return None  # ambiguous — skip to search
                extract = data.get("extract", "").strip()
                if extract:
                    # Return first paragraph only to keep context concise
                    return extract.split("\n")[0]
    except Exception:
        pass
    return None


def _search_then_summary(topic: str) -> str | None:
    """Use the MediaWiki search API to find the best article, then fetch summary."""
    try:
        params = urllib.parse.urlencode({
            "action":   "query",
            "list":     "search",
            "srsearch": topic,
            "srlimit":  1,
            "format":   "json",
        })
        url = f"{_WIKI_SEARCH_URL}?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Albedo/1.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        hits = data.get("query", {}).get("search", [])
        if not hits:
            return None
        best_title = hits[0]["title"]
        return _direct_summary(best_title)
    except Exception as exc:
        print(f"[wikipedia] Search error: {exc}")
        return None


def wikipedia_summary(query: str) -> str | None:
    """Fetch a Wikipedia first-paragraph summary relevant to the query.

    Tries a direct title lookup first; falls back to the MediaWiki search API
    if the title doesn't resolve. Returns None on any failure.
    """
    topic = _extract_topic(query)
    if not topic or len(topic) < 3:
        return None

    result = _direct_summary(topic)
    if result:
        return result
    return _search_then_summary(topic)
