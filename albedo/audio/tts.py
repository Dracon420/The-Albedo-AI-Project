"""
Text-to-speech via Piper (subprocess) with sounddevice playback.

Setup:
  1. Download the Piper binary for Windows:
       https://github.com/rhasspy/piper/releases
  2. Voice models are downloaded automatically by setup_utility.py into
       <project_root>/voices/
     or set PIPER_VOICE_CORTANA / PIPER_VOICE_JARVIS in your .env.
  3. Set PIPER_BINARY in your .env (or accept the default C:\\piper\\piper.exe).

Piper runs on CPU so it uses zero VRAM -- keeps the RTX 2060 budget clean.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import sounddevice as sd
import soundfile as sf
import numpy as np
from albedo.config import PIPER_BINARY, PIPER_VOICE_MODEL, AUDIO_SAMPLE_RATE

# ---------------------------------------------------------------------------
# Markdown sanitiser — strips formatting tokens before sending text to Piper.
# Piper reads every character literally, so **bold** would be spoken as
# "asterisk asterisk bold asterisk asterisk".
# ---------------------------------------------------------------------------
_MD_LINK      = re.compile(r'!\[([^\]]*)\]\([^)]*\)')          # ![alt](url) → ''
_MD_LINK2     = re.compile(r'\[([^\]]+)\]\([^)]*\)')            # [text](url) → text
_MD_BARE_LINK = re.compile(r'\[([^\]]*)\]')                     # [text] → text
_MD_CODE_BLK  = re.compile(r'```[\s\S]*?```')                   # fenced code → ''
_MD_CODE_INL  = re.compile(r'`([^`]*)`')                        # `code` → code
_MD_BOLD_IT   = re.compile(r'\*{1,3}([^*\n]*)\*{1,3}')         # ***/**/*, → text
_MD_UNDER     = re.compile(r'_{1,3}([^_\n]*)_{1,3}')           # ___/__/_, → text
_MD_HEADER    = re.compile(r'^#{1,6}\s+', re.MULTILINE)         # ## Header → text
_MD_BULLET    = re.compile(r'^\s*[-*+]\s+', re.MULTILINE)       # - item → text
_MD_BLOCKQUOTE = re.compile(r'^\s*>\s*', re.MULTILINE)          # > text → text
_MD_HR        = re.compile(r'^[-*_]{3,}\s*$', re.MULTILINE)     # --- → ''
_MD_SPACES    = re.compile(r'\n{3,}')                           # collapse blank lines


def _sanitize_for_tts(text: str) -> str:
    """Strip all markdown formatting so Piper speaks clean prose."""
    text = _MD_LINK.sub('', text)
    text = _MD_LINK2.sub(r'\1', text)
    text = _MD_BARE_LINK.sub(r'\1', text)
    text = _MD_CODE_BLK.sub('', text)
    text = _MD_CODE_INL.sub(r'\1', text)
    text = _MD_BOLD_IT.sub(r'\1', text)
    text = _MD_UNDER.sub(r'\1', text)
    text = _MD_HEADER.sub('', text)
    text = _MD_BULLET.sub('', text)
    text = _MD_BLOCKQUOTE.sub('', text)
    text = _MD_HR.sub('', text)
    text = _MD_SPACES.sub('\n\n', text)
    return text.strip()

# Cache only the binary check -- voice model varies per persona call.
_piper_binary_ok: bool | None = None


def _check_piper_binary() -> bool:
    global _piper_binary_ok
    if _piper_binary_ok is None:
        _piper_binary_ok = os.path.isfile(PIPER_BINARY)
        if not _piper_binary_ok:
            print(
                f"[tts] Piper binary not found at {PIPER_BINARY!r}. "
                "TTS will print to console instead. "
                "See .env.example for setup instructions."
            )
    return _piper_binary_ok


def _resolve_voice(voice_model: str | None) -> str:
    """Return the voice model path to use, falling back to PIPER_VOICE_MODEL."""
    return voice_model if voice_model else PIPER_VOICE_MODEL


def speak(text: str, device: int | None = None,
          voice_model: str | None = None) -> None:
    """Synthesise text and play audio.

    device:      sounddevice output device index, or None for system default.
    voice_model: path to .onnx voice file.  None → use PIPER_VOICE_MODEL.
    Falls back to print() if Piper binary or voice model is unavailable.
    """
    text = _sanitize_for_tts(text)
    if not text:
        return

    if not _check_piper_binary():
        print(f"[Albedo] {text}")
        return

    model = _resolve_voice(voice_model)
    if not os.path.isfile(model):
        print(f"[tts] Voice model not found: {model!r} -- falling back to console.")
        print(f"[Albedo] {text}")
        return

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [PIPER_BINARY, "--model", model, "--output_file", tmp_path],
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
            from scipy.signal import resample
            samples = int(len(audio) * AUDIO_SAMPLE_RATE / sr)
            audio = resample(audio, samples).astype(np.float32)

        sd.play(audio, samplerate=AUDIO_SAMPLE_RATE, blocking=True, device=device)

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def synthesize_to_bytes(text: str,
                        voice_model: str | None = None) -> bytes | None:
    """
    Run Piper and return the raw WAV file as bytes.
    Used by the FastAPI server so the mobile client can play audio remotely.
    Returns None if Piper is not installed or the voice model is missing.
    """
    text = _sanitize_for_tts(text)
    if not text or not _check_piper_binary():
        return None

    model = _resolve_voice(voice_model)
    if not os.path.isfile(model):
        print(f"[tts] Voice model not found: {model!r}")
        return None

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [PIPER_BINARY, "--model", model, "--output_file", tmp_path],
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
