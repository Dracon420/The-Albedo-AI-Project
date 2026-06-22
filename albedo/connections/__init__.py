"""
connections — external integrations (email, calendar, Home Assistant, messaging).

Each submodule declares:
  KEYS            : list of (ENV_VAR, label, help_url) for the keys panel
  is_configured() : bool
  link()          : (name, status, label, detail) for the neural-links HUD

The registry aggregates them so bridge.py can auto-feed _API_KEY_SPECS and
_detect_neural_links — adding a new connection is one module, not edits in 4 files.
"""
from __future__ import annotations

from . import email_conn, calendar_conn, home_assistant, messaging

_MODULES = [email_conn, calendar_conn, home_assistant, messaging]


def key_specs() -> list:
    out: list = []
    for m in _MODULES:
        out += list(getattr(m, "KEYS", []))
    return out


def links() -> list:
    """List of (name, status, label, detail) for each connection."""
    out = []
    for m in _MODULES:
        try:
            out.append(m.link())
        except Exception:
            pass
    return out
