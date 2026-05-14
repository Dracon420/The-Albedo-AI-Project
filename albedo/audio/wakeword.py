"""
Wake word detection via OpenWakeWord.

WAKEWORD_MODEL can be:
  - A built-in label string: "hey_jarvis", "alexa", "hey_mycroft"
  - An absolute path to a custom .onnx file trained on "Cortana"

To train a custom Cortana model:
  https://github.com/dscripka/openWakeWord#training-new-models
The trained .onnx goes in a local models/ directory (gitignored), then set
WAKEWORD_MODEL=C:\path\to\models\cortana.onnx in your .env.
"""

import os
import sounddevice as sd
from openwakeword.model import Model
from albedo.config import WAKEWORD_MODEL, WAKEWORD_THRESHOLD
from albedo.audio.capture import AudioStream

_model: Model | None = None


def _get_model() -> Model:
    global _model
    if _model is None:
        # Resolve whether this is a path to a custom .onnx or a built-in label
        if os.path.isfile(WAKEWORD_MODEL):
            _model = Model(wakeword_models=[WAKEWORD_MODEL], inference_framework="onnx")
        else:
            _model = Model(wakeword_models=[WAKEWORD_MODEL], inference_framework="onnx")
    return _model


def wait_for_wakeword(stream: AudioStream) -> None:
    """Block until the configured wake word is detected above threshold."""
    model = _get_model()
    model_key = list(model.models.keys())[0]

    print(f"[wakeword] Listening for '{WAKEWORD_MODEL}' (threshold={WAKEWORD_THRESHOLD})")

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
