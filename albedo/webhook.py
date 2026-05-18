"""
webhook.py — remote command uplink for Albedo.

A lightweight FastAPI service that runs in a background thread and lets
external callers (a mobile app over Tailscale, a home-automation hub, a
push notification handler, etc.) push commands into the running Albedo
instance. The forthcoming Eel UI consumes those commands by calling
``pop_pending_updates()`` from its render loop.

Security defaults — these are intentional, please don't loosen them
without thinking:

  - Binds to 127.0.0.1 ONLY by default. To expose on LAN/Tailscale,
    set environment variable ``ALBEDO_WEBHOOK_HOST=0.0.0.0`` (or a
    specific interface). Loopback-only means a process on this machine
    is the only one that can talk to it without further config.

  - Every request must carry header ``X-Albedo-Secret`` matching the
    shared secret. The secret is read from ``ALBEDO_WEBHOOK_SECRET``;
    if unset, a 32-byte random secret is generated on first start
    and written to ``.webhook_secret`` next to the install root.
    The .webhook_secret file is gitignored.

  - Missing or wrong secret → HTTP 401 immediately, no helpful error.

  - Any command the webhook tries to execute MUST go through
    ``safety_catch.safe_run`` so the user still sees an approval prompt
    in the UI (defense in depth — a leaked secret alone can't run code).

Endpoints
---------
    GET  /webhook/health             liveness + version snapshot
    POST /webhook/command            queue a command for the UI to consume
    GET  /webhook/secret             returns the active secret (loopback only,
                                     refuses 401 if request didn't come from
                                     127.0.0.1 — used by self-tests + tools)

Public API
----------
    start(host=None, port=5000) -> str
        Spin up the server in a daemon thread. Returns the binding URL.
        Idempotent — second call is a no-op and returns the same URL.

    stop() -> None
        Gracefully shut down the uvicorn instance.

    is_running() -> bool

    pop_pending_updates() -> list[dict]
        Drain and return the queue of accepted webhook commands. The UI
        renders these and acts on them through its own approval flow.

    push_update(payload: dict) -> None
        Manually enqueue an update (used by /webhook/command and by tests).

    current_secret() -> str
        The shared secret currently in use, materialising one if needed.

    secret_path() -> Path
        Where the auto-generated secret lives on disk.
"""
from __future__ import annotations

import os
import secrets
import threading
import time
from pathlib import Path
from typing import Optional

# FastAPI must be importable at module scope so its introspection of our
# Command BaseModel and Request type hints below resolves correctly.
# (Defining BaseModel-typed params inside a closure breaks get_type_hints()
# and makes FastAPI mis-classify them as query parameters → HTTP 422.)
# uvicorn is still imported lazily inside start() so a missing install does
# not break ``from albedo import webhook`` on a headless server.
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel


class Command(BaseModel):
    """JSON body for POST /webhook/command."""
    kind:    str                          # "speak", "query", "open", custom
    payload: dict = {}
    source:  str = "webhook"              # arbitrary label from caller


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_ROOT        = Path(__file__).resolve().parent.parent
_SECRET_FILE = _ROOT / ".webhook_secret"
_DEFAULT_PORT = 5000

# Module state — set by start(), cleared by stop()
_thread:   Optional[threading.Thread] = None
_server:   Optional[object] = None       # uvicorn.Server
_url:      Optional[str] = None

# Incoming update queue — FIFO of dicts, drained by pop_pending_updates()
_queue:      list[dict] = []
_queue_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Secret management
# ---------------------------------------------------------------------------

def current_secret() -> str:
    """
    Return the active shared secret.

    Priority order:
      1. ALBEDO_WEBHOOK_SECRET environment variable (operator override)
      2. Contents of .webhook_secret file (auto-generated, persistent)
      3. Generate a new 32-byte hex secret, write it, return it.
    """
    env_secret = os.environ.get("ALBEDO_WEBHOOK_SECRET", "").strip()
    if env_secret:
        return env_secret

    try:
        s = _SECRET_FILE.read_text(encoding="utf-8").strip()
        if s:
            return s
    except OSError:
        pass

    fresh = secrets.token_hex(32)
    try:
        _SECRET_FILE.write_text(fresh, encoding="utf-8")
        # Best-effort: tighten file permissions on POSIX systems.
        if os.name == "posix":
            os.chmod(_SECRET_FILE, 0o600)
    except OSError:
        pass
    return fresh


def secret_path() -> Path:
    return _SECRET_FILE


# ---------------------------------------------------------------------------
# Update queue (UI consumes via pop_pending_updates)
# ---------------------------------------------------------------------------

def push_update(payload: dict) -> None:
    """Enqueue an update for the UI to consume. Thread-safe."""
    with _queue_lock:
        _queue.append(dict(payload))


def pop_pending_updates() -> list[dict]:
    """Atomically drain and return the queue contents."""
    with _queue_lock:
        items = list(_queue)
        _queue.clear()
    return items


# ---------------------------------------------------------------------------
# FastAPI app factory
# ---------------------------------------------------------------------------

def _build_app():
    """Construct the FastAPI app. Module-level imports defined just below."""
    app = FastAPI(
        title="Albedo Webhook",
        version="1.0",
        docs_url=None,        # disable Swagger UI on this internal service
        redoc_url=None,
    )

    def _require_secret(provided: Optional[str]) -> None:
        expected = current_secret()
        if not provided or not secrets.compare_digest(provided, expected):
            raise HTTPException(status_code=401, detail="bad secret")

    def _require_loopback(request: Request) -> None:
        client = request.client.host if request.client else ""
        if client not in ("127.0.0.1", "::1", "localhost"):
            raise HTTPException(status_code=403, detail="loopback only")

    @app.get("/webhook/health")
    async def health(
        x_albedo_secret: Optional[str] = Header(default=None,
                                                alias="X-Albedo-Secret"),
    ):
        _require_secret(x_albedo_secret)
        return {
            "ok":      True,
            "service": "albedo-webhook",
            "queued":  len(_queue),
        }

    @app.post("/webhook/command")
    async def command(
        cmd: Command,
        x_albedo_secret: Optional[str] = Header(default=None,
                                                alias="X-Albedo-Secret"),
    ):
        _require_secret(x_albedo_secret)
        update = {
            "id":      secrets.token_hex(8),
            "ts":      time.time(),
            "kind":    cmd.kind,
            "payload": cmd.payload,
            "source":  cmd.source,
        }
        push_update(update)
        return {"accepted": True, "id": update["id"], "queued": len(_queue)}

    @app.get("/webhook/secret")
    async def reveal_secret(request: Request):
        # Convenience for local tools / self-tests. Loopback only so a
        # remote attacker who somehow reached us cannot read the secret.
        _require_loopback(request)
        return {"secret": current_secret()}

    return app


# ---------------------------------------------------------------------------
# Public start / stop
# ---------------------------------------------------------------------------

def start(host: Optional[str] = None, port: int = _DEFAULT_PORT) -> str:
    """
    Spin up the webhook in a background thread.

    host  -- defaults to env ALBEDO_WEBHOOK_HOST, else 127.0.0.1.
             Set to 0.0.0.0 ONLY if you understand you're exposing this
             on every interface.
    port  -- defaults to 5000; override per-instance if it collides with
             another service on the host.

    Returns the bound URL. Idempotent.
    """
    global _thread, _server, _url

    if _thread is not None and _thread.is_alive():
        return _url or ""

    bind = host or os.environ.get("ALBEDO_WEBHOOK_HOST", "").strip() or "127.0.0.1"

    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError(
            "uvicorn not installed — add 'uvicorn[standard]' to requirements.txt"
        ) from exc

    app = _build_app()
    config = uvicorn.Config(
        app,
        host=bind,
        port=port,
        log_level="warning",
        access_log=False,
    )
    _server = uvicorn.Server(config)

    def _serve() -> None:
        try:
            _server.run()
        except Exception as exc:                                # noqa: BLE001
            # Log to crash log if black box is installed
            try:
                from albedo import black_box
                black_box.write_report(exc, where="webhook server thread")
            except Exception:
                pass

    _thread = threading.Thread(target=_serve, daemon=True, name="albedo-webhook")
    _thread.start()

    _url = f"http://{bind}:{port}"
    # Ensure the secret is materialised on disk before the first request.
    current_secret()
    return _url


def stop() -> None:
    """Gracefully shut down the uvicorn server."""
    global _thread, _server, _url
    if _server is not None:
        try:
            _server.should_exit = True
        except Exception:
            pass
    if _thread is not None:
        _thread.join(timeout=3.0)
    _thread = None
    _server = None
    _url = None


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()


def url() -> Optional[str]:
    return _url
