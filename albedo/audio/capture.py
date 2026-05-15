"""
Audio capture with energy-based VAD.

Provides two modes:
  - stream_chunks()   : yields numpy int16 chunks for the wake word loop
  - record_utterance(): records until VAD silence gate and returns full array

Sample-rate resilience
----------------------
Some devices (USB headsets, HDMI audio) reject 16 kHz with PortAudio error
-9997 (Invalid Sample Rate).  AudioStream.start() tries 16 kHz first; on
failure it re-opens at the device's native rate and resamples each chunk to
16 kHz in the callback using numpy linear interpolation before queuing.
This keeps all downstream consumers (OpenWakeWord, Whisper) blissfully
unaware that a resampler exists.
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


def _resample(audio: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    """Linear interpolation resample — no scipy dependency required."""
    if from_rate == to_rate or len(audio) == 0:
        return audio
    n_out = max(1, int(round(len(audio) * to_rate / from_rate)))
    x_old = np.linspace(0.0, 1.0, len(audio))
    x_new = np.linspace(0.0, 1.0, n_out)
    return np.interp(x_new, x_old, audio).astype(audio.dtype)


class AudioStream:
    """Continuous microphone capture shared between wake word and recording modes."""

    def __init__(self, device: int | None = None) -> None:
        self._queue: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None
        self._device = device          # None = sounddevice default
        self._native_rate: int = AUDIO_SAMPLE_RATE  # updated if resampling needed

    def _callback(self, indata: np.ndarray, frames: int, time, status) -> None:
        audio = np.squeeze(indata.copy())
        if self._native_rate != AUDIO_SAMPLE_RATE:
            audio = _resample(audio, self._native_rate, AUDIO_SAMPLE_RATE)
        int16 = (audio * 32767).astype(np.int16)
        with self._lock:
            self._queue.append(int16)

    def start(self) -> None:
        # ── Attempt 1: native 16 kHz (OpenWakeWord / Whisper requirement) ──
        try:
            self._native_rate = AUDIO_SAMPLE_RATE
            self._stream = sd.InputStream(
                samplerate=AUDIO_SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=_CHUNK_SAMPLES,
                callback=self._callback,
                device=self._device,
            )
            self._stream.start()
            return
        except sd.PortAudioError as pa_err:
            print(
                f"[capture] Device rejected {AUDIO_SAMPLE_RATE} Hz "
                f"({pa_err}); probing native rate..."
            )

        # ── Attempt 2: device's native rate + resample in callback ──────────
        try:
            dev_idx = self._device if self._device is not None else sd.default.device[0]
            info = sd.query_devices(dev_idx)
            native = int(info.get("default_samplerate", 44100))
        except Exception:
            native = 44100

        native_chunk = int(native * AUDIO_CHUNK_MS / 1000)
        self._native_rate = native
        print(
            f"[capture] Capturing at {native} Hz and resampling to "
            f"{AUDIO_SAMPLE_RATE} Hz in memory."
        )
        self._stream = sd.InputStream(
            samplerate=native,
            channels=1,
            dtype="float32",
            blocksize=native_chunk,
            callback=self._callback,
            device=self._device,
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
