"""
Wake word detection via Vosk with a restricted-grammar KaldiRecognizer.

Listens continuously to the audio stream and uses Vosk transcription
to detect the configured persona word(s).  This replaces OpenWakeWord
entirely — Vosk handles both wake detection and full STT, so there is
only one model to load and keep resident.

WAKE_WORDS in .env is a comma-separated list (e.g. "cortana,jarvis").
Wake detection succeeds when any one of those words appears in either
the partial or final Vosk result while listening.

Public API
----------
wait_for_wakeword(stream, stop_event=None)
    Blocking call — returns True when detected, False when stop_event fires.

start_background_listener(stream, callback, stop_event=None) -> threading.Event
    Non-blocking — runs the detection loop in a daemon thread, calling
    callback() each time the wake word fires.  Returns the stop_event
    so the caller can cancel it.
"""
from __future__ import annotations

import json
import threading

from albedo.audio.capture import AudioStream
from albedo.audio.stt import _get_model
from albedo.config import AUDIO_SAMPLE_RATE, WAKE_WORDS

# ---------------------------------------------------------------------------
# Guarded imports — clean error if vosk / sounddevice are missing
# ---------------------------------------------------------------------------
try:
    import sounddevice as sd
    from vosk import KaldiRecognizer
    _WAKEWORD_AVAILABLE = True
except ImportError:
    _WAKEWORD_AVAILABLE = False
    print("[SYS] FATAL: Run 'pip install vosk sounddevice' in your terminal.")

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
_recognizer:   "KaldiRecognizer | None" = None
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


def _get_recognizer() -> "KaldiRecognizer":
    global _recognizer
    if _recognizer is None:
        words = sorted(_word_set())
        model = _get_model()
        _recognizer = KaldiRecognizer(model, AUDIO_SAMPLE_RATE)
        print(f"[wakeword] Vosk recognizer armed for: {words}")
    return _recognizer


# ---------------------------------------------------------------------------
# Core detection loop
# ---------------------------------------------------------------------------

def wait_for_wakeword(
    stream: AudioStream,
    stop_event: threading.Event | None = None,
) -> bool:
    """
    Block until any configured wake word is transcribed by Vosk.

    Returns True when the wake word fires.
    Returns False immediately if stop_event is set before detection.
    """
    if not _WAKEWORD_AVAILABLE:
        return False

    rec     = _get_recognizer()
    targets = _word_set()
    print(f"[wakeword] Listening for {sorted(targets)}")

    while True:
        if stop_event is not None and stop_event.is_set():
            return False

        chunk = stream.read_chunk()
        if chunk is None:
            sd.sleep(10)
            continue

        if rec.AcceptWaveform(chunk.tobytes()):
            text = json.loads(rec.Result()).get("text", "").strip().lower()
            if any(w in text for w in targets):
                rec.Reset()
                return True
        else:
            partial = json.loads(rec.PartialResult()).get("partial", "").strip().lower()
            if partial and any(w in partial for w in targets):
                rec.Reset()
                return True


# ---------------------------------------------------------------------------
# Non-blocking background listener
# ---------------------------------------------------------------------------

def start_background_listener(
    stream: AudioStream,
    callback,
    stop_event: threading.Event | None = None,
) -> threading.Event:
    """
    Run the wake word detection loop in a daemon thread so it never blocks
    the CustomTkinter mainloop().

    Arguments
    ---------
    stream      : an already-started AudioStream
    callback    : called (with no arguments) each time the wake word fires
    stop_event  : optional Event to cancel listening; one is created if None

    Returns the stop_event so the caller can cancel the listener thread.
    """
    if stop_event is None:
        stop_event = threading.Event()

    def _loop() -> None:
        while not stop_event.is_set():
            try:
                detected = wait_for_wakeword(stream, stop_event=stop_event)
                if detected and not stop_event.is_set():
                    callback()
            except Exception as exc:
                print(f"[wakeword] Listener error: {exc}")
                if not stop_event.is_set():
                    sd.sleep(500)

    threading.Thread(target=_loop, daemon=True,
                     name="wakeword-listener").start()
    return stop_event
