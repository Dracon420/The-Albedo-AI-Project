"""
Wolfram Alpha Short Answers API.

Free tier: 2,000 queries/month — no credit card required.
Sign up at: https://developer.wolframalpha.com/

Used for: math, unit conversions, physical constants, date calculations,
          and any query where a precise single-value answer beats LLM generation.
"""

from __future__ import annotations

import os
import re
import json
import urllib.parse
import urllib.request

_WOLFRAM_KEY = os.getenv("WOLFRAM_API_KEY", "").strip()

# Patterns that indicate a computation/conversion query
_COMPUTE_RE = re.compile(
    r"""(?x)
    \d+\s*[\+\-\*\/\^%]\s*\d+            # basic arithmetic: 5 * 12
    |(?:square\s+root|sqrt)\s+of\s+\d+   # square root of 144
    |\d+\s*factorial                       # 10 factorial
    |(?:how\s+many|convert|in\s+a)\s+\w+ # unit conversions
    |(?:integral|derivative)\s+of         # calculus
    |\b(?:integrate|differentiate|solve)\b
    |(?:what\s+is\s+(?:pi|e|phi|euler|avogadro|planck|speed\s+of\s+light))
    |(?:prime\s+(?:factors?|factori[sz]ation)|is\s+\d+\s+prime)
    |(?:\d+(?:\.\d+)?\s*(?:km|mi|miles?|kg|lbs?|oz|°?[CF]|celsius|fahrenheit
        |mph|kph|m\/s|hz|mhz|ghz|watts?|joules?|calories?|liters?|gallons?
        |inches?|feet|foot|yards?|meters?|cm|mm|nm)\b)
    |(?:how\s+(?:tall|heavy|far|long|old|fast|hot|cold)\s+is)
    |(?:\d{4}\s+(?:to|in)\s+\d{4})       # year ranges
    """,
    re.IGNORECASE,
)


def is_wolfram_query(query: str) -> bool:
    """Return True if the query looks like a computation or unit conversion.

    Only returns True when WOLFRAM_API_KEY is configured — if there's no key
    the caller should not bother dispatching to this module.
    """
    if not _WOLFRAM_KEY:
        return False
    return bool(_COMPUTE_RE.search(query))


def wolfram_short_answer(query: str) -> str | None:
    """Call Wolfram Alpha Short Answers API and return a plain-text answer.

    Returns None on failure, rate-limit, or when Wolfram cannot interpret
    the query (HTTP 501 "Wolfram|Alpha did not understand your input").
    """
    if not _WOLFRAM_KEY:
        return None
    try:
        params = urllib.parse.urlencode({
            "i":      query,
            "appid":  _WOLFRAM_KEY,
            "output": "plaintext",
        })
        url = f"https://api.wolframalpha.com/v1/result?{params}"
        req = urllib.request.Request(
            url, headers={"User-Agent": "Albedo/1.0"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                answer = resp.read().decode("utf-8").strip()
                # Reject meta-responses that contain Wolfram branding or are empty
                if answer and "Wolfram|Alpha" not in answer and len(answer) < 500:
                    return answer
    except urllib.error.HTTPError as exc:
        if exc.code != 501:  # 501 = "did not understand" — expected, not a bug
            print(f"[wolfram] HTTP {exc.code}: {exc.reason}")
    except Exception as exc:
        print(f"[wolfram] Error: {exc}")
    return None


def wolfram_full(query: str, max_pods: int = 3) -> str | None:
    """Call the Wolfram Alpha Full Results API and return top pod text.

    Useful when short answers fail but a richer result is needed.
    Requires the same WOLFRAM_API_KEY (same free quota).
    """
    if not _WOLFRAM_KEY:
        return None
    try:
        params = urllib.parse.urlencode({
            "input":         query,
            "appid":         _WOLFRAM_KEY,
            "format":        "plaintext",
            "output":        "JSON",
            "podstate":      "Step-by-step solution",
        })
        url = f"https://api.wolframalpha.com/v2/query?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Albedo/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        pods = data.get("queryresult", {}).get("pods", [])
        parts = []
        for pod in pods[:max_pods]:
            title = pod.get("title", "")
            for sub in pod.get("subpods", []):
                text = sub.get("plaintext", "").strip()
                if text:
                    parts.append(f"{title}: {text}" if title else text)
        return "\n".join(parts) if parts else None
    except Exception as exc:
        print(f"[wolfram_full] Error: {exc}")
        return None
