"""
Speech-to-text via Vosk (offline, CPU, zero VRAM).

Default model: vosk-model-small-en-us-0.15 (~40 MB)

Auto-acquired: if the model folder is absent, stt.py downloads and
extracts it automatically from alphacephei.com before initialising.
Override the install path with VOSK_MODEL_PATH in .env.

The model is loaded once at first call and kept resident, so first MIC
press has the load latency (~1 s) and every subsequent transcription
is instant.
"""
from __future__ import annotations

import json
import urllib.request
import zipfile
from pathlib import Path

import numpy as np

from albedo.config import AUDIO_SAMPLE_RATE, VOSK_MODEL_PATH

# ---------------------------------------------------------------------------
# Guarded import — clean error if vosk or sounddevice is not installed
# ---------------------------------------------------------------------------
try:
    from vosk import KaldiRecognizer, Model, SetLogLevel
    import sounddevice as _sd_check  # noqa: F401 — verify it's present
    SetLogLevel(-1)
    _VOSK_AVAILABLE = True
except ImportError:
    _VOSK_AVAILABLE = False
    print("[SYS] FATAL: Run 'pip install vosk sounddevice' in your terminal.")

# ---------------------------------------------------------------------------
# Auto-acquisition constants
# ---------------------------------------------------------------------------
_MODEL_URL = (
    "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
)

_model: "Model | None" = None


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _resolve_model_path() -> Path:
    return Path(VOSK_MODEL_PATH).expanduser()


def is_cached() -> bool:
    """True if the Vosk model directory exists locally (no side effects)."""
    return _resolve_model_path().exists()


# ---------------------------------------------------------------------------
# Auto-download
# ---------------------------------------------------------------------------

def _ensure_model() -> None:
    """Download and extract the Vosk model if it is not already present."""
    path = _resolve_model_path()
    if path.exists():
        return

    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    zip_path = parent / "vosk-model-small-en-us-0.15.zip"

    print("[stt] Vosk model not found — downloading from alphacephei.com ...")
    try:
        urllib.request.urlretrieve(_MODEL_URL, zip_path)
        print("[stt] Extracting...")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(parent)
        zip_path.unlink()
        print(f"[stt] Vosk model ready: {path.name}")
    except Exception as exc:
        print(
            f"[stt] Auto-download failed: {exc}. "
            "Run the Setup Wizard or manually place the model at "
            f"{path}"
        )
        try:
            zip_path.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Model singleton
# ---------------------------------------------------------------------------

def _get_model() -> "Model":
    global _model
    if not _VOSK_AVAILABLE:
        raise RuntimeError(
            "[SYS] FATAL: Run 'pip install vosk sounddevice' in your terminal."
        )
    if _model is None:
        _ensure_model()
        path = _resolve_model_path()
        if not path.exists():
            raise FileNotFoundError(
                f"Vosk model not found at {path} and auto-download failed. "
                "Run setup_utility.py to retry."
            )
        print(f"[stt] Loading Vosk model: {path.name}")
        _model = Model(str(path))
        print("[stt] Vosk ready.")
    return _model


def prewarm() -> None:
    """Load the Vosk model now so the first transcription is instant."""
    _get_model()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def transcribe(audio: np.ndarray) -> str:
    """
    Transcribe a numpy array (16 kHz mono) to text.

    Accepts float32 in [-1, 1] or int16 directly.
    Returns an empty string if the audio is too short, silent, or if
    Vosk is unavailable.
    """
    if not _VOSK_AVAILABLE:
        return ""
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
