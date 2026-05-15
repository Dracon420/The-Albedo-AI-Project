"""
telemetry.py  --  Albedo Trace Logger

Appends a JSON trace record to logs/daily_traces.json for every routed
interaction.  The logs/ directory is created automatically on first write.

Public API
----------
log_trace(query, route, success)  -- append one trace record
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

LOGS_DIR  = Path(__file__).parent / "logs"
TRACE_LOG = LOGS_DIR / "daily_traces.json"


def log_trace(query: str, route: str, success: bool) -> None:
    """
    Append a single interaction trace to logs/daily_traces.json.

    The file holds a JSON array; individual records are appended by reading
    the existing array, appending the new record, and rewriting the file.
    Safe to call from any thread — writes are serialised by the GIL on the
    json.dumps call and the final atomic write.
    """
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query":     query,
        "route":     route,
        "success":   success,
    }

    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

        if TRACE_LOG.exists():
            try:
                existing = json.loads(TRACE_LOG.read_text(encoding="utf-8"))
                if not isinstance(existing, list):
                    existing = []
            except (json.JSONDecodeError, OSError):
                existing = []
        else:
            existing = []

        existing.append(record)
        TRACE_LOG.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        # Telemetry must never crash the main process.
        print(f"[telemetry] Trace write failed: {exc}")
