"""
calendar_conn.py — read upcoming events from a calendar ICS feed (read-only).

Google Calendar / Outlook both expose a secret ICS URL. Creating events needs
OAuth (a later drop-in); this v1 answers "what's on my schedule?".
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta

KEYS = [
    ("CALENDAR_ICS_URL", "Calendar ICS feed URL (read-only)",
     "https://support.google.com/calendar/answer/37648"),
]


def _url():
    return os.environ.get("CALENDAR_ICS_URL", "").strip()


def is_configured() -> bool:
    return bool(_url())


def link():
    return ("CALENDAR", "ready", "READY", "ICS feed") if is_configured() else ("CALENDAR", "off", "OFF", "no ICS url")


def _parse_dt(val: str):
    """Parse an ICS DTSTART value (YYYYMMDD or YYYYMMDDTHHMMSS[Z])."""
    v = val.strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(v, fmt)
        except Exception:
            continue
    return None


def upcoming(days: int = 7) -> str:
    if not is_configured():
        return "[tool error] No calendar configured (set CALENDAR_ICS_URL in Settings)."
    try:
        import httpx
        text = httpx.get(_url(), timeout=20, follow_redirects=True).text
    except Exception as exc:                                        # noqa: BLE001
        return f"[tool error] calendar fetch failed: {exc}"
    now = datetime.now()
    horizon = now + timedelta(days=int(days or 7))
    events = []
    for block in text.split("BEGIN:VEVENT")[1:]:
        sm = re.search(r"\nSUMMARY:(.*)", block)
        dm = re.search(r"\nDTSTART[^:]*:(.*)", block)
        if not sm or not dm:
            continue
        dt = _parse_dt(dm.group(1).strip())
        if not dt:
            continue
        if now.date() <= dt.date() <= horizon.date():
            events.append((dt, sm.group(1).strip()))
    events.sort(key=lambda e: e[0])
    if not events:
        return f"Nothing on the calendar in the next {days} day(s)."
    lines = [f"- {dt.strftime('%a %d %b %H:%M')}: {sumr}" for dt, sumr in events[:25]]
    return f"Upcoming ({days}d):\n" + "\n".join(lines)
