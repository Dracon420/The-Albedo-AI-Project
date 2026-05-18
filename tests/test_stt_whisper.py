"""
Unit tests for albedo.audio.stt_whisper.

Mocks faster_whisper.WhisperModel so tests run without paying the
~250 MB model download. Validates lazy load contract, resource_policy
device wiring, and audio dtype coercion.

Run:
    python tests/test_stt_whisper.py
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Pre-import torch to avoid the torch 2.12.0+cpu / Python 3.12 GC race
# documented in tests/test_tts_kokoro.py.
try:
    import torch                                                    # noqa: F401
except ImportError:
    pass

import numpy as np                                                  # noqa: E402

from albedo.audio import stt_whisper                                # noqa: E402


# ---------------------------------------------------------------------------
# Fake WhisperModel
# ---------------------------------------------------------------------------

class _FakeSegment:
    def __init__(self, text):
        self.text = text


class _FakeWhisperModel:
    last_init_kwargs: dict = {}
    next_segments:    list = []
    raise_on_transcribe: bool = False

    def __init__(self, model_name, device="cpu", compute_type="int8", **kwargs):
        _FakeWhisperModel.last_init_kwargs = {
            "model_name":   model_name,
            "device":       device,
            "compute_type": compute_type,
        }

    def transcribe(self, audio, **kwargs):
        if _FakeWhisperModel.raise_on_transcribe:
            raise RuntimeError("simulated whisper internal failure")
        return iter(_FakeWhisperModel.next_segments), {"language": "en"}


def _install_fake_whisper():
    fake_mod = types.ModuleType("faster_whisper")
    fake_mod.WhisperModel = _FakeWhisperModel
    return patch.dict(sys.modules, {"faster_whisper": fake_mod})


def _reset():
    stt_whisper._reset_for_tests()
    _FakeWhisperModel.last_init_kwargs = {}
    _FakeWhisperModel.next_segments    = [_FakeSegment(" hello world ")]
    _FakeWhisperModel.raise_on_transcribe = False


# ---------------------------------------------------------------------------
# Lazy load contract (Phase 6 fix #2)
# ---------------------------------------------------------------------------

def test_no_load_at_import_time():
    _reset()
    assert stt_whisper._model is None
    assert stt_whisper._load_attempted is False


def test_first_transcribe_triggers_load():
    _reset()
    audio = np.zeros(16000, dtype=np.float32)   # 1 second of silence
    with _install_fake_whisper(), \
         patch("albedo.resource_policy.device_for", return_value="cpu"):
        text = stt_whisper.transcribe(audio)
    assert text == "hello world"
    assert stt_whisper._model is not None
    assert _FakeWhisperModel.last_init_kwargs["model_name"] == "distil-small.en"


def test_subsequent_transcribes_reuse_loaded_model():
    _reset()
    audio = np.zeros(16000, dtype=np.float32)
    construct_count = {"n": 0}
    orig_init = _FakeWhisperModel.__init__

    def counting_init(self, *a, **kw):
        construct_count["n"] += 1
        orig_init(self, *a, **kw)

    with _install_fake_whisper(), \
         patch.object(_FakeWhisperModel, "__init__", counting_init), \
         patch("albedo.resource_policy.device_for", return_value="cpu"):
        stt_whisper.transcribe(audio)
        stt_whisper.transcribe(audio)
        stt_whisper.transcribe(audio)
    assert construct_count["n"] == 1, "model must be constructed exactly once"


# ---------------------------------------------------------------------------
# Resource policy wiring (Phase 6 fix #1: CUDA-with-CPU-fallback)
# ---------------------------------------------------------------------------

def test_cpu_device_when_resource_policy_demoted():
    _reset()
    audio = np.zeros(16000, dtype=np.float32)
    with _install_fake_whisper(), \
         patch("albedo.resource_policy.device_for", return_value="cpu"):
        stt_whisper.transcribe(audio)
    assert _FakeWhisperModel.last_init_kwargs["device"]       == "cpu"
    assert _FakeWhisperModel.last_init_kwargs["compute_type"] == "int8"


def test_cuda_device_with_float16_when_available():
    _reset()
    audio = np.zeros(16000, dtype=np.float32)
    with _install_fake_whisper(), \
         patch("albedo.resource_policy.device_for", return_value="cuda"):
        stt_whisper.transcribe(audio)
    assert _FakeWhisperModel.last_init_kwargs["device"]       == "cuda"
    assert _FakeWhisperModel.last_init_kwargs["compute_type"] == "float16"


# ---------------------------------------------------------------------------
# Audio dtype coercion
# ---------------------------------------------------------------------------

def test_int16_audio_is_converted_to_float32():
    _reset()
    audio_int16 = (np.sin(np.linspace(0, 6.28, 16000)) * 10000).astype(np.int16)
    received_audio = {}

    def capture_audio(self, audio, **kwargs):
        received_audio["audio"] = audio
        return iter([_FakeSegment("ok")]), {}

    with _install_fake_whisper(), \
         patch.object(_FakeWhisperModel, "transcribe", capture_audio), \
         patch("albedo.resource_policy.device_for", return_value="cpu"):
        stt_whisper.transcribe(audio_int16)

    a = received_audio["audio"]
    assert a.dtype == np.float32
    assert a.max() <= 1.0 and a.min() >= -1.0


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------

def test_returns_empty_for_too_short_audio():
    _reset()
    audio = np.zeros(100, dtype=np.float32)   # < 0.25 s
    assert stt_whisper.transcribe(audio) == ""


def test_returns_empty_when_faster_whisper_missing():
    _reset()
    audio = np.zeros(16000, dtype=np.float32)
    with patch.object(stt_whisper, "_faster_whisper_importable", return_value=False):
        result = stt_whisper.transcribe(audio)
    assert result == ""
    assert "not installed" in (stt_whisper.load_error() or "")


def test_returns_empty_on_internal_failure():
    _reset()
    _FakeWhisperModel.raise_on_transcribe = True
    audio = np.zeros(16000, dtype=np.float32)
    with _install_fake_whisper(), \
         patch("albedo.resource_policy.device_for", return_value="cpu"):
        result = stt_whisper.transcribe(audio)
    assert result == ""


# ---------------------------------------------------------------------------
# is_available + load_error
# ---------------------------------------------------------------------------

def test_is_available_reflects_module_state():
    _reset()
    with patch.object(stt_whisper, "_faster_whisper_importable", return_value=True):
        assert stt_whisper.is_available() is True
    with patch.object(stt_whisper, "_faster_whisper_importable", return_value=False):
        assert stt_whisper.is_available() is False


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import faulthandler, inspect, os, traceback
    faulthandler.enable()
    mod = sys.modules[__name__]
    tests = [(n, f) for n, f in inspect.getmembers(mod, inspect.isfunction)
             if n.startswith("test_")]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception:
            print(f"  FAIL  {name}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    os._exit(0 if failed == 0 else 1)
