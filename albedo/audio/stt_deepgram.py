"""
stt_deepgram.py — Deepgram cloud STT (primary).

One-shot REST path: takes a numpy audio buffer, encodes it as WAV bytes,
sends it to Deepgram's prerecorded REST endpoint, and returns the
transcript. This is the synchronous path used by gui.py / server.py /
listener.py via the dispatcher in albedo/audio/stt.py.

The streaming WebSocket path that the directive references (continuous
mic + partial transcripts during a conversation) is Phase 4 N+3 work —
it pairs with the wake-word comm-mode panel.

Configuration
-------------
DEEPGRAM_API_KEY    required to enable. If unset, is_available() is False
                    and the dispatcher routes around Deepgram entirely.
DEEPGRAM_MODEL      default "nova-2" (low latency, English-focused)
DEEPGRAM_LANGUAGE   default "en"
DEEPGRAM_TIMEOUT    seconds before the request is abandoned (default 10)

Failure modes
-------------
Every path returns "" on failure — never raises. The router decides
whether to retry with whisper based on the empty return + the recorded
last_error() value.

Public API
----------
    is_available() -> bool
    transcribe(audio, sample_rate=16000) -> str
    last_error() -> str | None
    reset_state() -> None             # tests only
"""
from __future__ import annotations

import io
import os
import threading
from typing import Optional

import numpy as np

# soundfile is only needed for the WAV encode; soft-import keeps tests
# free of the dependency.
try:
    import soundfile as sf
    _SOUNDFILE_OK = True
except ImportError:
    _SOUNDFILE_OK = False


# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_state_lock = threading.Lock()
_last_error: Optional[str] = None


def last_error() -> Optional[str]:
    return _last_error


def reset_state() -> None:
    """Drop cached error state — used by unit tests."""
    global _last_error
    with _state_lock:
        _last_error = None


# ---------------------------------------------------------------------------
# Availability check
# ---------------------------------------------------------------------------

def _api_key() -> str:
    return os.environ.get("DEEPGRAM_API_KEY", "").strip()


def _deepgram_importable() -> bool:
    try:
        import deepgram  # noqa: F401
        return True
    except ImportError:
        return False


def is_available() -> bool:
    """
    True when:
      - deepgram-sdk is pip-installed,
      - soundfile is importable (to encode WAV bytes),
      - DEEPGRAM_API_KEY is set in env.

    Does NOT make a network call; cheap to call from a hot path.
    """
    return _deepgram_importable() and _SOUNDFILE_OK and bool(_api_key())


# ---------------------------------------------------------------------------
# Audio encoding
# ---------------------------------------------------------------------------

def _to_wav_bytes(audio: np.ndarray, sample_rate: int) -> Optional[bytes]:
    """Encode a numpy audio buffer to WAV PCM_16 bytes. Returns None on error."""
    if not _SOUNDFILE_OK:
        return None
    if audio.dtype not in (np.float32, np.int16):
        audio = audio.astype(np.float32)
    buf = io.BytesIO()
    try:
        sf.write(buf, audio, sample_rate, format="WAV", subtype="PCM_16")
    except Exception as exc:                                    # noqa: BLE001
        print(f"[stt_deepgram] WAV encode error: {exc}")
        return None
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Deepgram REST call
# ---------------------------------------------------------------------------

def _timeout_seconds() -> float:
    raw = os.environ.get("DEEPGRAM_TIMEOUT", "").strip()
    if not raw:
        return 10.0
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 10.0


def _build_options():
    """Construct PrerecordedOptions with the configured model + language."""
    from deepgram import PrerecordedOptions
    return PrerecordedOptions(
        model=os.environ.get("DEEPGRAM_MODEL", "nova-2"),
        language=os.environ.get("DEEPGRAM_LANGUAGE", "en"),
        smart_format=True,
        punctuate=True,
    )


def _client():
    """Construct DeepgramClient from the configured API key."""
    from deepgram import DeepgramClient
    return DeepgramClient(_api_key())


def _extract_transcript(response) -> str:
    """
    Pull the first-alternative transcript from a Deepgram response. The
    SDK exposes either a typed object or a dict depending on version, so
    we cover both shapes.
    """
    try:
        # SDK v3+ typed object access
        return response.results.channels[0].alternatives[0].transcript or ""
    except Exception:
        pass
    try:
        # Dict-style access (older SDKs or .to_dict())
        if hasattr(response, "to_dict"):
            data = response.to_dict()
        else:
            data = response
        return (
            data["results"]["channels"][0]["alternatives"][0]["transcript"] or ""
        )
    except Exception:
        return ""


def transcribe(audio: np.ndarray, sample_rate: int = 16000) -> str:
    """
    Send `audio` to Deepgram's prerecorded REST endpoint and return the
    transcript. Returns "" on:

      - missing API key / SDK
      - audio too short (<0.25 s)
      - WAV encoding failure
      - network error / timeout
      - empty result from Deepgram

    Records the failure reason in last_error() so the router can log
    the demotion to whisper.
    """
    global _last_error
    if audio is None or len(audio) < sample_rate * 0.25:
        return ""
    if not is_available():
        with _state_lock:
            if not _deepgram_importable():
                _last_error = "deepgram-sdk not installed"
            elif not _api_key():
                _last_error = "DEEPGRAM_API_KEY not set"
            elif not _SOUNDFILE_OK:
                _last_error = "soundfile not installed"
        return ""

    wav = _to_wav_bytes(audio, sample_rate)
    if wav is None:
        with _state_lock:
            _last_error = "wav encode failed"
        return ""

    try:
        client = _client()
        options = _build_options()
        payload = {"buffer": wav}
        # deepgram-sdk v3.x: client.listen.rest.v("1").transcribe_file
        # deepgram-sdk v4.x: client.listen.prerecorded.v("1").transcribe_file
        # Try both shapes.
        rest_path = getattr(client.listen, "rest", None) or getattr(
            client.listen, "prerecorded", None)
        if rest_path is None:
            raise RuntimeError("Deepgram SDK shape unrecognized — neither "
                               "client.listen.rest nor .prerecorded present")
        response = rest_path.v("1").transcribe_file(
            payload, options, timeout=_timeout_seconds()
        )
        text = _extract_transcript(response).strip()
        with _state_lock:
            _last_error = None if text else "deepgram returned empty transcript"
        return text
    except Exception as exc:                                    # noqa: BLE001
        with _state_lock:
            _last_error = f"{type(exc).__name__}: {exc}"
        print(f"[stt_deepgram] error: {exc}")
        return ""
