"""
mobile_relay.py — Albedo ↔ Phone App relay client.

Connects Albedo to the Fly.io relay server via a persistent WebSocket.
Handles incoming commands from the phone app and pushes responses and
notifications back.

Public API
----------
    start()                   — connect to relay in background thread (idempotent)
    stop()                    — disconnect cleanly
    push(payload: dict)       — send a push message to all connected phones
    is_connected() -> bool    — is the relay WebSocket currently open?
    get_token() -> str        — current pairing token (or "" if not paired)
    get_relay_url() -> str    — wss:// URL currently in use
    pair(relay_host: str)     — register with relay, save token to settings.json

Message protocol (JSON)
-----------------------
Phone → Albedo:
    {"type": "query",   "text": "...", "id": "uuid"}
    {"type": "stop_tts", "id": "uuid"}
    {"type": "status",  "id": "uuid"}

Albedo → Phone:
    {"type": "response",      "text": "...", "id": "uuid"}
    {"type": "push",          "title": "Albedo", "body": "..."}
    {"type": "status",        "persona": "CORTANA", "uptime": 3600, "online": true}
    {"type": "albedo_status", "online": true}   (relay-injected, not us)
    {"type": "error",         "text": "...", "id": "uuid"}
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_ROOT         = Path(__file__).resolve().parent.parent
_SETTINGS     = _ROOT / "settings.json"
_DEFAULT_HOST = "albedo-relay.fly.dev"

_RECONNECT_DELAY  = 5    # seconds between reconnect attempts
_PING_INTERVAL    = 25   # keep-alive ping (relay closes idle WS at 60s)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_ws          = None          # websockets.ClientConnection | None
_ws_lock     = threading.Lock()
_stop_event  = threading.Event()
_thread: threading.Thread | None = None
_connected   = False


def is_connected() -> bool:
    return _connected


def get_token() -> str:
    s = _load_settings()
    return s.get("mobile_token", "")


def get_relay_url() -> str:
    s = _load_settings()
    host = s.get("relay_host", _DEFAULT_HOST)
    return f"wss://{host}/ws"


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------

def _load_settings() -> dict:
    try:
        return json.loads(_SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_settings(data: dict) -> None:
    try:
        _SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"[mobile_relay] settings write failed: {exc}")


# ---------------------------------------------------------------------------
# Pairing — call once from Mission Control to get/refresh the token
# ---------------------------------------------------------------------------

def pair(relay_host: str = _DEFAULT_HOST) -> dict:
    """
    Register with the relay server. Returns {"token": "...", "relay_url": "wss://..."}.
    Saves token + relay_host to settings.json.
    """
    import urllib.request, urllib.error

    settings = _load_settings()
    existing_token = settings.get("mobile_token", "")

    url  = f"https://{relay_host}/pair"
    body = json.dumps({"token": existing_token}).encode()

    try:
        req  = urllib.request.Request(url, data=body,
                                      headers={"Content-Type": "application/json"},
                                      method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
    except urllib.error.URLError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    token = result.get("token", "")
    if token:
        settings["mobile_token"] = token
        settings["relay_host"]   = relay_host
        _save_settings(settings)
        print(f"[mobile_relay] paired: token={token[:8]}... relay={relay_host}")

    return {"ok": True, "token": token, "relay_url": result.get("relay_url", "")}


# ---------------------------------------------------------------------------
# Push — send a message to all connected phones
# ---------------------------------------------------------------------------

def push(payload: dict) -> None:
    """
    Send a JSON payload to all connected phones via the relay.
    Safe to call from any thread. No-op if not connected.

    NOTE: websockets.sync.client is thread-safe for concurrent send + recv,
    so calling ws.send() here while _relay_loop() iterates ws is fine.
    The previous asyncio wrapper was wrong — ws.send() is synchronous and
    returns None (not a coroutine), so run_until_complete(None) always raised
    ValueError and silently dropped every outbound message.
    """
    with _ws_lock:
        ws = _ws
    if ws is None:
        return
    try:
        ws.send(json.dumps(payload))
    except Exception as exc:
        print(f"[mobile_relay] push failed: {exc}")


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _handle_query(msg: dict) -> None:
    """Run the Albedo pipeline and push response back to phone."""
    text    = msg.get("text", "").strip()
    msg_id  = msg.get("id", "")
    if not text:
        return

    def _run():
        try:
            from albedo.pipeline import run as pipeline_run
            reply = pipeline_run(text) or ""
        except Exception as exc:
            reply = f"[error] {exc}"

        # Push text response to phone first (fast path — shows in chat immediately)
        push({"type": "response", "text": reply, "id": msg_id})

        # Also speak on desktop so local TTS still fires
        # (non-blocking, fire-and-forget — don't block relay receive loop)
        try:
            from albedo.audio.tts import speak as _speak
            threading.Thread(target=_speak, args=(reply,),
                             daemon=True, name="mobile-tts").start()
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True, name="mobile-query").start()


def _handle_stop_tts(msg: dict) -> None:
    try:
        from albedo.audio.tts import stop_audio
        stop_audio()
    except Exception:
        pass
    push({"type": "ack", "id": msg.get("id", "")})


def _handle_status(msg: dict) -> None:
    try:
        from albedo.eel_app.bridge import get_active_persona_name
        persona = get_active_persona_name().get("name", "ALBEDO")
    except Exception:
        persona = "ALBEDO"

    push({
        "type":    "status",
        "persona": persona,
        "online":  True,
        "id":      msg.get("id", ""),
    })


_HANDLERS = {
    "query":    _handle_query,
    "stop_tts": _handle_stop_tts,
    "status":   _handle_status,
}


def _dispatch(raw: str) -> None:
    try:
        msg = json.loads(raw)
    except Exception:
        return
    kind = msg.get("type", "")
    handler = _HANDLERS.get(kind)
    if handler:
        try:
            handler(msg)
        except Exception as exc:
            print(f"[mobile_relay] handler error ({kind}): {exc}")
    else:
        print(f"[mobile_relay] unknown message type: {kind!r}")


# ---------------------------------------------------------------------------
# WebSocket loop — runs in a background thread
# ---------------------------------------------------------------------------

def _relay_loop() -> None:
    global _ws, _connected

    while not _stop_event.is_set():
        token = get_token()
        if not token:
            print("[mobile_relay] no token — call pair() from Mission Control first.")
            _stop_event.wait(timeout=30)
            continue

        settings    = _load_settings()
        relay_host  = settings.get("relay_host", _DEFAULT_HOST)
        ws_url      = f"wss://{relay_host}/ws/albedo/{token}"

        print(f"[mobile_relay] connecting to {ws_url[:40]}...")
        try:
            import websockets.sync.client as _wsc

            with _wsc.connect(ws_url, ping_interval=_PING_INTERVAL) as ws:
                with _ws_lock:
                    _ws = ws
                _connected = True
                print("[mobile_relay] connected.")

                for raw in ws:
                    if _stop_event.is_set():
                        break
                    if isinstance(raw, str):
                        _dispatch(raw)

        except Exception as exc:
            print(f"[mobile_relay] disconnected: {exc}")
        finally:
            with _ws_lock:
                _ws = None
            _connected = False

        if not _stop_event.is_set():
            print(f"[mobile_relay] reconnecting in {_RECONNECT_DELAY}s...")
            _stop_event.wait(timeout=_RECONNECT_DELAY)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def start() -> None:
    """Start the relay background thread. Safe to call multiple times."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_relay_loop, daemon=True, name="mobile-relay")
    _thread.start()
    print("[mobile_relay] background thread started.")


def stop() -> None:
    """Disconnect and stop the background thread."""
    _stop_event.set()
    with _ws_lock:
        ws = _ws
    if ws:
        try:
            ws.close()
        except Exception:
            pass
    if _thread:
        _thread.join(timeout=5)
    print("[mobile_relay] stopped.")
