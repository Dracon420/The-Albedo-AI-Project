"""
stt_router.py — STT failover orchestration.

When the dispatcher in ``albedo/audio/stt.py`` sees ``AUDIO_STT=deepgram``
it routes here. This module owns the failover policy: try the primary
cloud STT first, fall back to the offline whisper engine on any failure,
and log each demotion so the user knows latency / quality has shifted.

Decision tree
-------------
1. If Deepgram is configured (DEEPGRAM_API_KEY set + SDK installed):
     - call stt_deepgram.transcribe(audio)
     - non-empty result  -> return it tagged as engine="deepgram"
     - empty result      -> read stt_deepgram.last_error(); log demotion;
                            fall through to step 2
2. If whisper is available (faster-whisper installed):
     - lazy-load distil-small.en on the device assigned by Phase 6's
       resource_policy (CUDA when available, else CPU)
     - call stt_whisper.transcribe(audio)
     - non-empty result  -> return it tagged as engine="whisper"
     - empty result      -> return "" tagged as engine="none"
3. Neither engine available -> return "" tagged as engine="none".

Audit log
---------
Each call appends one line to logs/stt_router.log with:

    ISO_TS  engine=<name>  ok=<bool>  ms=<duration>  reason=<demote_reason or ->

The audit log is opt-in via STT_ROUTER_AUDIT=1 to avoid filesystem
churn during normal voice loops. Failover demotions are always logged
regardless of the env flag.

Public API
----------
    transcribe(audio, sample_rate=16000) -> str
        Returns transcript or empty string. Never raises.

    transcribe_with_meta(audio, sample_rate=16000) -> dict
        Same as above but returns a dict with:
            { "text": str, "engine": str, "demoted": bool,
              "reason": str | None, "ms": float }
        — useful for the chat-feed callout when the engine demotes
        from deepgram to whisper mid-conversation.

    last_engine() -> str            # what engine produced the last result
    last_demoted_reason() -> str | None

    audit_log_path() -> Path
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Paths + state
# ---------------------------------------------------------------------------

_ROOT       = Path(__file__).resolve().parent.parent.parent
_LOG_DIR    = _ROOT / "logs"
_AUDIT_FILE = _LOG_DIR / "stt_router.log"

_state_lock = threading.Lock()
_last_engine = "none"
_last_demoted_reason: Optional[str] = None


def last_engine() -> str:
    return _last_engine


def last_demoted_reason() -> Optional[str]:
    return _last_demoted_reason


def audit_log_path() -> Path:
    return _AUDIT_FILE


def _audit(line: str) -> None:
    """Best-effort append to logs/stt_router.log. Never raises."""
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().isoformat(timespec="seconds")
        with open(_AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(f"{ts}  {line}\n")
    except Exception:
        pass


def _audit_always() -> bool:
    """Audit every call when STT_ROUTER_AUDIT is set; otherwise only on demotion."""
    return os.environ.get("STT_ROUTER_AUDIT", "").strip() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def transcribe(audio: np.ndarray, sample_rate: int = 16000) -> str:
    """Convenience: same as transcribe_with_meta() but returns just the text."""
    return transcribe_with_meta(audio, sample_rate)["text"]


def transcribe_with_meta(audio: np.ndarray, sample_rate: int = 16000) -> dict:
    """
    Run the Deepgram → whisper failover and return both the transcript
    and metadata about which engine produced it.
    """
    global _last_engine, _last_demoted_reason
    t0 = time.perf_counter()

    # Late imports so the dispatcher can import this module even when
    # whisper / deepgram are missing.
    from albedo.audio import stt_deepgram, stt_whisper

    demoted = False
    demote_reason: Optional[str] = None

    # ---- step 1: Deepgram ----
    if stt_deepgram.is_available():
        text = stt_deepgram.transcribe(audio, sample_rate=sample_rate)
        if text:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            with _state_lock:
                _last_engine = "deepgram"
                _last_demoted_reason = None
            if _audit_always():
                _audit(f"engine=deepgram  ok=True   ms={elapsed_ms:.0f}  reason=-")
            return {
                "text": text, "engine": "deepgram",
                "demoted": False, "reason": None, "ms": elapsed_ms,
            }
        # Empty Deepgram result — record demotion reason
        demote_reason = stt_deepgram.last_error() or "deepgram returned empty"
        demoted = True
    else:
        # Skip Deepgram silently if not configured — not a demotion, just
        # the configured fallback flow (whisper-only mode).
        pass

    # ---- step 2: whisper fallback ----
    if stt_whisper.is_available():
        text = stt_whisper.transcribe(audio, sample_rate=sample_rate)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        with _state_lock:
            _last_engine = "whisper"
            _last_demoted_reason = demote_reason if demoted else None
        if demoted:
            print(f"[stt_router] Deepgram unavailable ({demote_reason}) — "
                  f"falling back to whisper")
            _audit(f"engine=whisper  ok={bool(text)}  ms={elapsed_ms:.0f}  "
                   f"reason=deepgram_failed: {demote_reason}")
        elif _audit_always():
            _audit(f"engine=whisper  ok={bool(text)}  ms={elapsed_ms:.0f}  reason=-")
        return {
            "text": text, "engine": "whisper",
            "demoted": demoted, "reason": demote_reason, "ms": elapsed_ms,
        }

    # ---- nothing worked ----
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    with _state_lock:
        _last_engine = "none"
        _last_demoted_reason = demote_reason or "no engine configured"
    _audit(f"engine=none  ok=False  ms={elapsed_ms:.0f}  "
           f"reason={_last_demoted_reason}")
    return {
        "text": "", "engine": "none",
        "demoted": demoted, "reason": _last_demoted_reason, "ms": elapsed_ms,
    }


# ---------------------------------------------------------------------------
# Test helper
# ---------------------------------------------------------------------------

def _reset_for_tests() -> None:
    global _last_engine, _last_demoted_reason
    with _state_lock:
        _last_engine = "none"
        _last_demoted_reason = None
