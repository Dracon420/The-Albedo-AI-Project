"""
reminders.py — scheduled reminders that fire a Windows notification.

A daemon thread polls due reminders and fires a toast (dependency-free, via the
WinRT API through PowerShell) plus a `reminder.fired` event so the UI can surface
it. Reminders persist to install-root/reminders.json and re-arm on boot.

Public API: start(), add(text, when), active(), all_items(), cancel(ids)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

_STORE = Path(__file__).resolve().parent.parent / "reminders.json"
_lock = threading.Lock()
_reminders: list[dict] = []
_started = False

_CREATE_NO_WINDOW = 0x08000000


def _load() -> None:
    global _reminders
    try:
        _reminders = json.loads(_STORE.read_text(encoding="utf-8")) if _STORE.exists() else []
    except Exception:
        _reminders = []


def _save() -> None:
    try:
        _STORE.write_text(json.dumps(_reminders, indent=2), encoding="utf-8")
    except Exception:
        pass


# Dependency-free Windows toast through the WinRT ToastNotificationManager. Title
# and body are passed via env vars so quoting can't break the script.
_TOAST_PS = (
    "$ErrorActionPreference='SilentlyContinue';"
    "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null;"
    "$x=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
    "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
    "$t=$x.GetElementsByTagName('text');"
    "$t.Item(0).AppendChild($x.CreateTextNode($env:ALB_TITLE))|Out-Null;"
    "$t.Item(1).AppendChild($x.CreateTextNode($env:ALB_BODY))|Out-Null;"
    "$n=[Windows.UI.Notifications.ToastNotification]::new($x);"
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Albedo').Show($n)"
)


def _os_toast(title: str, body: str) -> None:
    try:
        env = dict(os.environ, ALB_TITLE=title, ALB_BODY=body)
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", _TOAST_PS],
            env=env, creationflags=_CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _notify(rem: dict) -> None:
    _os_toast("Albedo Reminder", rem.get("text", ""))
    try:
        from albedo import event_bus
        event_bus.publish("reminder.fired", text=rem.get("text", ""), id=rem.get("id", ""))
    except Exception:
        pass


def _loop() -> None:
    while True:
        try:
            now = time.time()
            due = []
            with _lock:
                for r in _reminders:
                    if not r.get("fired") and r.get("fire_ts", 0) <= now:
                        r["fired"] = True
                        due.append(dict(r))
                if due:
                    _save()
            for r in due:
                _notify(r)
        except Exception:
            pass
        time.sleep(5)


def start() -> None:
    global _started
    if _started:
        return
    _started = True
    _load()
    threading.Thread(target=_loop, daemon=True, name="reminders").start()


# ── "when" parsing: "in 20 minutes", "in 2 hours", "at 3pm", "tomorrow at 9" ──
_REL = re.compile(r"in\s+(\d+)\s*(sec|second|min|minute|hr|hour|day)s?", re.I)
_AT = re.compile(r"at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.I)
_UNIT = {"sec": 1, "second": 1, "min": 60, "minute": 60, "hr": 3600, "hour": 3600, "day": 86400}


def parse_when(s: str):
    """Return (epoch_ts, human_string) or (None, None)."""
    s = (s or "").strip().lower()
    now = datetime.now()
    m = _REL.search(s)
    if m:
        t = now + timedelta(seconds=int(m.group(1)) * _UNIT[m.group(2)])
        return t.timestamp(), t.strftime("%a %H:%M")
    m = _AT.search(s)
    if m:
        h, mn, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        t = now.replace(hour=h % 24, minute=mn, second=0, microsecond=0)
        if "tomorrow" in s or t <= now:
            t += timedelta(days=1)
        return t.timestamp(), t.strftime("%a %H:%M")
    return None, None


def add(text: str, when: str):
    ts, human = parse_when(when)
    if ts is None:
        return None
    rem = {"id": uuid.uuid4().hex[:8], "text": (text or "").strip(),
           "fire_ts": ts, "when_human": human, "created_ts": time.time(), "fired": False}
    with _lock:
        _reminders.append(rem)
        _save()
    if not _started:
        start()
    return rem


def active() -> list[dict]:
    with _lock:
        return [dict(r) for r in _reminders if not r.get("fired")]


def all_items() -> list[dict]:
    with _lock:
        return [dict(r) for r in _reminders]


def cancel(ids) -> int:
    wanted = set(ids or [])
    removed = 0
    with _lock:
        global _reminders
        keep = []
        for r in _reminders:
            if r["id"] in wanted or r["text"] in wanted:
                removed += 1
            else:
                keep.append(r)
        _reminders = keep
        _save()
    return removed
