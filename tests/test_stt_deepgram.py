"""
Unit tests for albedo.audio.stt_deepgram.

The deepgram-sdk isn't installed in this dev venv (it's opt-in via
AUDIO_STT=deepgram + a DEEPGRAM_API_KEY). Tests stub it via sys.modules.

Run:
    python tests/test_stt_deepgram.py
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import torch                                                    # noqa: F401
except ImportError:
    pass

import numpy as np                                                  # noqa: E402

from albedo.audio import stt_deepgram                               # noqa: E402


# ---------------------------------------------------------------------------
# Fake deepgram SDK
# ---------------------------------------------------------------------------

class _FakePrerecordedOptions:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeListenRest:
    last_payload: dict = {}
    next_transcript: str = "hello world"
    raise_on_call: bool = False

    def v(self, _version):
        return self

    def transcribe_file(self, payload, options, timeout=None):
        _FakeListenRest.last_payload = {"payload": payload, "options": options.kwargs,
                                        "timeout": timeout}
        if _FakeListenRest.raise_on_call:
            raise ConnectionError("simulated deepgram network failure")
        # Build a response object that mimics the v3 typed API
        resp = MagicMock()
        resp.results.channels[0].alternatives[0].transcript = _FakeListenRest.next_transcript
        return resp


class _FakeClient:
    def __init__(self, api_key):
        self.api_key = api_key
        # Mimic v3 shape: client.listen.rest
        self.listen = types.SimpleNamespace(rest=_FakeListenRest())


def _install_fake_deepgram():
    fake_mod = types.ModuleType("deepgram")
    fake_mod.DeepgramClient = _FakeClient
    fake_mod.PrerecordedOptions = _FakePrerecordedOptions
    return patch.dict(sys.modules, {"deepgram": fake_mod})


def _reset(api_key="test-key"):
    stt_deepgram.reset_state()
    _FakeListenRest.last_payload = {}
    _FakeListenRest.next_transcript = "hello world"
    _FakeListenRest.raise_on_call = False
    if api_key is None:
        os.environ.pop("DEEPGRAM_API_KEY", None)
    else:
        os.environ["DEEPGRAM_API_KEY"] = api_key


# ---------------------------------------------------------------------------
# is_available()
# ---------------------------------------------------------------------------

def test_is_available_false_without_api_key():
    _reset(api_key=None)
    with _install_fake_deepgram():
        assert stt_deepgram.is_available() is False


def test_is_available_false_without_sdk():
    _reset()
    with patch.object(stt_deepgram, "_deepgram_importable", return_value=False):
        assert stt_deepgram.is_available() is False


def test_is_available_true_when_configured():
    _reset()
    with _install_fake_deepgram():
        assert stt_deepgram.is_available() is True


# ---------------------------------------------------------------------------
# transcribe() — success path
# ---------------------------------------------------------------------------

def test_transcribe_returns_text_on_success():
    _reset()
    _FakeListenRest.next_transcript = "the swarm is online"
    audio = np.zeros(16000, dtype=np.float32)
    with _install_fake_deepgram():
        text = stt_deepgram.transcribe(audio)
    assert text == "the swarm is online"
    assert stt_deepgram.last_error() is None


def test_transcribe_forwards_audio_as_wav_bytes():
    _reset()
    audio = (np.sin(np.linspace(0, 6.28, 16000)) * 10000).astype(np.int16)
    with _install_fake_deepgram():
        stt_deepgram.transcribe(audio)
    p = _FakeListenRest.last_payload
    assert isinstance(p["payload"]["buffer"], bytes)
    assert p["payload"]["buffer"][:4] == b"RIFF"   # valid WAV magic
    assert p["payload"]["buffer"][8:12] == b"WAVE"


def test_transcribe_forwards_configured_model_and_language():
    _reset()
    os.environ["DEEPGRAM_MODEL"] = "nova-2"
    os.environ["DEEPGRAM_LANGUAGE"] = "en"
    audio = np.zeros(16000, dtype=np.float32)
    with _install_fake_deepgram():
        stt_deepgram.transcribe(audio)
    opts = _FakeListenRest.last_payload["options"]
    assert opts["model"] == "nova-2"
    assert opts["language"] == "en"


# ---------------------------------------------------------------------------
# Failure modes — every path returns ""
# ---------------------------------------------------------------------------

def test_transcribe_returns_empty_for_too_short_audio():
    _reset()
    audio = np.zeros(100, dtype=np.float32)
    with _install_fake_deepgram():
        assert stt_deepgram.transcribe(audio) == ""


def test_transcribe_returns_empty_without_api_key():
    _reset(api_key=None)
    audio = np.zeros(16000, dtype=np.float32)
    with _install_fake_deepgram():
        result = stt_deepgram.transcribe(audio)
    assert result == ""
    assert "DEEPGRAM_API_KEY" in (stt_deepgram.last_error() or "")


def test_transcribe_returns_empty_on_network_failure():
    _reset()
    _FakeListenRest.raise_on_call = True
    audio = np.zeros(16000, dtype=np.float32)
    with _install_fake_deepgram():
        result = stt_deepgram.transcribe(audio)
    assert result == ""
    assert "ConnectionError" in (stt_deepgram.last_error() or "")


def test_transcribe_returns_empty_on_empty_deepgram_response():
    _reset()
    _FakeListenRest.next_transcript = ""
    audio = np.zeros(16000, dtype=np.float32)
    with _install_fake_deepgram():
        result = stt_deepgram.transcribe(audio)
    assert result == ""
    assert "empty transcript" in (stt_deepgram.last_error() or "")


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import faulthandler, inspect, traceback
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
