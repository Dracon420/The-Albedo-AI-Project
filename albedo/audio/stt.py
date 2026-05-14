"""
Speech-to-text via Faster-Whisper on CUDA.

RTX 2060 VRAM budget:
  Ollama (mistral Q4)   ~4.0 GB
  Whisper small int8f16 ~0.5 GB
  headroom              ~1.5 GB
  ──────────────────────────────
  total                 ~6.0 GB  ✓

The model is loaded once at first call and kept resident to avoid
the ~2-second reload penalty on every query.
"""
from __future__ import annotations

import numpy as np
from faster_whisper import WhisperModel
from albedo.config import (
    AUDIO_SAMPLE_RATE,
    WHISPER_MODEL_SIZE,
    WHISPER_DEVICE,
    WHISPER_COMPUTE_TYPE,
)

_model: WhisperModel | None = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        print(
            f"[stt] Loading Whisper {WHISPER_MODEL_SIZE} "
            f"on {WHISPER_DEVICE} ({WHISPER_COMPUTE_TYPE})..."
        )
        _model = WhisperModel(
            WHISPER_MODEL_SIZE,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )
        print("[stt] Whisper ready.")
    return _model


def prewarm() -> None:
    """Load the Whisper model now so the first MIC press is instant."""
    _get_model()


def transcribe(audio: np.ndarray) -> str:
    """
    Transcribe a float32 numpy array (16 kHz mono) to text.
    Returns an empty string if the audio is too short or silent.
    """
    if audio is None or len(audio) < AUDIO_SAMPLE_RATE * 0.3:
        return ""

    model = _get_model()
    segments, _ = model.transcribe(
        audio,
        language="en",
        beam_size=5,
        vad_filter=True,               # built-in Silero VAD — skips silent segments
        vad_parameters={"min_silence_duration_ms": 500},
    )
    return " ".join(seg.text.strip() for seg in segments).strip()
