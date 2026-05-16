"""
Speech-to-text via Vosk (offline, CPU, zero VRAM).

Default model:
  vosk-model-small-en-us-0.15 (~40 MB)

Downloaded by setup_utility.py into <project_root>/vosk_models/.
Override the location with VOSK_MODEL_PATH in .env.

The model is loaded once at first call and kept resident, so first MIC
press has the load latency (~1 s) and every subsequent transcription
is instant.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from vosk import KaldiRecognizer, Model, SetLogLevel

from albedo.config import AUDIO_SAMPLE_RATE, VOSK_MODEL_PATH

# Silence Vosk's verbose Kaldi logs
SetLogLevel(-1)

_model: Model | None = None


def _resolve_model_path() -> Path:
    return Path(VOSK_MODEL_PATH).expanduser()


def is_cached() -> bool:
    """True if the Vosk model directory exists locally."""
    return _resolve_model_path().exists()


def _get_model() -> Model:
    global _model
    if _model is None:
        path = _resolve_model_path()
        if not path.exists():
            raise FileNotFoundError(
                f"Vosk model not found at {path}. "
                "Run setup_utility.py to download it, "
                "or set VOSK_MODEL_PATH in .env."
            )
        print(f"[stt] Loading Vosk model: {path.name}")
        _model = Model(str(path))
        print("[stt] Vosk ready.")
    return _model


def prewarm() -> None:
    """Load the Vosk model now so the first transcription is instant."""
    _get_model()


def transcribe(audio: np.ndarray) -> str:
    """
    Transcribe a numpy array (16 kHz mono) to text.

    Accepts float32 in the range [-1, 1] or int16 directly.
    Returns an empty string if the audio is too short or silent.
    """
    if audio is None or len(audio) < AUDIO_SAMPLE_RATE * 0.3:
        return ""

    if audio.dtype != np.int16:
        audio = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)

    model = _get_model()
    recognizer = KaldiRecognizer(model, AUDIO_SAMPLE_RATE)
    recognizer.SetWords(False)
    recognizer.AcceptWaveform(audio.tobytes())

    result = json.loads(recognizer.FinalResult())
    return result.get("text", "").strip()
