"""
Wake word detection via Vosk with a restricted-grammar KaldiRecognizer.

Listens continuously to the audio stream and uses Vosk transcription
to detect the configured persona word(s).  This replaces OpenWakeWord
entirely — Vosk handles both wake detection and full STT, so there is
only one model to load and keep resident.

WAKE_WORDS in .env is a comma-separated list (e.g. "cortana,jarvis").
Wake detection succeeds when any one of those words appears in either
the partial or final Vosk result while listening.
"""
from __future__ import annotations

import json

import sounddevice as sd
from vosk import KaldiRecognizer

from albedo.audio.capture import AudioStream
from albedo.audio.stt import _get_model
from albedo.config import AUDIO_SAMPLE_RATE, WAKE_WORDS

_recognizer: KaldiRecognizer | None = None
_active_words: str = WAKE_WORDS


def set_active_model(words: str) -> None:
    """
    Hot-swap the wake word(s).  Accepts a comma-separated string,
    e.g. "cortana,jarvis" or just "cortana".  Resets the cached
    recognizer so the next wait_for_wakeword() call rebuilds it
    with the new grammar.
    """
    global _recognizer, _active_words
    if words and words != _active_words:
        _active_words = words
        _recognizer = None


def _word_set() -> set[str]:
    return {w.strip().lower() for w in _active_words.split(",") if w.strip()}


def _get_recognizer() -> KaldiRecognizer:
    global _recognizer
    if _recognizer is None:
        words = sorted(_word_set())
        # "[unk]" is required so Vosk silently absorbs anything not in the list
        grammar = json.dumps(words + ["[unk]"])
        model = _get_model()
        _recognizer = KaldiRecognizer(model, AUDIO_SAMPLE_RATE, grammar)
        print(f"[wakeword] Vosk recognizer armed for: {words}")
    return _recognizer


def wait_for_wakeword(stream: AudioStream) -> None:
    """Block until any configured wake word is transcribed by Vosk."""
    rec     = _get_recognizer()
    targets = _word_set()
    print(f"[wakeword] Listening for {sorted(targets)}")

    while True:
        chunk = stream.read_chunk()
        if chunk is None:
            sd.sleep(10)
            continue

        if rec.AcceptWaveform(chunk.tobytes()):
            text = json.loads(rec.Result()).get("text", "").strip().lower()
            if any(w in text for w in targets):
                rec.Reset()
                return
        else:
            partial = json.loads(rec.PartialResult()).get("partial", "").strip().lower()
            if partial and any(w in partial for w in targets):
                rec.Reset()
                return
