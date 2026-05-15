"""
Audio capture with energy-based VAD.

Provides two modes:
  - stream_chunks()   : yields numpy int16 chunks for the wake word loop
  - record_utterance(): records until VAD silence gate and returns full array

Sample-rate and channel resilience
------------------------------------
WASAPI exclusive mode (and some USB devices) reject arbitrary sample rates
or channel counts with PortAudio error -9997 / AUDCLNT_E_UNSUPPORTED_FORMAT.

AudioStream.start() probes the device's native format first, then:
  Attempt 1 -- 16 kHz / mono  (ideal for OpenWakeWord + Whisper)
  Attempt 2 -- native rate / native channels, then:
                 • multi-channel  → mean-mix to mono in callback
                 • wrong rate     → resample to 16 kHz in callback
                   (scipy.signal.resample if available, numpy interp fallback)

All downstream consumers (OpenWakeWord, Whisper) receive 16 kHz mono int16
regardless of what the hardware actually opened.
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
    """
    Downsample/upsample a mono float32 array.
    Uses scipy.signal.resample when available (better anti-aliasing);
    falls back to numpy linear interpolation (no extra dependency).
    """
    if from_rate == to_rate or len(audio) == 0:
        return audio
    n_out = max(1, int(round(len(audio) * to_rate / from_rate)))
    try:
        from scipy.signal import resample as _sp_resample
        return _sp_resample(audio, n_out).astype(np.float32)
    except ImportError:
        x_old = np.linspace(0.0, 1.0, len(audio))
        x_new = np.linspace(0.0, 1.0, n_out)
        return np.interp(x_new, x_old, audio).astype(np.float32)


def _query_native_format(device: int | None) -> tuple[int, int]:
    """Return (native_sample_rate, native_input_channels) for the given device."""
    try:
        dev_idx = device if device is not None else sd.default.device[0]
        info = sd.query_devices(dev_idx)
        rate = int(info.get("default_samplerate", 44100))
        channels = max(1, int(info.get("max_input_channels", 1)))
        return rate, channels
    except Exception:
        return 44100, 1


class AudioStream:
    """Continuous microphone capture shared between wake word and recording modes."""

    def __init__(self, device: int | None = None) -> None:
        self._queue: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None
        self._device = device
        self._native_rate: int = AUDIO_SAMPLE_RATE
        self._native_channels: int = 1

    def _callback(self, indata: np.ndarray, frames: int, time, status) -> None:
        audio = indata.copy()

        # Downmix multichannel to mono
        if audio.ndim > 1 and audio.shape[1] > 1:
            audio = audio.mean(axis=1)
        else:
            audio = np.squeeze(audio)

        # Resample to target 16 kHz if hardware opened at a different rate
        if self._native_rate != AUDIO_SAMPLE_RATE:
            audio = _resample(audio, self._native_rate, AUDIO_SAMPLE_RATE)

        int16 = (audio * 32767).astype(np.int16)
        with self._lock:
            self._queue.append(int16)

    def start(self) -> None:
        native_rate, native_ch = _query_native_format(self._device)

        # ── Attempt 1: ideal format (16 kHz / mono) ─────────────────────────
        try:
            self._native_rate = AUDIO_SAMPLE_RATE
            self._native_channels = 1
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
                f"[capture] 16 kHz / mono rejected ({pa_err}); "
                f"falling back to native {native_rate} Hz / {native_ch} ch..."
            )

        # ── Attempt 2: device's native format, resample/downmix in callback ─
        native_chunk = int(native_rate * AUDIO_CHUNK_MS / 1000)
        self._native_rate = native_rate
        self._native_channels = native_ch
        print(
            f"[capture] Opening stream at {native_rate} Hz / {native_ch} ch; "
            f"downmixing to mono and resampling to {AUDIO_SAMPLE_RATE} Hz in memory."
        )
        self._stream = sd.InputStream(
            samplerate=native_rate,
            channels=native_ch,
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
