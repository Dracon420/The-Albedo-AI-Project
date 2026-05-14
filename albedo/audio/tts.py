"""
Text-to-speech via Piper (subprocess) with sounddevice playback.

Setup:
  1. Download the Piper binary for Windows:
       https://github.com/rhasspy/piper/releases
  2. Download a voice model (.onnx + .onnx.json):
       https://huggingface.co/rhasspy/piper-voices
     Recommended for low latency: en_US-ryan-high  or  en_US-amy-medium
  3. Set PIPER_BINARY and PIPER_VOICE_MODEL in your .env

Piper runs on CPU so it uses zero VRAM -- keeps the RTX 2060 budget clean.
"""
from __future__ import annotations

import subprocess
import tempfile
import os
import sounddevice as sd
import soundfile as sf
import numpy as np
from albedo.config import PIPER_BINARY, PIPER_VOICE_MODEL, AUDIO_SAMPLE_RATE

_piper_available: bool | None = None


def _check_piper() -> bool:
    global _piper_available
    if _piper_available is None:
        _piper_available = os.path.isfile(PIPER_BINARY) and os.path.isfile(PIPER_VOICE_MODEL)
        if not _piper_available:
            print(
                f"[tts] Piper not found at {PIPER_BINARY!r}. "
                "TTS will print to console instead. "
                "See .env.example for setup instructions."
            )
    return _piper_available


def speak(text: str, device: int | None = None) -> None:
    """Synthesise text and play audio. Falls back to print if Piper is unavailable.

    device: sounddevice output device index, or None for system default.
    """
    text = text.strip()
    if not text:
        return

    if not _check_piper():
        print(f"[Albedo] {text}")
        return

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [
                PIPER_BINARY,
                "--model", PIPER_VOICE_MODEL,
                "--output_file", tmp_path,
            ],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=15,
        )
        if result.returncode != 0:
            print(f"[tts] Piper error: {result.stderr.decode()}")
            print(f"[Albedo] {text}")
            return

        audio, sr = sf.read(tmp_path, dtype="float32")
        if sr != AUDIO_SAMPLE_RATE:
            # Resample to 16 kHz if the voice model outputs a different rate
            from scipy.signal import resample
            samples = int(len(audio) * AUDIO_SAMPLE_RATE / sr)
            audio = resample(audio, samples).astype(np.float32)

        sd.play(audio, samplerate=AUDIO_SAMPLE_RATE, blocking=True, device=device)

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def synthesize_to_bytes(text: str) -> bytes | None:
    """
    Run Piper and return the raw WAV file as bytes.
    Used by the FastAPI server so the mobile client can play audio remotely.
    Returns None if Piper is not installed.
    """
    text = text.strip()
    if not text or not _check_piper():
        return None

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [PIPER_BINARY, "--model", PIPER_VOICE_MODEL, "--output_file", tmp_path],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=15,
        )
        if result.returncode != 0:
            print(f"[tts] Piper error: {result.stderr.decode()}")
            return None
        with open(tmp_path, "rb") as fh:
            return fh.read()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
