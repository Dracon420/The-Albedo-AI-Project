"""
Integration tests for albedo.webhook — spins up the FastAPI server on a
free local port, hits it with httpx, and verifies auth + queue behaviour.

Run:
    python tests/test_webhook.py
"""
from __future__ import annotations

import os
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Use a dedicated env-var secret so the test never touches the real
# .webhook_secret file on disk.
os.environ["ALBEDO_WEBHOOK_SECRET"] = "test-secret-do-not-use-in-prod"

import httpx                                                          # noqa: E402
from albedo import webhook                                            # noqa: E402


def _free_port() -> int:
    """Bind to port 0 to let the OS pick a free port, then close and reuse."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_ready(url: str, timeout: float = 5.0) -> None:
    """Poll the health endpoint until the server is accepting connections."""
    headers = {"X-Albedo-Secret": webhook.current_secret()}
    deadline = time.time() + timeout
    last_exc = None
    while time.time() < deadline:
        try:
            r = httpx.get(f"{url}/webhook/health", headers=headers, timeout=0.5)
            if r.status_code == 200:
                return
        except Exception as exc:
            last_exc = exc
        time.sleep(0.05)
    raise TimeoutError(f"webhook never came up: {last_exc!r}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_secret_from_env_var():
    """ALBEDO_WEBHOOK_SECRET wins over the on-disk file."""
    assert webhook.current_secret() == "test-secret-do-not-use-in-prod"


def test_server_starts_on_loopback_and_health_works():
    port = _free_port()
    url = webhook.start(host="127.0.0.1", port=port)
    try:
        _wait_for_ready(url)
        r = httpx.get(
            f"{url}/webhook/health",
            headers={"X-Albedo-Secret": webhook.current_secret()},
            timeout=2.0,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["service"] == "albedo-webhook"
    finally:
        webhook.stop()


def test_missing_secret_returns_401():
    port = _free_port()
    url = webhook.start(host="127.0.0.1", port=port)
    try:
        _wait_for_ready(url)
        # No header at all
        r = httpx.get(f"{url}/webhook/health", timeout=2.0)
        assert r.status_code == 401, f"expected 401, got {r.status_code}"
    finally:
        webhook.stop()


def test_wrong_secret_returns_401():
    port = _free_port()
    url = webhook.start(host="127.0.0.1", port=port)
    try:
        _wait_for_ready(url)
        r = httpx.get(
            f"{url}/webhook/health",
            headers={"X-Albedo-Secret": "wrong"},
            timeout=2.0,
        )
        assert r.status_code == 401
    finally:
        webhook.stop()


def test_command_enqueues_for_ui_consumption():
    port = _free_port()
    url = webhook.start(host="127.0.0.1", port=port)
    try:
        _wait_for_ready(url)
        # Drain any leftover state from prior tests
        webhook.pop_pending_updates()

        r = httpx.post(
            f"{url}/webhook/command",
            headers={"X-Albedo-Secret": webhook.current_secret()},
            json={"kind": "speak", "payload": {"text": "hello"},
                  "source": "mobile-app"},
            timeout=2.0,
        )
        assert r.status_code == 200
        assert r.json()["accepted"] is True

        # The UI calling pop_pending_updates() must see exactly that command
        updates = webhook.pop_pending_updates()
        assert len(updates) == 1
        u = updates[0]
        assert u["kind"]    == "speak"
        assert u["payload"] == {"text": "hello"}
        assert u["source"]  == "mobile-app"

        # Second drain returns empty — pop is destructive
        assert webhook.pop_pending_updates() == []
    finally:
        webhook.stop()


def test_idempotent_start_returns_same_url():
    port = _free_port()
    url1 = webhook.start(host="127.0.0.1", port=port)
    url2 = webhook.start(host="127.0.0.1", port=port)
    try:
        assert url1 == url2
        assert webhook.is_running()
    finally:
        webhook.stop()
    assert not webhook.is_running()


def test_secret_endpoint_loopback_only_allows_127():
    port = _free_port()
    url = webhook.start(host="127.0.0.1", port=port)
    try:
        _wait_for_ready(url)
        # Request comes from 127.0.0.1, no secret header required by this
        # endpoint — but bind is loopback so this is fine.
        r = httpx.get(f"{url}/webhook/secret", timeout=2.0)
        assert r.status_code == 200
        assert r.json()["secret"] == webhook.current_secret()
    finally:
        webhook.stop()


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import inspect, traceback
    mod = sys.modules[__name__]
    tests = [(n, f) for n, f in inspect.getmembers(mod, inspect.isfunction)
             if n.startswith("test_")]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception:
            print(f"  FAIL  {name}")
            traceback.print_exc()
            failed += 1
        # Ensure server is stopped between tests
        webhook.stop()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
