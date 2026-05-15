"""
operative_dream.py  --  Albedo Dream Operative

Background memory-consolidation agent (REM cycle).

Reads the daily interaction traces written by telemetry.py, sends them to
the local Ollama model (with Groq as fallback) for subconscious reflection,
and appends the generated Markdown insight report to the Obsidian vault.
The trace log is then cleared so the next day starts fresh.

Public API
----------
initiate_rem_cycle()  -- run one full dream consolidation pass
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRACE_LOG   = Path(__file__).parent / "logs" / "daily_traces.json"
VAULT_DIR   = Path(r"C:\Users\demon\Desktop\Albedo Project Brain\Core Directives")
INSIGHT_FILE = VAULT_DIR / "Albedo_Daily_Insights.md"

_DREAM_PROMPT = (
    "You are Albedo's subconscious. Review these daily interaction traces. "
    "Summarize the user's current goals, hardware preferences, and any "
    "recurring errors. Output a clean Markdown summary."
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_traces() -> list[dict]:
    """Return the trace list from disk, or [] if absent / corrupt."""
    if not TRACE_LOG.exists():
        return []
    try:
        data = json.loads(TRACE_LOG.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _traces_to_text(traces: list[dict]) -> str:
    lines = []
    for t in traces:
        ts      = t.get("timestamp", "?")
        query   = t.get("query",   "?")
        route   = t.get("route",   "?")
        success = "OK" if t.get("success", False) else "FAIL"
        lines.append(f"[{ts}] route={route} status={success} | {query}")
    return "\n".join(lines)


def _ask_ollama(prompt: str) -> str:
    """Query the local Ollama model synchronously via CLI."""
    result = subprocess.run(
        ["ollama", "run", "llama3", prompt],
        capture_output=True,
        text=True,
        timeout=120,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    raise RuntimeError(result.stderr.strip() or "Ollama returned no output")


def _ask_groq(prompt: str) -> str:
    """Groq fallback — used when Ollama is unavailable."""
    from swarm import query_groq
    response = query_groq(prompt)
    if response.startswith("[swarm]"):
        raise RuntimeError(response)
    return response


def _generate_summary(traces: list[dict]) -> str:
    trace_text = _traces_to_text(traces)
    full_prompt = f"{_DREAM_PROMPT}\n\n---\n{trace_text}\n---"
    try:
        return _ask_ollama(full_prompt)
    except Exception as ollama_exc:
        print(f"[dream] Ollama unavailable ({ollama_exc}), trying Groq fallback.")
        return _ask_groq(full_prompt)


def _append_to_vault(summary: str) -> None:
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    date_stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    block = (
        f"\n\n---\n\n"
        f"## Dream Cycle — {date_stamp}\n\n"
        f"{summary}\n"
    )
    with INSIGHT_FILE.open("a", encoding="utf-8") as fh:
        fh.write(block)


def _clear_traces() -> None:
    try:
        TRACE_LOG.write_text("[]", encoding="utf-8")
    except OSError as exc:
        print(f"[dream] Could not clear trace log: {exc}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def initiate_rem_cycle() -> str:
    """
    Run one full REM consolidation pass.

    Returns a human-readable status string describing the outcome.
    Never raises — all errors are caught and returned as status messages.
    """
    traces = _read_traces()
    if not traces:
        return "[dream] No traces to consolidate — trace log is empty."

    try:
        summary = _generate_summary(traces)
    except Exception as exc:
        return f"[dream] Summary generation failed: {exc}"

    try:
        _append_to_vault(summary)
    except Exception as exc:
        return f"[dream] Vault write failed: {exc}"

    _clear_traces()

    date_stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return (
        f"[dream] REM cycle complete for {date_stamp}. "
        f"{len(traces)} traces consolidated → {INSIGHT_FILE}"
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(initiate_rem_cycle())
