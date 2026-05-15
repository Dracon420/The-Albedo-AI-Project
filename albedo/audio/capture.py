"""
Audio capture with energy-based VAD.

Provides two modes:
  - stream_chunks()   : yields numpy int16 chunks for the wake word loop
  - record_utterance(): records until VAD silence gate and returns full array

Three-attempt WASAPI / format resilience
-----------------------------------------
WASAPI exclusive mode and some USB devices reject arbitrary sample rates or
channel counts with PortAudio error -9997 / AUDCLNT_E_UNSUPPORTED_FORMAT.

AudioStream.start() escalates through three strategies before giving up:

  Attempt 1 -- 16 kHz / mono on the user-selected device (ideal for
               OpenWakeWord + Whisper).

  Attempt 2 -- Device's native sample rate + native channel count on the
               same device.  Callback downmixes to mono and resamples to
               16 kHz in memory (scipy if available, numpy interp fallback).

  Attempt 3 -- MME host API variant of the device.  MME is the oldest,
               most universally accepted Windows audio stack and almost
               never raises AUDCLNT_E_UNSUPPORTED_FORMAT.  The function
               _find_mme_device() locates the correct device index by
               matching the physical device name inside the MME host API.

All downstream consumers (OpenWakeWord, Whisper) always receive 16 kHz
mono int16 regardless of which attempt succeeded.
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resample(audio: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    """
    Resample mono float32 audio.
    scipy.signal.resample used when available (anti-aliased);
    numpy linear interp is the no-dependency fallback.
    """
    if from_rate == to_rate or len(audio) == 0:
        return audio
    n_out = max(1, int(round(len(audio) * to_rate / from_rate)))
    try:
        from scipy.signal import resample as _sp
        return _sp(audio, n_out).astype(np.float32)
    except ImportError:
        x_old = np.linspace(0.0, 1.0, len(audio))
        x_new = np.linspace(0.0, 1.0, n_out)
        return np.interp(x_new, x_old, audio).astype(np.float32)


def _query_native_format(device: int | None) -> tuple[int, int, str]:
    """Return (sample_rate, input_channels, device_name) for the given device."""
    try:
        dev_idx = device if device is not None else sd.default.device[0]
        info = sd.query_devices(dev_idx)
        rate     = int(info.get("default_samplerate", 44100))
        channels = max(1, int(info.get("max_input_channels", 1)))
        name     = info.get("name", "")
        return rate, channels, name
    except Exception:
        return 44100, 1, ""


def _find_mme_device(device_name: str) -> int | None:
    """
    Return the sounddevice index of the MME-hosted version of a named device.

    Windows exposes each physical audio device once per host API (MME,
    DirectSound, WASAPI …).  This function scans the device list for an
    input-capable device whose name matches and whose host API is MME.
    Returns None if MME is not present or no matching device is found.
    """
    try:
        hostapis = sd.query_hostapis()
        mme_idx  = next(
            (i for i, h in enumerate(hostapis) if "MME" in h.get("name", "")),
            None,
        )
        if mme_idx is None:
            return None
        for i, d in enumerate(sd.query_devices()):
            if (d["hostapi"] == mme_idx
                    and d["max_input_channels"] > 0
                    and d["name"] == device_name):
                return i
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# AudioStream
# ---------------------------------------------------------------------------

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

        # Downmix multichannel → mono
        if audio.ndim > 1 and audio.shape[1] > 1:
            audio = audio.mean(axis=1)
        else:
            audio = np.squeeze(audio)

        # Resample to 16 kHz if hardware opened at a different rate
        if self._native_rate != AUDIO_SAMPLE_RATE:
            audio = _resample(audio, self._native_rate, AUDIO_SAMPLE_RATE)

        int16 = (audio * 32767).astype(np.int16)
        with self._lock:
            self._queue.append(int16)

    def _open_stream(self, samplerate: int, channels: int,
                     blocksize: int, device: int | None) -> None:
        """Open and start an InputStream with the given parameters."""
        self._stream = sd.InputStream(
            samplerate=samplerate,
            channels=channels,
            dtype="float32",
            blocksize=blocksize,
            callback=self._callback,
            device=device,
        )
        self._stream.start()

    def start(self) -> None:
        native_rate, native_ch, dev_name = _query_native_format(self._device)

        # ── Attempt 1: ideal format (16 kHz / mono) ─────────────────────────
        try:
            self._native_rate    = AUDIO_SAMPLE_RATE
            self._native_channels = 1
            self._open_stream(AUDIO_SAMPLE_RATE, 1, _CHUNK_SAMPLES, self._device)
            return
        except sd.PortAudioError as e1:
            print(
                f"[capture] Attempt 1 failed (16 kHz / mono): {e1}\n"
                f"[capture] Trying native format {native_rate} Hz / {native_ch} ch..."
            )

        # ── Attempt 2: native rate + native channels; resample in callback ───
        try:
            native_block          = int(native_rate * AUDIO_CHUNK_MS / 1000)
            self._native_rate     = native_rate
            self._native_channels = native_ch
            self._open_stream(native_rate, native_ch, native_block, self._device)
            print(
                f"[capture] Stream open at {native_rate} Hz / {native_ch} ch "
                f"(resampling + downmix active)."
            )
            return
        except sd.PortAudioError as e2:
            print(
                f"[capture] Attempt 2 failed (native format): {e2}\n"
                "[capture] Trying MME host API fallback..."
            )

        # ── Attempt 3: MME host API — most compatible Windows audio stack ────
        mme_dev = _find_mme_device(dev_name)
        if mme_dev is not None:
            try:
                self._native_rate     = AUDIO_SAMPLE_RATE
                self._native_channels = 1
                self._open_stream(AUDIO_SAMPLE_RATE, 1, _CHUNK_SAMPLES, mme_dev)
                self._device = mme_dev  # persist so future restarts reuse MME
                print(f"[capture] Stream open via MME fallback (device index {mme_dev}).")
                return
            except sd.PortAudioError as e3:
                print(f"[capture] Attempt 3 failed (MME): {e3}")
        else:
            print("[capture] MME host API not found on this system.")

        raise RuntimeError(
            "AudioStream.start(): all three attempts to open the microphone "
            "failed. Check HARDWARE settings and select a different input device."
        )

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


# ---------------------------------------------------------------------------
# VAD recording
# ---------------------------------------------------------------------------

def record_utterance(stream: AudioStream) -> np.ndarray:
    """
    Collect audio from stream until VAD_SILENCE_DURATION of quiet or
    VAD_MAX_RECORD_SECONDS elapsed. Returns a float32 array at AUDIO_SAMPLE_RATE.
    """
    stream.drain()
    frames: list[np.ndarray] = []
    silence_samples = 0
    silence_gate = int(VAD_SILENCE_DURATION * AUDIO_SAMPLE_RATE / _CHUNK_SAMPLES)
    max_chunks   = int(VAD_MAX_RECORD_SECONDS * AUDIO_SAMPLE_RATE / _CHUNK_SAMPLES)

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

    return np.concatenate(frames).astype(np.float32) / 32767
