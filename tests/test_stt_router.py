"""
Unit tests for albedo.audio.stt_router — the Deepgram-with-whisper
failover orchestration. Mocks both downstream modules so the router's
own decision logic is the thing under test.

Run:
    python tests/test_stt_router.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import torch                                                    # noqa: F401
except ImportError:
    pass

import numpy as np                                                  # noqa: E402

from albedo.audio import stt_router                                 # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _audio():
    return np.zeros(16000, dtype=np.float32)


def _reset():
    stt_router._reset_for_tests()


# ---------------------------------------------------------------------------
# Happy path — Deepgram returns a transcript
# ---------------------------------------------------------------------------

def test_deepgram_success_no_failover():
    _reset()
    with patch("albedo.audio.stt_deepgram.is_available", return_value=True), \
         patch("albedo.audio.stt_deepgram.transcribe", return_value="cloud transcript") as dg, \
         patch("albedo.audio.stt_whisper.transcribe") as wh:
        result = stt_router.transcribe_with_meta(_audio())
    assert result["text"]    == "cloud transcript"
    assert result["engine"]  == "deepgram"
    assert result["demoted"] is False
    assert result["reason"]  is None
    assert dg.called
    assert not wh.called, "whisper must not be called when Deepgram succeeds"


# ---------------------------------------------------------------------------
# Failover — Deepgram empty/failed → whisper
# ---------------------------------------------------------------------------

def test_failover_to_whisper_on_deepgram_empty():
    _reset()
    with patch("albedo.audio.stt_deepgram.is_available", return_value=True), \
         patch("albedo.audio.stt_deepgram.transcribe", return_value=""), \
         patch("albedo.audio.stt_deepgram.last_error", return_value="network timeout"), \
         patch("albedo.audio.stt_whisper.is_available", return_value=True), \
         patch("albedo.audio.stt_whisper.transcribe", return_value="offline transcript"):
        result = stt_router.transcribe_with_meta(_audio())
    assert result["text"]    == "offline transcript"
    assert result["engine"]  == "whisper"
    assert result["demoted"] is True
    assert "network timeout" in (result["reason"] or "")


def test_failover_records_demotion_in_state():
    _reset()
    with patch("albedo.audio.stt_deepgram.is_available", return_value=True), \
         patch("albedo.audio.stt_deepgram.transcribe", return_value=""), \
         patch("albedo.audio.stt_deepgram.last_error", return_value="403 unauthorized"), \
         patch("albedo.audio.stt_whisper.is_available", return_value=True), \
         patch("albedo.audio.stt_whisper.transcribe", return_value="ok"):
        stt_router.transcribe_with_meta(_audio())
    assert stt_router.last_engine() == "whisper"
    assert "403 unauthorized" in (stt_router.last_demoted_reason() or "")


# ---------------------------------------------------------------------------
# Deepgram unconfigured → whisper-only path (no demotion logged)
# ---------------------------------------------------------------------------

def test_whisper_only_when_deepgram_unconfigured():
    _reset()
    with patch("albedo.audio.stt_deepgram.is_available", return_value=False), \
         patch("albedo.audio.stt_deepgram.transcribe") as dg, \
         patch("albedo.audio.stt_whisper.is_available", return_value=True), \
         patch("albedo.audio.stt_whisper.transcribe", return_value="whisper output"):
        result = stt_router.transcribe_with_meta(_audio())
    assert result["text"]    == "whisper output"
    assert result["engine"]  == "whisper"
    assert result["demoted"] is False, "whisper-only mode is the configured flow, not a demotion"
    assert not dg.called


# ---------------------------------------------------------------------------
# Total failure — neither engine produces output
# ---------------------------------------------------------------------------

def test_returns_empty_when_no_engine_available():
    _reset()
    with patch("albedo.audio.stt_deepgram.is_available", return_value=False), \
         patch("albedo.audio.stt_whisper.is_available", return_value=False):
        result = stt_router.transcribe_with_meta(_audio())
    assert result["text"]   == ""
    assert result["engine"] == "none"


def test_returns_empty_when_whisper_fallback_also_fails():
    _reset()
    with patch("albedo.audio.stt_deepgram.is_available", return_value=True), \
         patch("albedo.audio.stt_deepgram.transcribe", return_value=""), \
         patch("albedo.audio.stt_deepgram.last_error", return_value="cloud down"), \
         patch("albedo.audio.stt_whisper.is_available", return_value=True), \
         patch("albedo.audio.stt_whisper.transcribe", return_value=""):
        result = stt_router.transcribe_with_meta(_audio())
    assert result["text"]    == ""
    assert result["engine"]  == "whisper"     # tried, returned nothing
    assert result["demoted"] is True
    assert "cloud down" in (result["reason"] or "")


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------

def test_transcribe_returns_just_text():
    _reset()
    with patch("albedo.audio.stt_deepgram.is_available", return_value=True), \
         patch("albedo.audio.stt_deepgram.transcribe", return_value="text only please"):
        assert stt_router.transcribe(_audio()) == "text only please"


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def test_demotion_is_audit_logged_even_when_audit_flag_off():
    _reset()
    p = stt_router.audit_log_path()
    sentinel = "DEMOTE_AUDIT_SENTINEL_" + str(int.from_bytes(__import__("os").urandom(4), "big"))
    with patch("albedo.audio.stt_deepgram.is_available", return_value=True), \
         patch("albedo.audio.stt_deepgram.transcribe", return_value=""), \
         patch("albedo.audio.stt_deepgram.last_error", return_value=sentinel), \
         patch("albedo.audio.stt_whisper.is_available", return_value=True), \
         patch("albedo.audio.stt_whisper.transcribe", return_value="ok"):
        stt_router.transcribe_with_meta(_audio())
    body = p.read_text(encoding="utf-8")
    assert sentinel in body, "demotion must be audit-logged regardless of STT_ROUTER_AUDIT"


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import faulthandler, inspect, os, traceback
    faulthandler.enable()
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
    os._exit(0 if failed == 0 else 1)
