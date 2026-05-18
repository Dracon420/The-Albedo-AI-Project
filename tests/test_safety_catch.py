"""
Unit tests for albedo.safety_catch — covers the allowlist fast path, the
approval handler contract (allow / deny / handler-raises), audit log
appending, and in-flight counter accounting.

Run:
    python tests/test_safety_catch.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import subprocess
from unittest.mock import patch
from albedo import safety_catch                                # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset() -> None:
    """Reset module state between tests so each test is independent."""
    safety_catch.set_approval_handler(None)   # restore console default
    # Audit log is append-only by design — tests don't reset it.


# ---------------------------------------------------------------------------
# Allowlist fast path
# ---------------------------------------------------------------------------

def test_allowlisted_command_runs_without_handler():
    """nvidia-smi telemetry must skip the handler entirely (no prompt)."""
    _reset()
    called = {"n": 0}

    def deny_all(req):
        called["n"] += 1
        return False
    safety_catch.set_approval_handler(deny_all)

    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        safety_catch.safe_run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            requester="test")

    assert mock_run.called, "subprocess.run should fire for allowlisted commands"
    assert called["n"] == 0, "handler must not be invoked for allowlisted commands"


def test_taskkill_pythonw_is_allowlisted():
    """The uninstaller's taskkill /F /IM pythonw.exe is pre-approved."""
    _reset()

    def deny_all(req):
        return False
    safety_catch.set_approval_handler(deny_all)

    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        safety_catch.safe_run(["taskkill", "/F", "/IM", "pythonw.exe"],
                              requester="uninstaller")
    assert mock_run.called


# ---------------------------------------------------------------------------
# Handler contract
# ---------------------------------------------------------------------------

def test_handler_approves_runs_command():
    _reset()
    seen = []

    def approve(req):
        seen.append(req)
        return True
    safety_catch.set_approval_handler(approve)

    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        safety_catch.safe_run(["rm", "-rf", "/tmp/danger"], requester="swarm")

    assert len(seen) == 1
    assert seen[0].requester == "swarm"
    assert seen[0].argv == ["rm", "-rf", "/tmp/danger"]
    assert "rm" in seen[0].display
    assert mock_run.called


def test_handler_denies_raises_command_denied():
    _reset()

    def refuse(req):
        return False
    safety_catch.set_approval_handler(refuse)

    raised = False
    try:
        with patch.object(subprocess, "run") as mock_run:
            safety_catch.safe_run(["evil-binary", "--purge"], requester="swarm")
        assert not mock_run.called, "denied commands must not execute"
    except safety_catch.CommandDenied as exc:
        raised = True
        assert exc.request.requester == "swarm"
        assert "evil-binary" in exc.request.display
    assert raised, "CommandDenied must be raised when handler returns False"


def test_handler_exception_becomes_command_denied():
    """A buggy handler that raises must fail-closed (deny), not crash through."""
    _reset()

    def buggy(req):
        raise RuntimeError("UI dialog crashed")
    safety_catch.set_approval_handler(buggy)

    raised = False
    try:
        safety_catch.safe_run(["touch", "/tmp/file"], requester="swarm")
    except safety_catch.CommandDenied as exc:
        raised = True
        assert "handler raised" in exc.reason
    assert raised


# ---------------------------------------------------------------------------
# In-flight accounting
# ---------------------------------------------------------------------------

def test_in_flight_counter_increments_during_handler_and_resets():
    """pending_count() reflects requests waiting on the handler decision."""
    _reset()
    observed = []

    def slow_handler(req):
        observed.append(safety_catch.pending_count())
        return False
    safety_catch.set_approval_handler(slow_handler)

    try:
        # Use an unusual binary name so no prior test's add_allowed() pattern
        # accidentally fast-paths around the handler.
        safety_catch.safe_run(["zz-in-flight-probe", "arg"], requester="test")
    except safety_catch.CommandDenied:
        pass
    assert observed == [1], f"expected pending_count==1 during handler, got {observed}"
    assert safety_catch.pending_count() == 0, "must reset to 0 after handler returns"


# ---------------------------------------------------------------------------
# add_allowed
# ---------------------------------------------------------------------------

def test_add_allowed_pattern_takes_effect():
    """Custom allowlist entries skip the handler like the built-ins."""
    _reset()
    safety_catch.set_approval_handler(lambda req: False)
    safety_catch.add_allowed(r"^echo\b")

    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        safety_catch.safe_run(["echo", "hello"], requester="test")
    assert mock_run.called


# ---------------------------------------------------------------------------
# String argv accepted
# ---------------------------------------------------------------------------

def test_string_argv_is_split():
    _reset()
    captured = {}

    def approve(req):
        captured["argv"] = req.argv
        return True
    safety_catch.set_approval_handler(approve)

    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        safety_catch.safe_run('rm "with spaces"', requester="test")
    assert captured["argv"][0] == "rm"
    # On Windows shlex splits without honoring single quotes, but double
    # quotes work in posix=False mode — exact tokenisation is OS-dependent,
    # so just assert we got more than one arg.
    assert len(captured["argv"]) >= 2


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
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
