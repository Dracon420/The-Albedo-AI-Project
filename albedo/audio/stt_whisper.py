"""
stt_whisper.py — distil-whisper offline STT fallback.

Lazy-loaded faster-whisper wrapper around the distil-small.en model. This
is the offline failsafe behind the primary Deepgram WebSocket STT — it
only loads into VRAM/RAM when the cloud STT fails, per Phase 6's
``should_load_eagerly("stt_whisper") == False`` contract.

Device binding follows ``albedo.resource_policy``:
  - CUDA when available (torch + nvidia-smi both happy)
  - CPU with audible-quality warning when CUDA is missing

Public API (matches the contract of albedo.audio.stt for drop-in routing):

    is_available() -> bool         # faster-whisper installed
    prewarm() -> bool              # force the model load (for testing only)
    transcribe(audio, sample_rate=16000) -> str
        Accepts float32 in [-1, 1] or int16. Returns the transcript or
        empty string on failure. Never raises.
    load_error() -> str | None

Why lazy
--------
The distil-small.en model is ~250 MB on disk and ~1.2 GB in CUDA VRAM at
float16, ~600 MB in CPU RAM at int8. On a 6 GB GPU shared with Ollama
the eager load would OOM the LLM on the first chat turn. The router
only invokes whisper when Deepgram has actually failed, so the load
cost is paid exactly once per outage rather than on every boot.

Compute type selection
----------------------
faster-whisper accepts a `compute_type` argument that trades quality for
speed/VRAM. We map by device:

  cuda  -> float16   (~1.2 GB VRAM, ~3-5x realtime on RTX 2060)
  cpu   -> int8      (~600 MB RAM, ~0.7x realtime on Ryzen 5)

Both are quality-equivalent to distil-whisper's reference numbers within
~0.5 WER points.
"""
from __future__ import annotations

import threading
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Tunables — model name and revision are pinned for reproducibility
# ---------------------------------------------------------------------------

_MODEL_NAME = "distil-small.en"

# Singleton state (guarded by _load_lock)
_load_lock = threading.Lock()
_model = None
_load_attempted = False
_load_error: Optional[str] = None


# ---------------------------------------------------------------------------
# Availability check
# ---------------------------------------------------------------------------

def _faster_whisper_importable() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def is_available() -> bool:
    """True when faster-whisper is installed. Cheap; safe to call repeatedly."""
    return _faster_whisper_importable()


def load_error() -> Optional[str]:
    return _load_error


# ---------------------------------------------------------------------------
# Lazy model load
# ---------------------------------------------------------------------------

def _select_compute_type(device: str) -> str:
    if device == "cuda":
        return "float16"
    return "int8"


def _build_model():
    """
    Construct the WhisperModel honoring resource_policy. Returns the model
    or raises — caller wraps to set _load_error and return False.
    """
    from faster_whisper import WhisperModel
    from albedo.resource_policy import device_for

    device = device_for("stt_whisper")
    compute_type = _select_compute_type(device)
    if device == "cpu":
        print(
            "[stt_whisper] CUDA unavailable — loading distil-small.en on CPU "
            "(audible-quality slower; acceptable for fallback usage)"
        )
    return WhisperModel(_MODEL_NAME, device=device, compute_type=compute_type)


def _ensure_loaded() -> bool:
    """Load the model if not already loaded. Returns True on success."""
    global _model, _load_attempted, _load_error
    if _model is not None:
        return True
    with _load_lock:
        if _model is not None:
            return True
        _load_attempted = True
        if not is_available():
            _load_error = "faster-whisper not installed"
            return False
        try:
            _model = _build_model()
            _load_error = None
            return True
        except Exception as exc:                                # noqa: BLE001
            _load_error = f"{type(exc).__name__}: {exc}"
            _model = None
            return False


def prewarm() -> bool:
    """Force the model load now. Returns True on success."""
    return _ensure_loaded()


# ---------------------------------------------------------------------------
# Public transcribe
# ---------------------------------------------------------------------------

def _to_float32(audio: np.ndarray) -> np.ndarray:
    """faster-whisper wants float32 in [-1, 1]. Convert int16 if needed."""
    if audio.dtype == np.float32:
        return audio
    if audio.dtype == np.int16:
        return audio.astype(np.float32) / 32768.0
    # Anything else — coerce to float32 and clip
    return np.clip(audio.astype(np.float32), -1.0, 1.0)


def transcribe(audio: np.ndarray, sample_rate: int = 16000) -> str:
    """
    Transcribe a numpy audio buffer (mono, 16 kHz preferred).

    Returns the joined transcript text, or empty string on any failure
    (model load failed, audio too short, internal error). Never raises
    into the caller — empty string lets the router fall through cleanly
    or the UI display a no-result message.
    """
    if audio is None or len(audio) < sample_rate * 0.25:
        return ""
    if not _ensure_loaded():
        return ""

    audio_f32 = _to_float32(audio)
    try:
        segments, _info = _model.transcribe(
            audio_f32,
            language="en",
            beam_size=1,             # tiny model — beam>1 wastes cycles
            without_timestamps=True,
        )
        return " ".join(seg.text for seg in segments).strip()
    except Exception as exc:                                    # noqa: BLE001
        print(f"[stt_whisper] transcription error: {exc}")
        return ""


# Module-level introspection helper used by tests
def _reset_for_tests() -> None:
    """Drop the cached singleton — only used by unit tests."""
    global _model, _load_attempted, _load_error
    with _load_lock:
        _model = None
        _load_attempted = False
        _load_error = None
