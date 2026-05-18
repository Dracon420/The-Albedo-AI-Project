"""
tts_kokoro.py — Kokoro TTS engine wrapper.

Provides a synthesizer-only module that runs the Kokoro voice model
locally via ONNX runtime, on the CPU device assigned by
``albedo.resource_policy``. The engine selection (Kokoro vs Piper vs
Edge-TTS) is made one level up in ``albedo/audio/tts.py``; this module
just produces audio when asked.

Phase 4 N+1 of the Cyberdeck Overhaul — see docs/PHASE_4_AUDIO_PLAN.md.

Lazy model loading
------------------
The Kokoro ONNX session is built on the first ``synthesize()`` call,
not at import time. This matters because:

  - the model is ~300 MB and takes 1-3 seconds to load,
  - importing ``albedo.audio.tts`` should not pay that cost when the
    active engine is Piper (the v2.x default),
  - tests must be able to import this module without the kokoro-onnx
    package or model files being present.

Public API
----------
    is_available() -> bool
        True only when kokoro-onnx is installed AND the model and voices
        files exist on disk. Cheap; safe to call repeatedly.

    synthesize(text, voice=None, speed=1.0) -> tuple[np.ndarray, int] | None
        Returns (float32 PCM samples, sample_rate). None on any failure
        (model missing, unknown voice, runtime error). Never raises into
        the caller — every failure path returns None so dispatcher logic
        can fall back to Piper cleanly.

    synthesize_to_bytes(text, voice=None, speed=1.0) -> bytes | None
        Same contract as albedo.audio.tts.synthesize_to_bytes — returns
        a self-contained WAV byte string for the FastAPI server / mobile
        client. None on failure.

    available_voices() -> list[str]
        Voice names the loaded model knows about. Empty list before
        the model is loaded (so callers don't pay the load cost just
        to enumerate).

    prewarm() -> bool
        Force the model load now. Returns True on success.

Configuration (read at synthesize() time, not import time, so .env
edits take effect on next call without restart):

    KOKORO_MODEL_PATH   absolute path to kokoro-v1.0.onnx
    KOKORO_VOICES_PATH  absolute path to voices-v1.0.bin
    KOKORO_VOICE        default voice when caller passes voice=None
    KOKORO_SPEED        default speed multiplier (float, 1.0 = normal)

If unset, the module looks for the model under ``<install_root>/voices/``
matching the existing Piper voice download convention.
"""
from __future__ import annotations

import io
import os
import threading
from pathlib import Path
from typing import Optional

import numpy as np

# Soft-import everything heavy. None of these are required at import time.
try:
    import soundfile as sf
    _SOUNDFILE_OK = True
except ImportError:
    _SOUNDFILE_OK = False

_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_MODEL_FILENAME  = "kokoro-v1.0.onnx"
_DEFAULT_VOICES_FILENAME = "voices-v1.0.bin"
_DEFAULT_VOICE           = "af_sky"        # American female, neutral
_DEFAULT_SPEED           = 1.0


# ---------------------------------------------------------------------------
# Singleton state (guarded by _model_lock)
# ---------------------------------------------------------------------------

_model_lock = threading.Lock()
_kokoro_session = None     # kokoro_onnx.Kokoro instance once loaded
_load_attempted = False    # True after the first prewarm/synthesize call,
                           # whether or not the load succeeded
_load_error: Optional[str] = None    # last load failure reason, for diagnostics


# ---------------------------------------------------------------------------
# Path resolution — env vars first, fall back to bundled voices/ dir
# ---------------------------------------------------------------------------

def _model_path() -> Path:
    env = os.environ.get("KOKORO_MODEL_PATH", "").strip()
    if env:
        return Path(env)
    return _ROOT / "voices" / _DEFAULT_MODEL_FILENAME


def _voices_path() -> Path:
    env = os.environ.get("KOKORO_VOICES_PATH", "").strip()
    if env:
        return Path(env)
    return _ROOT / "voices" / _DEFAULT_VOICES_FILENAME


def _default_voice() -> str:
    return os.environ.get("KOKORO_VOICE", _DEFAULT_VOICE).strip() or _DEFAULT_VOICE


def _default_speed() -> float:
    raw = os.environ.get("KOKORO_SPEED", "").strip()
    if not raw:
        return _DEFAULT_SPEED
    try:
        return float(raw)
    except ValueError:
        return _DEFAULT_SPEED


# ---------------------------------------------------------------------------
# Availability check (no side effects, never throws)
# ---------------------------------------------------------------------------

def _kokoro_module_importable() -> bool:
    try:
        import kokoro_onnx  # noqa: F401
        return True
    except ImportError:
        return False


def is_available() -> bool:
    """
    True only when:
      - kokoro-onnx is pip-installed,
      - soundfile is importable (needed for WAV bytes path),
      - the model and voices files both exist on disk.

    Does NOT load the model; cheap to call from a dispatcher's hot path.
    """
    if not _kokoro_module_importable():
        return False
    if not _SOUNDFILE_OK:
        return False
    return _model_path().exists() and _voices_path().exists()


# ---------------------------------------------------------------------------
# Model construction (lazy, thread-safe)
# ---------------------------------------------------------------------------

def _build_session():
    """
    Construct the kokoro_onnx.Kokoro session honouring the resource policy
    for ONNX providers. Returns the session, or raises with a clear message
    on any failure (caller wraps to convert to None).
    """
    import kokoro_onnx
    from albedo.resource_policy import providers_for

    providers = providers_for("tts_kokoro") or ["CPUExecutionProvider"]
    model = str(_model_path())
    voices = str(_voices_path())

    # kokoro-onnx API has shifted over releases. Try the providers-kwarg
    # path first (>= 0.4.x), fall back to plain construction.
    try:
        return kokoro_onnx.Kokoro(model, voices, providers=providers)
    except TypeError:
        # Older release without providers kwarg — onnxruntime defaults to
        # CPU when CUDA isn't installed, which matches our policy anyway.
        return kokoro_onnx.Kokoro(model, voices)


def _ensure_loaded() -> bool:
    """
    Load the model if not already loaded. Returns True on success, False
    on any failure. Records the failure reason in _load_error for the
    diagnostics endpoint.
    """
    global _kokoro_session, _load_attempted, _load_error
    if _kokoro_session is not None:
        return True
    with _model_lock:
        if _kokoro_session is not None:
            return True
        _load_attempted = True
        if not is_available():
            _load_error = "kokoro-onnx not installed or model files missing"
            return False
        try:
            _kokoro_session = _build_session()
            _load_error = None
            return True
        except Exception as exc:                                # noqa: BLE001
            _load_error = f"{type(exc).__name__}: {exc}"
            _kokoro_session = None
            return False


def prewarm() -> bool:
    """Force the model load now. Returns True on success."""
    return _ensure_loaded()


# ---------------------------------------------------------------------------
# Public synthesis API
# ---------------------------------------------------------------------------

def synthesize(
    text: str,
    voice: Optional[str] = None,
    speed: Optional[float] = None,
) -> Optional[tuple[np.ndarray, int]]:
    """
    Run Kokoro on a text block. Returns (float32 audio, sample_rate) or
    None on any failure. Never raises.
    """
    if not text or not text.strip():
        return None
    if not _ensure_loaded():
        return None

    v = (voice or _default_voice()).strip()
    s = float(speed) if speed is not None else _default_speed()
    try:
        # kokoro.create returns (samples: np.ndarray float32, sample_rate: int)
        samples, sample_rate = _kokoro_session.create(text, voice=v, speed=s)
    except Exception as exc:                                    # noqa: BLE001
        print(f"[tts_kokoro] synthesis error: {exc}")
        return None

    # Some kokoro-onnx versions return samples as float64; coerce.
    if samples.dtype != np.float32:
        samples = samples.astype(np.float32)
    return samples, int(sample_rate)


def synthesize_to_bytes(
    text: str,
    voice: Optional[str] = None,
    speed: Optional[float] = None,
) -> Optional[bytes]:
    """
    Synthesize and return a self-contained WAV byte string.

    Used by albedo/server.py to deliver audio to the mobile client. Matches
    the contract of albedo.audio.tts.synthesize_to_bytes() so the
    dispatcher can swap engines without touching its caller.
    """
    if not _SOUNDFILE_OK:
        print("[tts_kokoro] soundfile not installed — cannot encode WAV")
        return None
    result = synthesize(text, voice=voice, speed=speed)
    if result is None:
        return None
    samples, sample_rate = result
    buf = io.BytesIO()
    try:
        sf.write(buf, samples, sample_rate, format="WAV", subtype="PCM_16")
    except Exception as exc:                                    # noqa: BLE001
        print(f"[tts_kokoro] WAV encode error: {exc}")
        return None
    return buf.getvalue()


def available_voices() -> list[str]:
    """Voice IDs the loaded model exposes. Empty list before load."""
    if _kokoro_session is None:
        return []
    # kokoro_onnx exposes either .voices (list) or .get_voices() depending
    # on version. Try both shapes.
    voices = getattr(_kokoro_session, "voices", None)
    if voices is None and hasattr(_kokoro_session, "get_voices"):
        try:
            voices = _kokoro_session.get_voices()
        except Exception:                                       # noqa: BLE001
            voices = None
    if voices is None:
        return []
    try:
        return sorted(list(voices))
    except Exception:                                           # noqa: BLE001
        return []


def load_error() -> Optional[str]:
    """Last failure reason from _ensure_loaded(), or None if load is healthy."""
    return _load_error
