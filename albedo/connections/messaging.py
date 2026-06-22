"""
messaging.py — send messages to Discord / Slack via incoming webhooks.
"""
from __future__ import annotations

import os

KEYS = [
    ("DISCORD_WEBHOOK_URL", "Discord webhook URL",
     "https://support.discord.com/hc/en-us/articles/228383668"),
    ("SLACK_WEBHOOK_URL", "Slack webhook URL",
     "https://api.slack.com/messaging/webhooks"),
]


def _discord():
    return os.environ.get("DISCORD_WEBHOOK_URL", "").strip()


def _slack():
    return os.environ.get("SLACK_WEBHOOK_URL", "").strip()


def is_configured() -> bool:
    return bool(_discord() or _slack())


def link():
    which = []
    if _discord():
        which.append("Discord")
    if _slack():
        which.append("Slack")
    return ("MESSAGING", "ready", "READY", ", ".join(which)) if which else ("MESSAGING", "off", "OFF", "no webhook")


def send_message(text: str, target: str = "") -> str:
    t = (target or "").lower()
    use_slack = "slack" in t or (not _discord() and _slack())
    url = _slack() if use_slack else _discord()
    if not url:
        return "[tool error] No messaging webhook configured (set a Discord or Slack webhook in Settings)."
    import httpx
    payload = {"text": text} if use_slack else {"content": text}
    try:
        r = httpx.post(url, json=payload, timeout=15)
        r.raise_for_status()
        return f"Message sent to {'Slack' if use_slack else 'Discord'}."
    except Exception as exc:                                        # noqa: BLE001
        return f"[tool error] message send failed: {exc}"
