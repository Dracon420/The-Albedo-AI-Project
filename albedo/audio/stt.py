"""
Speech-to-text — tiered waterfall (highest accuracy → offline fallback).

Engine waterfall (controlled by AUDIO_STT in .env):

  "azure"    Tier 0 — Azure Speech STT (cloud, 5 h/month free)
             Requires: AZURE_SPEECH_KEY + AZURE_SPEECH_REGION
             Falls through to Groq Whisper → Vosk on failure.

  "groq"     Tier 1 — Groq Whisper API (cloud, free tier generous)
             Requires: GROQ_API_KEY
             Falls through to Vosk on failure.

  "deepgram" Tier 2 — Deepgram cloud STT (existing engine)
             Requires: DEEPGRAM_API_KEY

  "whisper"  Tier 3 — distil-whisper offline (existing engine)

  "vosk"     Tier 4 — Vosk offline Kaldi (default, always works)
             No key, no internet, ~40 MB model auto-downloaded.

The default is "vosk" for zero-dependency offline operation.
Set AUDIO_STT=azure or AUDIO_STT=groq to enable cloud tiers.
"""
from __future__ import annotations

import json
import os
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


def _short_path(path: Path) -> str:
    """Return the Windows 8.3 short path to avoid spaces breaking Vosk/Kaldi."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(512)
        if ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, 512):
            return buf.value
    except Exception:
        pass
    return str(path)

_model: "Model | None" = None


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _resolve_model_path() -> Path:
    return Path(VOSK_MODEL_PATH).expanduser()


def _model_valid(path: Path) -> bool:
    """Check that the model directory has the minimum required files."""
    return (path / "am" / "final.mdl").exists() and (path / "conf" / "model.conf").exists()


def is_cached() -> bool:
    """True if the Vosk model directory exists and contains valid model files."""
    path = _resolve_model_path()
    return path.exists() and _model_valid(path)


# ---------------------------------------------------------------------------
# Auto-download
# ---------------------------------------------------------------------------

def _ensure_model() -> None:
    """Download and extract the Vosk model if it is absent or incomplete."""
    path = _resolve_model_path()
    if path.exists() and _model_valid(path):
        return
    # Directory exists but is corrupt/incomplete — remove it before re-downloading.
    if path.exists():
        import shutil
        print("[stt] Vosk model directory found but incomplete — removing and re-downloading...")
        shutil.rmtree(path, ignore_errors=True)

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
        import time as _time
        for _attempt in range(5):
            if path.exists():
                break
            _time.sleep(1)
        if not path.exists():
            raise FileNotFoundError(
                f"Vosk model not found at {path} and auto-download failed. "
                "Run setup_utility.py to retry."
            )
        print(f"[stt] Loading Vosk model: {path.name}")
        _model = Model(_short_path(path))
        print("[stt] Vosk ready.")
    return _model


def prewarm() -> None:
    """
    Load the active STT engine so the first transcribe() call is fast.

    Routes by AUDIO_STT env var — same dispatch as transcribe(). For Vosk
    this loads the Kaldi model; for Deepgram it does nothing (cloud is
    stateless); for whisper-direct it loads the WhisperModel.
    """
    engine = _active_stt_engine()
    if engine == "vosk":
        _get_model()
    elif engine == "whisper":
        from albedo.audio import stt_whisper
        stt_whisper.prewarm()
    # deepgram / router need no prewarm — REST cloud calls are stateless.
    # whisper prewarm under the router happens lazily on first failover.


# ---------------------------------------------------------------------------
# Engine dispatcher (Phase 4 N+2)
#
# AUDIO_STT controls which engine the public transcribe() routes to.
# Default "vosk" preserves v2.0.2 behaviour exactly — no v2.x install
# is affected until the user opts in.
#
#   AUDIO_STT=vosk     -> _transcribe_vosk() — the original code below
#   AUDIO_STT=deepgram -> stt_router.transcribe() — Deepgram with whisper fallback
#   AUDIO_STT=whisper  -> stt_whisper.transcribe() — offline-only, skip cloud
# ---------------------------------------------------------------------------

def _active_stt_engine() -> str:
    """Read AUDIO_STT at call time so .env edits take effect on next call."""
    return (os.environ.get("AUDIO_STT", "vosk") or "vosk").strip().lower()


# ---------------------------------------------------------------------------
# Tier 0: Azure Speech STT
# ---------------------------------------------------------------------------

def _transcribe_azure(audio: np.ndarray) -> str:
    """
    Transcribe via Azure Speech STT.
    Returns the transcript or "" — never raises.
    Falls back silently if SDK/key not available.
    """
    try:
        from albedo.audio.azure_speech import is_available as _az_ok, transcribe as _az_tr
        if not _az_ok():
            return ""
        return _az_tr(audio, sample_rate=AUDIO_SAMPLE_RATE)
    except Exception as exc:
        print(f"[stt] Azure STT error: {exc}")
        return ""


# ---------------------------------------------------------------------------
# Tier 1: Groq Whisper STT
# ---------------------------------------------------------------------------

def _transcribe_groq_whisper(audio: np.ndarray) -> str:
    """
    Transcribe via Groq Whisper API (whisper-large-v3-turbo).
    Returns the transcript or "" — never raises.
    Requires GROQ_API_KEY in .env.
    """
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not groq_key:
        return ""
    if audio is None or len(audio) == 0:
        return ""
    try:
        import io as _io
        import wave as _wave
        import numpy as _np
        from groq import Groq as _Groq

        # Float32 → int16 WAV in memory
        pcm = (_np.clip(audio, -1.0, 1.0) * 32767).astype(_np.int16)
        buf = _io.BytesIO()
        with _wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(AUDIO_SAMPLE_RATE)
            wf.writeframes(pcm.tobytes())
        buf.seek(0)

        client = _Groq(api_key=groq_key)
        result = client.audio.transcriptions.create(
            model="whisper-large-v3-turbo",
            file=("audio.wav", buf, "audio/wav"),
            language="en",
        )
        return (result.text or "").strip()
    except Exception as exc:
        print(f"[stt] Groq Whisper error: {exc}")
        return ""


def _transcribe_vosk(audio: np.ndarray) -> str:
    """The original Vosk-based transcribe(). Preserved verbatim under the dispatcher."""
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


# ---------------------------------------------------------------------------
# Public API — dispatcher routes to the engine selected by AUDIO_STT
# ---------------------------------------------------------------------------

def transcribe(audio: np.ndarray) -> str:
    """
    Transcribe a numpy audio buffer to text.

    Engine selection follows AUDIO_STT (read at every call so .env edits
    apply on the next request without a restart):

      azure    -> Azure Speech STT → Groq Whisper fallback → Vosk fallback
      groq     -> Groq Whisper API → Vosk fallback
      deepgram -> stt_router.transcribe() (Deepgram -> whisper failover)
      whisper  -> stt_whisper.transcribe() (offline-only)
      vosk     -> _transcribe_vosk() (the original v2.x path, default)

    Returns the transcript or an empty string. Never raises.
    """
    engine = _active_stt_engine()

    # ── Tier 0: Azure Speech STT ─────────────────────────────────────────────
    if engine == "azure":
        result = _transcribe_azure(audio)
        if result:
            return result
        # Cascade: try Groq Whisper then Vosk
        print("[stt] Azure STT returned empty — cascading to Groq Whisper")
        result = _transcribe_groq_whisper(audio)
        if result:
            return result
        print("[stt] Groq Whisper returned empty — cascading to Vosk")
        return _transcribe_vosk(audio)

    # ── Tier 1: Groq Whisper ─────────────────────────────────────────────────
    if engine == "groq":
        result = _transcribe_groq_whisper(audio)
        if result:
            return result
        print("[stt] Groq Whisper returned empty — cascading to Vosk")
        return _transcribe_vosk(audio)

    # ── Existing cloud engines ───────────────────────────────────────────────
    if engine == "deepgram":
        from albedo.audio import stt_router
        return stt_router.transcribe(audio, sample_rate=AUDIO_SAMPLE_RATE)

    if engine == "whisper":
        from albedo.audio import stt_whisper
        return stt_whisper.transcribe(audio, sample_rate=AUDIO_SAMPLE_RATE)

    # ── Default / Tier 4: Vosk ───────────────────────────────────────────────
    return _transcribe_vosk(audio)
