"""
Text-to-speech via Piper (subprocess) with sounddevice playback.

Setup:
  1. Download the Piper binary for Windows:
       https://github.com/rhasspy/piper/releases
  2. Voice models are downloaded automatically by setup_utility.py into
       <project_root>/voices/
     or set PIPER_VOICE_CORTANA / PIPER_VOICE_JARVIS in your .env.
  3. Set PIPER_BINARY in your .env (or accept the default).

Piper runs on CPU so it uses zero VRAM -- keeps the RTX 2060 budget clean.

Streaming TTS
-------------
speak_streamed() splits the response into sentences and pipelines synthesis
with playback: a producer thread synthesizes sentence N+1 via Piper while
the consumer plays sentence N through sounddevice.  First audio starts as
soon as Piper finishes the opening sentence, with no wait for the rest.
"""
from __future__ import annotations

import os
import queue
import re
import subprocess
import tempfile
import threading
import sounddevice as sd
import soundfile as sf
import numpy as np
from albedo.config import PIPER_BINARY, PIPER_VOICE_MODEL, AUDIO_SAMPLE_RATE

# ---------------------------------------------------------------------------
# Markdown sanitiser
# ---------------------------------------------------------------------------
_MD_IMG       = re.compile(r'!\[[^\]]*\]\([^)]*\)')
_MD_LINK      = re.compile(r'\[([^\]]+)\]\([^)]*\)')
_MD_BARE_LINK = re.compile(r'\[([^\]]*)\]')
_MD_CODE_BLK  = re.compile(r'```[\s\S]*?```')
_MD_CODE_INL  = re.compile(r'`([^`]*)`')
_MD_BOLD_IT   = re.compile(r'\*{1,3}([^*\n]*)\*{1,3}')
_MD_UNDER     = re.compile(r'_{1,3}([^_\n]*)_{1,3}')
_MD_HEADER    = re.compile(r'^#{1,6}\s+', re.MULTILINE)
_MD_BULLET    = re.compile(r'^\s*[-*+]\s+', re.MULTILINE)
_MD_BLOCKQUOT = re.compile(r'^\s*>\s*', re.MULTILINE)
_MD_HR        = re.compile(r'^[-*_]{3,}\s*$', re.MULTILINE)
_MD_BLANKS    = re.compile(r'\n{3,}')


def _sanitize_for_tts(text: str) -> str:
    """Strip all markdown formatting so Piper speaks clean prose."""
    text = _MD_IMG.sub('', text)
    text = _MD_LINK.sub(r'\1', text)
    text = _MD_BARE_LINK.sub(r'\1', text)
    text = _MD_CODE_BLK.sub('', text)
    text = _MD_CODE_INL.sub(r'\1', text)
    text = _MD_BOLD_IT.sub(r'\1', text)
    text = _MD_UNDER.sub(r'\1', text)
    text = _MD_HEADER.sub('', text)
    text = _MD_BULLET.sub('', text)
    text = _MD_BLOCKQUOT.sub('', text)
    text = _MD_HR.sub('', text)
    text = _MD_BLANKS.sub('\n\n', text)
    return text.strip()


# ---------------------------------------------------------------------------
# Sentence splitter
# ---------------------------------------------------------------------------
_SENT_SPLIT = re.compile(r'(?<=[.!?])\s+')


def _split_sentences(text: str) -> list[str]:
    """
    Split text on sentence-ending punctuation followed by whitespace.
    Newlines are normalised to a single space first so paragraph breaks
    don't create empty chunks.
    """
    text = text.replace('\n\n', ' ').replace('\n', ' ')
    parts = _SENT_SPLIT.split(text)
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# Binary / voice checks
# ---------------------------------------------------------------------------
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
    return voice_model if voice_model else PIPER_VOICE_MODEL


def _resampled(audio: np.ndarray, sr: int) -> np.ndarray:
    """Resample to AUDIO_SAMPLE_RATE if needed."""
    if sr == AUDIO_SAMPLE_RATE:
        return audio
    try:
        from scipy.signal import resample as _sp
        n = int(len(audio) * AUDIO_SAMPLE_RATE / sr)
        return _sp(audio, n).astype(np.float32)
    except ImportError:
        n = int(len(audio) * AUDIO_SAMPLE_RATE / sr)
        x_old = np.linspace(0.0, 1.0, len(audio))
        x_new = np.linspace(0.0, 1.0, n)
        return np.interp(x_new, x_old, audio).astype(np.float32)


# ---------------------------------------------------------------------------
# Core synthesis helper (one sentence → (audio, sr) or None)
# ---------------------------------------------------------------------------

def _synthesize(text: str, model: str) -> tuple[np.ndarray, int] | None:
    """Run Piper for a single text fragment and return (float32 audio, sr)."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        proc = subprocess.run(
            [PIPER_BINARY, "--model", model, "--output_file", tmp_path],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=20,
        )
        if proc.returncode != 0:
            print(f"[tts] Piper error: {proc.stderr.decode().strip()}")
            return None
        audio, sr = sf.read(tmp_path, dtype="float32")
        return audio, sr
    except Exception as exc:
        print(f"[tts] Synthesis error: {exc}")
        return None
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def speak(text: str, device: int | None = None,
          voice_model: str | None = None) -> None:
    """
    Synthesise the full text and play it as one block.
    Kept for compatibility; prefer speak_streamed() for multi-sentence responses.
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

    result = _synthesize(text, model)
    if result is None:
        print(f"[Albedo] {text}")
        return
    audio, sr = result
    sd.play(_resampled(audio, sr), samplerate=AUDIO_SAMPLE_RATE,
            blocking=True, device=device)


def speak_streamed(text: str, device: int | None = None,
                   voice_model: str | None = None) -> None:
    """
    Sentence-level streaming TTS with pipelined synthesis and playback.

    A producer thread synthesizes each sentence in order via Piper and
    enqueues the resulting audio array.  The main (caller) thread dequeues
    and plays each chunk immediately, so first audio starts as soon as the
    opening sentence is synthesized — without waiting for the whole response.

    Falls back to plain speak() for single-sentence responses.
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

    sentences = _split_sentences(text)
    if not sentences:
        return

    # Single sentence: no pipelining overhead needed
    if len(sentences) == 1:
        result = _synthesize(sentences[0], model)
        if result:
            audio, sr = result
            sd.play(_resampled(audio, sr), samplerate=AUDIO_SAMPLE_RATE,
                    blocking=True, device=device)
        else:
            print(f"[Albedo] {text}")
        return

    # Multiple sentences: producer synthesizes ahead, consumer plays
    # maxsize=2 keeps one chunk ready while the current one plays.
    audio_q: queue.Queue = queue.Queue(maxsize=2)

    def _producer() -> None:
        for sentence in sentences:
            if not sentence:
                continue
            item = _synthesize(sentence, model)
            audio_q.put(item)   # None means Piper failed for this sentence
        audio_q.put(None)       # sentinel

    threading.Thread(target=_producer, daemon=True).start()

    while True:
        item = audio_q.get()
        if item is None:
            break
        audio, sr = item
        sd.play(_resampled(audio, sr), samplerate=AUDIO_SAMPLE_RATE,
                blocking=True, device=device)


def synthesize_to_bytes(text: str,
                        voice_model: str | None = None) -> bytes | None:
    """
    Run Piper and return the raw WAV bytes.
    Used by the FastAPI server for mobile client audio delivery.
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
        proc = subprocess.run(
            [PIPER_BINARY, "--model", model, "--output_file", tmp_path],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=15,
        )
        if proc.returncode != 0:
            print(f"[tts] Piper error: {proc.stderr.decode().strip()}")
            return None
        with open(tmp_path, "rb") as fh:
            return fh.read()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
