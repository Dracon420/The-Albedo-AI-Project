"""
email_conn.py — read / search / send email via IMAP + SMTP with an app password.

Works with Gmail (app password) and any IMAP/SMTP provider. No OAuth, stdlib only.
"""
from __future__ import annotations

import os

KEYS = [
    ("EMAIL_ADDRESS",      "Email address",                       "https://myaccount.google.com/apppasswords"),
    ("EMAIL_APP_PASSWORD", "Email app password",                  "https://myaccount.google.com/apppasswords"),
    ("EMAIL_IMAP_HOST",    "Email IMAP host (def imap.gmail.com)", ""),
    ("EMAIL_SMTP_HOST",    "Email SMTP host (def smtp.gmail.com)", ""),
]


def _creds():
    return (os.environ.get("EMAIL_ADDRESS", "").strip(),
            os.environ.get("EMAIL_APP_PASSWORD", "").strip())


def is_configured() -> bool:
    a, p = _creds()
    return bool(a and p)


def link():
    a, _ = _creds()
    return ("EMAIL", "ready", "READY", a) if is_configured() else ("EMAIL", "off", "OFF", "no account")


def _imap_host():
    return os.environ.get("EMAIL_IMAP_HOST", "").strip() or "imap.gmail.com"


def _smtp_host():
    return os.environ.get("EMAIL_SMTP_HOST", "").strip() or "smtp.gmail.com"


def _decode(raw) -> str:
    from email.header import decode_header
    if not raw:
        return ""
    parts = []
    for txt, enc in decode_header(raw):
        if isinstance(txt, bytes):
            try:
                parts.append(txt.decode(enc or "utf-8", "ignore"))
            except Exception:
                parts.append(txt.decode("utf-8", "ignore"))
        else:
            parts.append(txt)
    return "".join(parts).strip()


def _headers(crit: str, n: int) -> str:
    if not is_configured():
        return "[tool error] Email not configured (set EMAIL_ADDRESS + app password in Settings)."
    import imaplib
    import email as _email
    a, p = _creds()
    try:
        M = imaplib.IMAP4_SSL(_imap_host())
        M.login(a, p)
        M.select("INBOX")
        typ, data = M.search(None, crit)
        ids = data[0].split()[-int(n):][::-1] if data and data[0] else []
        out = []
        for i in ids:
            typ, msgdata = M.fetch(i, "(BODY.PEEK[HEADER])")
            if not msgdata or not msgdata[0]:
                continue
            msg = _email.message_from_bytes(msgdata[0][1])
            out.append(f"- {_decode(msg.get('From',''))[:48]} | {_decode(msg.get('Subject','(no subject)'))[:70]}")
        M.logout()
        return ("\n".join(out)) if out else "(none)"
    except Exception as exc:                                        # noqa: BLE001
        return f"[tool error] email read failed: {exc}"


def read_inbox(n: int = 5) -> str:
    body = _headers("ALL", min(int(n or 5), 20))
    return body if body.startswith("[tool error]") else "Latest inbox:\n" + body


def search_email(query: str, n: int = 10) -> str:
    q = (query or "").strip()
    if not q:
        return "[tool error] need a search query."
    body = _headers(f'(OR SUBJECT "{q}" FROM "{q}")', min(int(n or 10), 25))
    return body if body.startswith("[tool error]") else f"Emails matching '{q}':\n" + body


def send_email(to: str, subject: str, body: str) -> str:
    if not is_configured():
        return "[tool error] Email not configured (set EMAIL_ADDRESS + app password in Settings)."
    import smtplib
    from email.mime.text import MIMEText
    a, p = _creds()
    try:
        msg = MIMEText(body or "", "plain", "utf-8")
        msg["Subject"] = subject or "(no subject)"
        msg["From"] = a
        msg["To"] = to
        with smtplib.SMTP_SSL(_smtp_host(), 465, timeout=20) as s:
            s.login(a, p)
            s.sendmail(a, [x.strip() for x in to.split(",") if x.strip()], msg.as_string())
        return f"Email sent to {to}."
    except Exception as exc:                                        # noqa: BLE001
        return f"[tool error] send failed: {exc}"
