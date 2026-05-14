"""
Audio capture with energy-based VAD.

Provides two modes:
  - stream_chunks()   : yields numpy int16 chunks for the wake word loop
  - record_utterance(): records until VAD silence gate and returns full array
"""
from __future__ import annotations

import threading
import numpy as np
import sounddevice as sd
from albedo.config import (
    AUDIO_SAMPLE_RATE,
    AUDIO_CHUNK_MS,
    VAD_SILENCE_THRESHOLD,
    VAD_SILENCE_DURATION,
    VAD_MAX_RECORD_SECONDS,
)

_CHUNK_SAMPLES = int(AUDIO_SAMPLE_RATE * AUDIO_CHUNK_MS / 1000)  # 1280 @ 16kHz/80ms


class AudioStream:
    """Continuous microphone capture shared between wake word and recording modes."""

    def __init__(self):
        self._queue: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None

    def _callback(self, indata: np.ndarray, frames: int, time, status) -> None:
        audio = np.squeeze(indata.copy())
        int16 = (audio * 32767).astype(np.int16)
        with self._lock:
            self._queue.append(int16)

    def start(self) -> None:
        self._stream = sd.InputStream(
            samplerate=AUDIO_SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=_CHUNK_SAMPLES,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def read_chunk(self) -> np.ndarray | None:
        with self._lock:
            return self._queue.pop(0) if self._queue else None

    def drain(self) -> None:
        with self._lock:
            self._queue.clear()


def record_utterance(stream: AudioStream) -> np.ndarray:
    """
    Collect audio from stream until VAD_SILENCE_DURATION of quiet or
    VAD_MAX_RECORD_SECONDS elapsed. Returns a float32 array at AUDIO_SAMPLE_RATE.
    """
    stream.drain()
    frames: list[np.ndarray] = []
    silence_samples = 0
    silence_gate = int(VAD_SILENCE_DURATION * AUDIO_SAMPLE_RATE / _CHUNK_SAMPLES)
    max_chunks = int(VAD_MAX_RECORD_SECONDS * AUDIO_SAMPLE_RATE / _CHUNK_SAMPLES)

    while len(frames) < max_chunks:
        chunk = stream.read_chunk()
        if chunk is None:
            sd.sleep(10)
            continue

        frames.append(chunk)
        rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2))) / 32767
        if rms < VAD_SILENCE_THRESHOLD:
            silence_samples += 1
            if silence_samples >= silence_gate:
                break
        else:
            silence_samples = 0

    if not frames:
        return np.zeros(0, dtype=np.float32)

    raw = np.concatenate(frames).astype(np.float32) / 32767
    return raw
