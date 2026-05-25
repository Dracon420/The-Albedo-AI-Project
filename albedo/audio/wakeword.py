"""
Wake word detection via OpenWakeWord (primary) with Vosk restricted-grammar
fallback.

OpenWakeWord is purpose-built for always-on wake-word detection and is far
more accurate than running full-vocabulary Vosk because it works directly on
mel-spectrogram audio features rather than trying to decode speech.

The `hey_jarvis_v0.1` model triggers on "hey Jarvis" (and phonetically close
phrases like "hey Cortana" — see notes below).  The Vosk restricted-grammar
path is kept as a fallback for any configured wake words that OWW doesn't
cover.

Notes on "Cortana" detection
------------------------------
OpenWakeWord has no dedicated "cortana" model.  The Vosk small model cannot
recognize "cortana" reliably because it is a proper noun absent from its
vocabulary (Vosk outputs "[unk]" or unrelated words).

Current behaviour:
  • "hey jarvis" / "jarvis"  → reliably detected by OWW hey_jarvis model
  • "cortana"                 → OWW score may be low; Vosk fallback active
                                but also unreliable for this word

The best wake trigger is "hey jarvis" until a custom OWW model is trained
for "cortana".  Set WAKE_WORDS=jarvis (or hey jarvis) in .env.

Public API
----------
wait_for_wakeword(stream, stop_event=None)
    Blocking — returns True when detected, False on stop_event.

start_background_listener(stream, callback, stop_event=None) -> threading.Event
    Non-blocking daemon thread.  Returns stop_event for cancellation.
"""
from __future__ import annotations

import json
import threading

from albedo.audio.capture import AudioStream
from albedo.config import AUDIO_SAMPLE_RATE, WAKE_WORDS

# ---------------------------------------------------------------------------
# Guarded imports
# ---------------------------------------------------------------------------
try:
    import sounddevice as sd
    _SD_AVAILABLE = True
except ImportError:
    _SD_AVAILABLE = False
    print("[wakeword] WARN: sounddevice not installed — wake word disabled.")

try:
    from openwakeword.model import Model as _OWWModel
    _OWW_AVAILABLE = True
except ImportError:
    _OWW_AVAILABLE = False
    print("[wakeword] WARN: openwakeword not installed — falling back to Vosk.")

try:
    from vosk import KaldiRecognizer
    from albedo.audio.stt import _get_model as _get_vosk_model
    _VOSK_AVAILABLE = True
except ImportError:
    _VOSK_AVAILABLE = False

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
_active_words:       str = WAKE_WORDS
_last_detected_word: str = ""
_detected_lock       = threading.Lock()
_oww_model:          "_OWWModel | None" = None
_oww_lock            = threading.Lock()

# OpenWakeWord detection threshold (0–1).  Lower = more sensitive but more
# false positives.  0.3 gives good sensitivity for "hey jarvis".
_OWW_THRESHOLD = 0.3

# Frames of audio fed to OWW per chunk.  OWW expects 80ms frames at 16kHz
# = 1280 samples (matches AUDIO_CHUNK_MS=80 in config).
_OWW_CHUNK_SAMPLES = int(AUDIO_SAMPLE_RATE * 80 / 1000)  # 1280


def get_last_detected_word() -> str:
    with _detected_lock:
        return _last_detected_word


def _record_detected(word: str) -> None:
    global _last_detected_word
    with _detected_lock:
        _last_detected_word = word.strip().lower()


def _word_set() -> set[str]:
    return {w.strip().lower() for w in _active_words.split(",") if w.strip()}


def set_active_model(words: str) -> None:
    """Hot-swap active wake words. Resets the OWW model cache."""
    global _active_words, _oww_model
    def _bare(w: str) -> str:
        for prefix in ("hey ", "ok "):
            if w.lower().startswith(prefix):
                return w[len(prefix):]
        return w
    normalised = ",".join(_bare(w.strip()) for w in words.split(",") if w.strip())
    if normalised and normalised != _active_words:
        _active_words = normalised
        with _oww_lock:
            _oww_model = None


# ---------------------------------------------------------------------------
# OpenWakeWord engine
# ---------------------------------------------------------------------------

def _get_oww_model() -> "_OWWModel":
    """
    Return a cached OWW Model instance.

    Loads the custom hey_core_tah_nuh.onnx ("hey cortana") model from the
    wakewords/ directory if present, then hey_jarvis as a secondary trigger,
    then falls back to the bundled alexa model so there's always something.
    """
    global _oww_model
    with _oww_lock:
        if _oww_model is None:
            import os
            from pathlib import Path
            root = Path(__file__).resolve().parent.parent.parent
            ww_dir = root / "wakewords"

            models_to_load: list[str] = []

            # Priority 1: custom hey_cortana model
            cortana_model = ww_dir / "hey_core_tah_nuh.onnx"
            if cortana_model.exists():
                models_to_load.append(str(cortana_model))
                print(f"[wakeword] Found custom cortana model: {cortana_model.name}")

            # Priority 2: hey_jarvis in wakewords/ dir
            jarvis_model = ww_dir / "hey_jarvis_v0.1.onnx"
            if jarvis_model.exists():
                models_to_load.append(str(jarvis_model))
                print(f"[wakeword] Found jarvis model: {jarvis_model.name}")

            # Fallback: bundled hey_jarvis
            if not models_to_load:
                models_to_load.append("hey_jarvis_v0.1.onnx")
                print("[wakeword] Using bundled hey_jarvis fallback.")

            print(f"[wakeword] Loading OWW with {len(models_to_load)} model(s)...")
            _oww_model = _OWWModel(
                wakeword_models=models_to_load,
                inference_framework="onnx",
            )
            print("[wakeword] OpenWakeWord ready.")
        return _oww_model


def _oww_detect_chunk(model: "_OWWModel", chunk) -> tuple[bool, str]:
    """
    Feed one chunk to OWW.  Returns (detected, word_label).

    OWW predict() returns a dict: {model_name: score}.  We check if the
    top score exceeds _OWW_THRESHOLD and also do a string match so the
    detected label maps back to configured wake words.
    """
    import numpy as np
    # OWW expects float32 or int16 at 16kHz mono
    if hasattr(chunk, 'dtype') and chunk.dtype == np.int16:
        audio_in = chunk
    else:
        audio_in = (np.clip(chunk, -1.0, 1.0) * 32767).astype(np.int16)

    scores = model.predict(audio_in)
    for model_name, score in scores.items():
        if score >= _OWW_THRESHOLD:
            mn_lower = model_name.lower()
            # Custom cortana model — phonetic spelling maps to "cortana"
            if "core_tah_nuh" in mn_lower or "cortana" in mn_lower:
                return True, "cortana"
            if "jarvis" in mn_lower:
                return True, "jarvis"
            if "alexa" in mn_lower:
                return True, "alexa"
            # Generic fallback: match against configured wake words
            for word in _word_set():
                if word in mn_lower:
                    return True, word
            return True, model_name.split("_")[0]
    return False, ""


# ---------------------------------------------------------------------------
# Vosk restricted-grammar fallback
# ---------------------------------------------------------------------------

def _get_vosk_recognizer() -> "KaldiRecognizer | None":
    """Build a grammar-restricted Vosk recognizer for configured wake words."""
    if not _VOSK_AVAILABLE:
        return None
    try:
        words = sorted(_word_set())
        token_set: set[str] = set()
        for phrase in words:
            token_set.add(phrase)
            token_set.update(phrase.split())
        grammar_words = sorted(token_set) + ["[unk]"]
        model = _get_vosk_model()
        rec = KaldiRecognizer(model, AUDIO_SAMPLE_RATE, json.dumps(grammar_words))
        print(f"[wakeword] Vosk fallback grammar: {grammar_words}")
        return rec
    except Exception as exc:
        print(f"[wakeword] Vosk recognizer build failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Core detection loop
# ---------------------------------------------------------------------------

def wait_for_wakeword(
    stream: AudioStream,
    stop_event: threading.Event | None = None,
) -> bool:
    """
    Block until a wake word is detected.

    Strategy:
      1. OpenWakeWord (primary) — feed every chunk, check OWW scores.
      2. Vosk restricted grammar (fallback) — runs in parallel, fires if
         any configured wake word appears in partial/final transcripts.

    Returns True on detection, False when stop_event fires.
    """
    if not _SD_AVAILABLE:
        return False

    oww      = _get_oww_model() if _OWW_AVAILABLE else None
    vosk_rec = _get_vosk_recognizer() if _VOSK_AVAILABLE else None
    targets  = _word_set()

    print(f"[wakeword] Listening for {sorted(targets)} "
          f"(OWW={'yes' if oww else 'no'}, Vosk={'yes' if vosk_rec else 'no'})")

    while True:
        if stop_event is not None and stop_event.is_set():
            return False

        chunk = stream.read_chunk()
        if chunk is None:
            sd.sleep(10)
            continue

        # ── OpenWakeWord check ────────────────────────────────────────────
        if oww is not None:
            try:
                detected, word = _oww_detect_chunk(oww, chunk)
                if detected:
                    _record_detected(word)
                    # Reset OWW state so it doesn't double-fire
                    oww.reset()
                    return True
            except Exception as exc:
                print(f"[wakeword] OWW error: {exc}")

        # ── Vosk fallback check ───────────────────────────────────────────
        if vosk_rec is not None:
            try:
                if vosk_rec.AcceptWaveform(chunk.tobytes()):
                    text = json.loads(vosk_rec.Result()).get("text", "").strip().lower()
                    if text and any(w in text for w in targets):
                        _record_detected(next(w for w in targets if w in text))
                        vosk_rec.Reset()
                        return True
                else:
                    partial = json.loads(vosk_rec.PartialResult()).get("partial", "").strip().lower()
                    if partial and any(w in partial for w in targets):
                        _record_detected(next(w for w in targets if w in partial))
                        vosk_rec.Reset()
                        return True
            except Exception as exc:
                print(f"[wakeword] Vosk error: {exc}")


# ---------------------------------------------------------------------------
# Non-blocking background listener
# ---------------------------------------------------------------------------

def start_background_listener(
    stream: AudioStream,
    callback,
    stop_event: threading.Event | None = None,
) -> threading.Event:
    """
    Run wake word detection in a daemon thread.

    Arguments
    ---------
    stream      : an already-started AudioStream
    callback    : called (with no arguments) each time the wake word fires
    stop_event  : optional Event to cancel; one is created if None

    Returns the stop_event.
    """
    if stop_event is None:
        stop_event = threading.Event()

    def _loop() -> None:
        while not stop_event.is_set():
            try:
                detected = wait_for_wakeword(stream, stop_event=stop_event)
                if detected and not stop_event.is_set():
                    word = get_last_detected_word()
                    if word:
                        try:
                            from albedo.eel_app.bridge import notify_persona_change
                            notify_persona_change(word)
                        except Exception:
                            pass
                    callback()
            except Exception as exc:
                print(f"[wakeword] Listener error: {exc}")
                if not stop_event.is_set():
                    sd.sleep(500)

    threading.Thread(target=_loop, daemon=True, name="wakeword-listener").start()
    return stop_event
