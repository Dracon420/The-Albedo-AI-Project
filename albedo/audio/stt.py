"""
Speech-to-text via Faster-Whisper (CPU, tiny, int8).

RTX 2060 VRAM budget:
  Ollama llama3.2:3b    ~4.0 GB
  Whisper tiny (CPU)     0.0 GB  -- zero VRAM; runs entirely on CPU
  headroom              ~2.0 GB
  ──────────────────────────────
  total                 ~4.0 GB  ✓

The model is loaded once at first call and kept resident to avoid
the reload penalty on every query. device=cpu and compute_type=int8
are locked — do not change; CUDA builds require cublas64_12.dll which
is absent on most gaming rigs and causes a hard import failure.

Cache recovery: if the HuggingFace snapshot is corrupt (e.g. model.bin
missing after a partial download), _get_model() wipes the cache entry
and retries once so the user gets a clean re-download rather than a
hard crash.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel
from albedo.config import (
    AUDIO_SAMPLE_RATE,
    WHISPER_MODEL_SIZE,
    WHISPER_DEVICE,
    WHISPER_COMPUTE_TYPE,
)

_model: WhisperModel | None = None


def _clear_whisper_cache() -> None:
    """Delete corrupt faster-whisper HuggingFace cache entries and force a clean re-download."""
    hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    hub_dir = hf_home / "hub"
    if not hub_dir.exists():
        return
    for entry in hub_dir.glob("models--Systran--faster-whisper*"):
        try:
            shutil.rmtree(entry)
            print(f"[stt] Cleared corrupt cache: {entry.name}")
        except Exception as exc:
            print(f"[stt] Cache clear skipped ({entry.name}): {exc}")


def _get_model() -> WhisperModel:
    global _model
    if _model is not None:
        return _model

    for attempt in range(2):
        try:
            print(
                f"[stt] Loading Whisper {WHISPER_MODEL_SIZE} "
                f"on {WHISPER_DEVICE} ({WHISPER_COMPUTE_TYPE})"
                f"{' — retrying after cache clear' if attempt else ''}..."
            )
            _model = WhisperModel(
                WHISPER_MODEL_SIZE,
                device=WHISPER_DEVICE,
                compute_type=WHISPER_COMPUTE_TYPE,
            )
            print("[stt] Whisper ready.")
            return _model
        except Exception as exc:
            if attempt == 0:
                print(f"[stt] Load failed: {exc}")
                print("[stt] Clearing corrupt HuggingFace cache and retrying...")
                _clear_whisper_cache()
            else:
                raise RuntimeError(
                    f"Whisper model failed to load after cache clear: {exc}"
                ) from exc

    raise RuntimeError("Whisper model failed to load.")


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
