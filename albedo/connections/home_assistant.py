"""
home_assistant.py — read entity states and call services via the HA REST API.
"""
from __future__ import annotations

import os

KEYS = [
    ("HA_BASE_URL", "Home Assistant URL (e.g. http://homeassistant.local:8123)",
     "https://www.home-assistant.io/"),
    ("HA_TOKEN", "Home Assistant long-lived token",
     "https://www.home-assistant.io/docs/authentication/#your-account-profile"),
]


def _cfg():
    return (os.environ.get("HA_BASE_URL", "").strip().rstrip("/"),
            os.environ.get("HA_TOKEN", "").strip())


def is_configured() -> bool:
    u, t = _cfg()
    return bool(u and t)


def link():
    u, _ = _cfg()
    return ("HOME_ASST", "ready", "READY", u) if is_configured() else ("HOME_ASST", "off", "OFF", "not set")


def _headers():
    _, t = _cfg()
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


def list_states(domain: str = "") -> str:
    if not is_configured():
        return "[tool error] Home Assistant not configured (set HA_BASE_URL + HA_TOKEN in Settings)."
    import httpx
    u, _ = _cfg()
    try:
        r = httpx.get(u + "/api/states", headers=_headers(), timeout=15)
        r.raise_for_status()
        items = r.json()
        d = (domain or "").strip().rstrip(".")
        if d:
            items = [e for e in items if str(e.get("entity_id", "")).startswith(d + ".")]
        items = items[:40]
        lines = [f"- {e['entity_id']}: {e.get('state','')}" for e in items]
        return "Home Assistant:\n" + "\n".join(lines) if lines else "No matching entities."
    except Exception as exc:                                        # noqa: BLE001
        return f"[tool error] HA states failed: {exc}"


def call_service(domain: str, service: str, entity_id: str) -> str:
    if not is_configured():
        return "[tool error] Home Assistant not configured (set HA_BASE_URL + HA_TOKEN in Settings)."
    import httpx
    u, _ = _cfg()
    try:
        r = httpx.post(f"{u}/api/services/{domain}/{service}", headers=_headers(),
                       json={"entity_id": entity_id}, timeout=15)
        r.raise_for_status()
        return f"Called {domain}.{service} on {entity_id}."
    except Exception as exc:                                        # noqa: BLE001
        return f"[tool error] HA service failed: {exc}"
