"""
Unit tests for albedo.audio.tts_kokoro.

The Kokoro ONNX runtime and model files aren't installed in this dev
venv (they're an opt-in install via AUDIO_TTS=kokoro). Tests therefore
stub the kokoro_onnx module and the model file existence checks so the
behaviour under test is the wrapper logic, not the model itself.

Run:
    python tests/test_tts_kokoro.py
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Pre-import torch so any test that triggers resource_policy._probe_torch_cuda()
# pays the import cost in a clean GC state. torch 2.12.0+cpu has a known
# Python 3.12 segfault during initial import when the GC fires mid-import
# (the crash happens in typing_extensions._collect_parameters). Importing
# it before any test runs sidesteps the race entirely.
try:
    import torch                                                    # noqa: F401
except ImportError:
    pass

import numpy as np                                                  # noqa: E402

from albedo.audio import tts_kokoro                                 # noqa: E402


# ---------------------------------------------------------------------------
# Helpers — install a fake kokoro_onnx module for the duration of a test
# ---------------------------------------------------------------------------

class _FakeKokoro:
    """Mimics kokoro_onnx.Kokoro for testing wrapper logic."""
    last_init_args:  list[tuple] = []
    last_create_call:  dict      = {}
    next_audio:       np.ndarray = np.zeros(2400, dtype=np.float32)  # 0.1s @ 24kHz
    next_sample_rate: int        = 24000
    fail_create:      bool       = False
    voices:           list[str]  = ["af_sky", "af_bella", "am_michael"]

    def __init__(self, model, voices, providers=None):
        _FakeKokoro.last_init_args.append((model, voices, providers))

    def create(self, text, voice="af_sky", speed=1.0, lang="en-us"):
        _FakeKokoro.last_create_call = {
            "text": text, "voice": voice, "speed": speed, "lang": lang,
        }
        if _FakeKokoro.fail_create:
            raise RuntimeError("simulated kokoro internal failure")
        return _FakeKokoro.next_audio, _FakeKokoro.next_sample_rate


def _install_fake_kokoro():
    """Inject a fake kokoro_onnx module into sys.modules. Returns the patcher object."""
    fake_mod = types.ModuleType("kokoro_onnx")
    fake_mod.Kokoro = _FakeKokoro
    return patch.dict(sys.modules, {"kokoro_onnx": fake_mod})


def _reset_module_state():
    """Reset tts_kokoro internals between tests."""
    tts_kokoro._kokoro_session = None
    tts_kokoro._load_attempted = False
    tts_kokoro._load_error = None
    _FakeKokoro.last_init_args = []
    _FakeKokoro.last_create_call = {}
    _FakeKokoro.fail_create = False
    _FakeKokoro.next_audio = np.zeros(2400, dtype=np.float32)
    _FakeKokoro.next_sample_rate = 24000


# ---------------------------------------------------------------------------
# is_available()
# ---------------------------------------------------------------------------

def test_is_available_false_when_kokoro_module_missing():
    """Patch the importability probe rather than sys.modules — putting None
    into sys.modules can segfault on some interpreters when an earlier
    successful import is cached."""
    _reset_module_state()
    with patch.object(tts_kokoro, "_kokoro_module_importable", return_value=False):
        assert tts_kokoro.is_available() is False


def test_is_available_false_when_model_files_missing():
    _reset_module_state()
    with _install_fake_kokoro(), \
         patch.object(tts_kokoro, "_model_path",
                      return_value=Path("/does/not/exist/model.onnx")), \
         patch.object(tts_kokoro, "_voices_path",
                      return_value=Path("/does/not/exist/voices.bin")):
        assert tts_kokoro.is_available() is False


def test_is_available_true_when_module_and_files_present(tmp_path=None):
    _reset_module_state()
    # Use real filesystem paths so .exists() returns True.
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".onnx", delete=False) as m, \
         tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as v:
        model_p = Path(m.name)
        voices_p = Path(v.name)
    try:
        with _install_fake_kokoro(), \
             patch.object(tts_kokoro, "_model_path", return_value=model_p), \
             patch.object(tts_kokoro, "_voices_path", return_value=voices_p):
            assert tts_kokoro.is_available() is True
    finally:
        model_p.unlink(missing_ok=True)
        voices_p.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Lazy load contract
# ---------------------------------------------------------------------------

def test_no_load_at_import_time():
    """tts_kokoro module-level state must not call Kokoro() on import."""
    _reset_module_state()
    assert tts_kokoro._kokoro_session is None
    assert tts_kokoro._load_attempted is False


def test_synthesize_loads_on_first_call_only(tmp_path):
    """First synthesize() triggers load; second synthesize() reuses the session."""
    _reset_module_state()
    model_p  = tmp_path / "kokoro.onnx"; model_p.touch()
    voices_p = tmp_path / "voices.bin";  voices_p.touch()

    with _install_fake_kokoro(), \
         patch.object(tts_kokoro, "_model_path", return_value=model_p), \
         patch.object(tts_kokoro, "_voices_path", return_value=voices_p):
        assert len(_FakeKokoro.last_init_args) == 0
        tts_kokoro.synthesize("first")
        tts_kokoro.synthesize("second")
        tts_kokoro.synthesize("third")
    # Kokoro constructor should fire exactly once.
    assert len(_FakeKokoro.last_init_args) == 1


# ---------------------------------------------------------------------------
# Resource policy is consulted
# ---------------------------------------------------------------------------

def test_providers_from_resource_policy_passed_to_kokoro(tmp_path):
    _reset_module_state()
    model_p  = tmp_path / "kokoro.onnx"; model_p.touch()
    voices_p = tmp_path / "voices.bin";  voices_p.touch()

    fake_providers = ["CPUExecutionProvider"]
    with _install_fake_kokoro(), \
         patch.object(tts_kokoro, "_model_path", return_value=model_p), \
         patch.object(tts_kokoro, "_voices_path", return_value=voices_p), \
         patch("albedo.resource_policy.providers_for", return_value=fake_providers) as mock_providers:
        tts_kokoro.synthesize("hello")

    mock_providers.assert_called_with("tts_kokoro")
    # Kokoro should have been constructed with the policy's providers list
    assert len(_FakeKokoro.last_init_args) == 1
    _, _, providers = _FakeKokoro.last_init_args[0]
    assert providers == fake_providers


# ---------------------------------------------------------------------------
# synthesize()
# ---------------------------------------------------------------------------

def test_synthesize_returns_audio_and_sample_rate(tmp_path):
    _reset_module_state()
    model_p  = tmp_path / "kokoro.onnx"; model_p.touch()
    voices_p = tmp_path / "voices.bin";  voices_p.touch()

    _FakeKokoro.next_audio = np.linspace(-1.0, 1.0, 1200, dtype=np.float32)
    _FakeKokoro.next_sample_rate = 24000

    with _install_fake_kokoro(), \
         patch.object(tts_kokoro, "_model_path", return_value=model_p), \
         patch.object(tts_kokoro, "_voices_path", return_value=voices_p):
        result = tts_kokoro.synthesize("hello world", voice="af_bella", speed=1.2)

    assert result is not None
    audio, sr = result
    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    assert audio.shape == (1200,)
    assert sr == 24000
    # The voice + speed arguments must be forwarded to Kokoro.create()
    assert _FakeKokoro.last_create_call["voice"] == "af_bella"
    assert _FakeKokoro.last_create_call["speed"] == 1.2


def test_synthesize_returns_none_on_empty_text():
    _reset_module_state()
    assert tts_kokoro.synthesize("")     is None
    assert tts_kokoro.synthesize("   ")  is None


def test_synthesize_returns_none_when_unavailable():
    """No model files = no exception, just None."""
    _reset_module_state()
    with patch.object(tts_kokoro, "_model_path",
                      return_value=Path("/does/not/exist.onnx")):
        assert tts_kokoro.synthesize("hello") is None


def test_synthesize_returns_none_on_kokoro_internal_failure(tmp_path):
    _reset_module_state()
    model_p  = tmp_path / "kokoro.onnx"; model_p.touch()
    voices_p = tmp_path / "voices.bin";  voices_p.touch()
    _FakeKokoro.fail_create = True

    with _install_fake_kokoro(), \
         patch.object(tts_kokoro, "_model_path", return_value=model_p), \
         patch.object(tts_kokoro, "_voices_path", return_value=voices_p):
        assert tts_kokoro.synthesize("trigger failure") is None


# ---------------------------------------------------------------------------
# synthesize_to_bytes()
# ---------------------------------------------------------------------------

def test_synthesize_to_bytes_returns_valid_wav(tmp_path):
    _reset_module_state()
    model_p  = tmp_path / "kokoro.onnx"; model_p.touch()
    voices_p = tmp_path / "voices.bin";  voices_p.touch()

    _FakeKokoro.next_audio = np.sin(np.linspace(0, 6.28, 2400)).astype(np.float32) * 0.3
    _FakeKokoro.next_sample_rate = 24000

    with _install_fake_kokoro(), \
         patch.object(tts_kokoro, "_model_path", return_value=model_p), \
         patch.object(tts_kokoro, "_voices_path", return_value=voices_p):
        wav = tts_kokoro.synthesize_to_bytes("hello world")

    assert wav is not None
    # Valid WAV files begin with "RIFF" + size + "WAVE"
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    # PCM_16 header is 44 bytes, body is 2400 samples * 2 bytes/sample = 4800
    assert len(wav) >= 44 + 4800


def test_synthesize_to_bytes_returns_none_on_failure(tmp_path):
    _reset_module_state()
    with patch.object(tts_kokoro, "_model_path",
                      return_value=Path("/does/not/exist.onnx")):
        assert tts_kokoro.synthesize_to_bytes("hello") is None


# ---------------------------------------------------------------------------
# load_error diagnostics
# ---------------------------------------------------------------------------

def test_load_error_records_missing_files():
    _reset_module_state()
    with patch.object(tts_kokoro, "_model_path",
                      return_value=Path("/does/not/exist.onnx")):
        tts_kokoro.synthesize("trigger load attempt")
    err = tts_kokoro.load_error()
    assert err is not None
    assert "not installed" in err or "missing" in err


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import faulthandler, inspect, os, tempfile, shutil, traceback
    # libsndfile (used via soundfile in the WAV-bytes test) can crash on
    # interpreter shutdown when its global state outlives the process; the
    # tests themselves all succeed. Enable faulthandler defensively and
    # use os._exit() to skip the at-exit teardown that triggers the crash.
    faulthandler.enable()

    mod = sys.modules[__name__]
    tests = [(n, f) for n, f in inspect.getmembers(mod, inspect.isfunction)
             if n.startswith("test_")]
    passed = failed = 0
    for name, fn in tests:
        sig = inspect.signature(fn)
        td_obj = None
        try:
            if "tmp_path" in sig.parameters:
                td_obj = tempfile.mkdtemp(prefix=f"kokoro_test_{name}_")
                fn(Path(td_obj))
            else:
                fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception:
            print(f"  FAIL  {name}")
            traceback.print_exc()
            failed += 1
        finally:
            if td_obj:
                shutil.rmtree(td_obj, ignore_errors=True)
    print(f"\n{passed} passed, {failed} failed")
    os._exit(0 if failed == 0 else 1)
