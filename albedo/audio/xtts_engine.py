"""
albedo/audio/xtts_engine.py — XTTS-v2 local voice-clone TTS engine.

Tier 2 TTS (free, offline, voice-cloned):
  Coqui TTS XTTS-v2 can clone any voice from a 6-second WAV reference
  clip.  The model (1.8 GB) is downloaded automatically on first use
  (no account required).  Runs on CPU or CUDA; RTX 2060 w/ 6 GB VRAM
  can comfortably run it alongside Ollama at ~0.3x realtime on GPU.

Opt-in via .env:
    XTTS_VOICE_SAMPLE=C:/path/to/voice_ref.wav   # required to enable
    XTTS_DEVICE=cuda                              # or "cpu" (default: cuda if GPU)
    XTTS_MODEL_DIR=                               # override model cache dir

When XTTS_VOICE_SAMPLE is not set, every function returns None/False
gracefully so the TTS waterfall falls through to Edge-TTS.

Model download (~1.8 GB, one-time):
  The TTS library downloads to ~/.local/share/tts/tts_models--multilingual--...
  automatically.  No API key, no account.

Setup:
    pip install TTS          # Coqui TTS (installs torch if not present)
    # Record or clip a 6-second WAV of the voice you want to clone.
    # Set XTTS_VOICE_SAMPLE= to the path in .env.
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# Module-level singleton + availability flag
# ---------------------------------------------------------------------------
_tts_instance   = None      # TTS object, loaded lazily
_load_error: str | None = None
_available: bool | None = None   # None = not yet probed


def _voice_sample() -> str:
    return os.environ.get("XTTS_VOICE_SAMPLE", "").strip()


def is_available() -> bool:
    """
    Return True when:
      - XTTS_VOICE_SAMPLE env var points to an existing WAV file
      - The TTS (Coqui) package is importable
    Does NOT require the model to already be downloaded — it auto-downloads.
    Cheap; safe to call repeatedly.
    """
    global _available
    if _available is None:
        sample = _voice_sample()
        if not sample or not Path(sample).exists():
            _available = False
        else:
            try:
                import TTS  # noqa: F401
                _available = True
            except ImportError:
                _available = False
    return _available


def load_error() -> Optional[str]:
    """Return the last error string from a failed load attempt, or None."""
    return _load_error


def _get_tts():
    """Lazy-load the XTTS-v2 model. Cached for the process lifetime."""
    global _tts_instance, _load_error
    if _tts_instance is not None:
        return _tts_instance
    try:
        from TTS.api import TTS  # type: ignore[import]

        device = os.environ.get("XTTS_DEVICE", "").strip()
        if not device:
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"

        model_dir = os.environ.get("XTTS_MODEL_DIR", "").strip() or None

        print(f"[xtts] Loading XTTS-v2 on {device} (first run downloads ~1.8 GB)…")
        tts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2")
        tts = tts.to(device)
        _tts_instance = tts
        _load_error = None
        print("[xtts] XTTS-v2 ready.")
        return _tts_instance

    except Exception as exc:
        _load_error = str(exc)
        print(f"[xtts] Load failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------

def synthesize_to_bytes(
    text: str,
    language: str = "en",
) -> Optional[bytes]:
    """
    Synthesize *text* using XTTS-v2 with the configured voice sample.
    Returns raw WAV bytes (16-bit PCM) or None on any failure.

    Parameters
    ----------
    text     : str — text to synthesize (plain, no SSML)
    language : str — BCP-47 language code (default "en")
    """
    if not is_available() or not text:
        return None

    tts = _get_tts()
    if tts is None:
        return None

    sample = _voice_sample()
    if not sample or not Path(sample).exists():
        print(f"[xtts] Voice sample not found: {sample!r}")
        return None

    try:
        buf = io.BytesIO()
        tts.tts_to_file(
            text=text,
            speaker_wav=sample,
            language=language,
            file_path=buf,
        )
        buf.seek(0)
        return buf.read()
    except Exception as exc:
        print(f"[xtts] Synthesis error: {exc}")
        return None


def synthesize_to_numpy(
    text: str,
    language: str = "en",
) -> Optional[tuple[np.ndarray, int]]:
    """
    Returns (float32 audio, sample_rate) or None.
    The sample_rate is 24000 Hz (XTTS-v2 native output).
    The caller is responsible for resampling if needed.
    """
    wav = synthesize_to_bytes(text, language=language)
    if wav is None:
        return None
    try:
        import soundfile as sf
        audio, sr = sf.read(io.BytesIO(wav), dtype="float32")
        return audio, sr
    except Exception as exc:
        print(f"[xtts] WAV decode error: {exc}")
        return None


def preload() -> None:
    """
    Eagerly load the XTTS-v2 model so the first speak() call is fast.
    Silently skips if XTTS_VOICE_SAMPLE is not configured.
    """
    if is_available():
        _get_tts()
