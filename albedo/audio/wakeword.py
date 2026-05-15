"""
Wake word detection via OpenWakeWord.

_active_model can be changed at runtime via set_active_model() so persona
switches take effect without restarting the process.

WAKEWORD_MODEL (from .env) can be:
  - A built-in label string: "hey_jarvis", "alexa", "hey_mycroft"
  - An absolute path to a custom .onnx file (e.g. hey_core_tah_nuh.onnx)

To train a custom Cortana model:
  https://github.com/dscripka/openWakeWord#training-new-models
The trained .onnx goes in <project_root>/wakeword_models/, then set
WAKEWORD_MODEL=C:/path/to/wakeword_models/hey_core_tah_nuh.onnx in .env.
"""
from __future__ import annotations

import os
import sounddevice as sd
from openwakeword.model import Model
from albedo.config import WAKEWORD_MODEL, WAKEWORD_THRESHOLD
from albedo.audio.capture import AudioStream

_model: Model | None = None
_active_model: str = WAKEWORD_MODEL


def set_active_model(model_path: str) -> None:
    """Hot-swap the wake word model.  Resets the cached singleton so the
    next wait_for_wakeword() call loads the new model."""
    global _model, _active_model
    if model_path != _active_model:
        _active_model = model_path
        _model = None


def _get_model() -> Model:
    global _model
    if _model is None:
        print(f"[wakeword] Loading model: {_active_model!r}")
        _model = Model(wakeword_models=[_active_model], inference_framework="onnx")
    return _model


def wait_for_wakeword(stream: AudioStream) -> None:
    """Block until the active wake word is detected above threshold."""
    model = _get_model()
    model_key = list(model.models.keys())[0]

    print(f"[wakeword] Listening for '{_active_model}' (threshold={WAKEWORD_THRESHOLD})")

    while True:
        chunk = stream.read_chunk()
        if chunk is None:
            sd.sleep(10)
            continue

        scores = model.predict(chunk)
        score = scores.get(model_key, 0.0)

        if score >= WAKEWORD_THRESHOLD:
            model.reset()
            return
