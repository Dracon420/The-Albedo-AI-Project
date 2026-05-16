"""
Text-to-speech with Edge-TTS (primary) and Piper (offline fallback).

Primary path — Edge-TTS:
  Streams audio from Microsoft's TTS cloud service using the edge-tts
  library.  No API key required; requires an internet connection.
  Voice quality is significantly higher than local Piper synthesis.

Fallback path — Piper (subprocess):
  If edge-tts fails for any reason (no internet, library absent, decode
  error) the call transparently retries via the local Piper binary.
  Piper runs on CPU so it uses zero VRAM — keeps the RTX 2060 clean.

Streaming TTS:
  speak_streamed() splits the response into sentences and pipelines
  synthesis with playback: a producer thread synthesizes sentence N+1
  while the consumer plays sentence N through sounddevice.  First audio
  starts as soon as the opening sentence finishes synthesis.

Setup (Piper fallback):
  1. Download the Piper binary for Windows:
       https://github.com/rhasspy/piper/releases
  2. Voice models are downloaded automatically by setup_utility.py into
       <project_root>/voices/
  3. Set PIPER_BINARY in your .env (or accept the default).
"""
from __future__ import annotations

import asyncio
import io
import os
import queue
import re
import subprocess
import tempfile
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

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
    """Strip all markdown formatting so TTS speaks clean prose."""
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
    text = text.replace('\n\n', ' ').replace('\n', ' ')
    parts = _SENT_SPLIT.split(text)
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# Active-process tracker and stop flag (enables hard-kill on abort)
# ---------------------------------------------------------------------------

_active_proc: subprocess.Popen | None = None
_proc_lock   = threading.Lock()
_stop_event  = threading.Event()   # set by stop_audio(); cleared at each new utterance


def stop_audio() -> None:
    """
    Immediately halt all TTS activity — edge-tts synthesis queue, any active
    Piper subprocess, and sounddevice playback.  Safe to call from any thread.

    Sets _stop_event so the producer thread in speak_streamed() stops
    synthesising further sentences and the consumer loop exits after the
    current sd.play() returns (which sd.stop() unblocks instantly).
    """
    global _active_proc
    try:
        _stop_event.set()
        with _proc_lock:
            proc = _active_proc
        if proc is not None:
            proc.kill()
        sd.stop()
    except Exception as e:
        print(f"[tts] stop_audio error: {e}")


# ---------------------------------------------------------------------------
# Edge-TTS helpers (primary path)
# ---------------------------------------------------------------------------

# Map Piper model filename fragments → Edge-TTS voice names
_EDGE_VOICE_MAP: dict[str, str] = {
    "kristin": "en-US-AriaNeural",   # Cortana persona
    "ryan":    "en-US-GuyNeural",    # Jarvis persona
}
_EDGE_VOICE_DEFAULT = "en-US-AriaNeural"


def _piper_to_edge_voice(piper_model: str) -> str:
    """Derive an Edge-TTS voice name from a Piper .onnx model path."""
    stem = Path(piper_model).stem.lower()
    for fragment, voice in _EDGE_VOICE_MAP.items():
        if fragment in stem:
            return voice
    return _EDGE_VOICE_DEFAULT


async def _edge_collect_mp3(text: str, voice: str) -> bytes:
    import edge_tts as _et
    communicate = _et.Communicate(text, voice)
    buf = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.extend(chunk["data"])
    return bytes(buf)


def _edge_synthesize(text: str, voice: str) -> tuple[np.ndarray, int] | None:
    """
    Synthesize text via Edge-TTS and return (float32 audio, sample_rate).
    Returns None on any error so the caller can fall back to Piper.
    """
    try:
        loop = asyncio.new_event_loop()
        try:
            mp3_bytes = loop.run_until_complete(_edge_collect_mp3(text, voice))
        finally:
            loop.close()
        if not mp3_bytes:
            return None
        audio, sr = sf.read(io.BytesIO(mp3_bytes), dtype="float32")
        return audio, sr
    except Exception as exc:
        print(f"[tts] Edge-TTS error: {exc}")
        return None


# ---------------------------------------------------------------------------
# Piper helpers (fallback path)
# ---------------------------------------------------------------------------
_piper_binary_ok: bool | None = None


def _check_piper_binary() -> bool:
    global _piper_binary_ok
    if _piper_binary_ok is None:
        _piper_binary_ok = os.path.isfile(PIPER_BINARY)
        if not _piper_binary_ok:
            print(
                f"[tts] Piper binary not found at {PIPER_BINARY!r}. "
                "TTS will print to console if Edge-TTS also fails."
            )
    return _piper_binary_ok


def _resolve_voice(voice_model: str | None) -> str:
    return voice_model if voice_model else PIPER_VOICE_MODEL


def _resampled(audio: np.ndarray, sr: int) -> np.ndarray:
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


def _synthesize(text: str, model: str) -> tuple[np.ndarray, int] | None:
    """Run Piper for a single text fragment; returns (float32 audio, sr) or None."""
    global _active_proc
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
    proc: subprocess.Popen | None = None
    try:
        proc = subprocess.Popen(
            [PIPER_BINARY, "--model", model, "--output_file", tmp_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        with _proc_lock:
            _active_proc = proc

        try:
            _, stderr_bytes = proc.communicate(
                input=text.encode("utf-8"), timeout=20
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return None

        if proc.returncode not in (0, -9, -15):
            print(f"[tts] Piper error: {stderr_bytes.decode().strip()}")
            return None
        if proc.returncode != 0:
            return None

        audio, sr = sf.read(tmp_path, dtype="float32")
        return audio, sr
    except Exception as exc:
        print(f"[tts] Piper synthesis error: {exc}")
        return None
    finally:
        with _proc_lock:
            if _active_proc is proc:
                _active_proc = None
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Unified synthesis — edge-tts with Piper fallback
# ---------------------------------------------------------------------------

def _synthesize_sentence(
    text: str,
    piper_model: str,
    edge_voice: str,
) -> tuple[np.ndarray, int] | None:
    """
    Try Edge-TTS first; fall back to Piper if edge-tts fails.
    Returns (float32 audio, sample_rate) or None if both fail.
    """
    result = _edge_synthesize(text, edge_voice)
    if result is not None:
        return result

    # Piper fallback
    if _check_piper_binary() and os.path.isfile(piper_model):
        return _synthesize(text, piper_model)

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def speak(text: str, device: int | None = None,
          voice_model: str | None = None) -> None:
    """
    Synthesise the full text and play it as one block.
    Kept for compatibility; prefer speak_streamed() for multi-sentence responses.
    """
    _stop_event.clear()
    text = _sanitize_for_tts(text)
    if not text:
        return
    model      = _resolve_voice(voice_model)
    edge_voice = _piper_to_edge_voice(model)

    result = _synthesize_sentence(text, model, edge_voice)
    if result is None:
        print(f"[Albedo] {text}")
        return
    if _stop_event.is_set():
        return
    audio, sr = result
    sd.play(_resampled(audio, sr), samplerate=AUDIO_SAMPLE_RATE,
            blocking=True, device=device)


def speak_streamed(text: str, device: int | None = None,
                   voice_model: str | None = None) -> None:
    """
    Sentence-level streaming TTS with pipelined synthesis and playback.

    A producer thread synthesizes each sentence in order (edge-tts primary,
    Piper fallback) and enqueues the resulting audio array.  The main thread
    dequeues and plays each chunk immediately so first audio starts as soon
    as the opening sentence finishes synthesis.

    stop_audio() sets _stop_event which causes:
      - the producer to skip remaining sentences immediately
      - sd.stop() to unblock the current blocking sd.play()
      - the consumer loop to exit at the next iteration check
    """
    _stop_event.clear()
    text = _sanitize_for_tts(text)
    if not text:
        return
    model      = _resolve_voice(voice_model)
    edge_voice = _piper_to_edge_voice(model)

    sentences = _split_sentences(text)
    if not sentences:
        return

    if len(sentences) == 1:
        result = _synthesize_sentence(sentences[0], model, edge_voice)
        if result and not _stop_event.is_set():
            audio, sr = result
            sd.play(_resampled(audio, sr), samplerate=AUDIO_SAMPLE_RATE,
                    blocking=True, device=device)
        elif result is None:
            print(f"[Albedo] {text}")
        return

    audio_q: queue.Queue = queue.Queue(maxsize=2)

    def _producer() -> None:
        for sentence in sentences:
            if _stop_event.is_set():
                break
            if not sentence:
                continue
            audio_q.put(_synthesize_sentence(sentence, model, edge_voice))
        audio_q.put(None)  # sentinel always — consumer must see it

    threading.Thread(target=_producer, daemon=True).start()

    while True:
        item = audio_q.get()
        if item is None or _stop_event.is_set():
            break
        audio, sr = item
        if not _stop_event.is_set():
            sd.play(_resampled(audio, sr), samplerate=AUDIO_SAMPLE_RATE,
                    blocking=True, device=device)


def synthesize_to_bytes(text: str,
                        voice_model: str | None = None) -> bytes | None:
    """
    Run Piper and return raw WAV bytes.
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
            creationflags=subprocess.CREATE_NO_WINDOW,
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
