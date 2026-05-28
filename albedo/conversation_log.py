"""
conversation_log.py — Lightweight JSONL conversation logger for Smart Brain mining.

Every substantive exchange (user query + Albedo response) is appended to a daily
JSONL log file. The brain_growth.py miner reads these logs during idle cycles to
extract knowledge, create Obsidian notes, and grow the vault.

Log location: <project_root>/logs/YYYY-MM-DD.jsonl
Format: one JSON object per line, {"role": "user"/"assistant", "content": "..."}
Pairs are always written together — user turn then assistant turn.

Import and use:
    from albedo.conversation_log import log_turn
    log_turn(user_query, assistant_response)
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

_LOG_DIR  = Path(__file__).resolve().parent.parent / "logs"
_LOCK     = threading.Lock()

# Don't log very short conversational exchanges — not worth mining
_MIN_RESPONSE_CHARS = 80


def log_turn(user: str, assistant: str) -> None:
    """
    Append a user+assistant turn pair to today's log file.
    Thread-safe. Silent on error — never crashes the main pipeline.
    """
    if not user or len(assistant) < _MIN_RESPONSE_CHARS:
        return

    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        today   = datetime.now().strftime("%Y-%m-%d")
        logfile = _LOG_DIR / f"{today}.jsonl"

        entry_user = json.dumps({"role": "user",      "content": user.strip()},
                                ensure_ascii=False)
        entry_asst = json.dumps({"role": "assistant", "content": assistant.strip()},
                                ensure_ascii=False)

        with _LOCK:
            with open(logfile, "a", encoding="utf-8") as f:
                f.write(entry_user + "\n")
                f.write(entry_asst + "\n")
    except Exception:
        pass   # Never crash the pipeline over logging
