"""
Voice loop: wake word → acknowledge → record → STT → pipeline → TTS.

                  ┌─────────────────────────────────────┐
  [mic] ──────────► Vosk (restricted-grammar wake)      │
                  │  "Cortana" detected                  │
                  │        │                             │
                  │        ▼                             │
                  │  Piper TTS: "Yes?"                   │
                  │        │                             │
                  │        ▼                             │
                  │  record_utterance (VAD gate, 1.2 s)  │
                  │        │                             │
                  │        ▼                             │
                  │  Vosk full transcription → text      │
                  │        │                             │
                  │        ▼                             │
                  │  pipeline.run() → response text      │
                  │        │                             │
                  │        ▼                             │
                  │  Piper TTS: speak response           │
                  │        │                             │
                  └────────┘  (loop)                     │
                  └─────────────────────────────────────┘
"""

import signal
import sys
from albedo.audio.capture import AudioStream, record_utterance
from albedo.audio.wakeword import wait_for_wakeword
from albedo.audio.stt import transcribe
from albedo.audio.tts import speak
from albedo.pipeline import run as pipeline_run
from albedo.config import WAKE_ACK_PHRASE


def _handle_sigint(sig, frame):
    print("\n[listener] Shutting down.")
    sys.exit(0)


def start(use_web: bool = False) -> None:
    signal.signal(signal.SIGINT, _handle_sigint)

    # Start the Fly.io relay client so phone ↔ desktop works even in voice-only mode.
    try:
        from albedo import mobile_relay as _mr
        if _mr.get_token():
            _mr.start()
            print("[listener] Mobile relay started (voice mode).")
        else:
            print("[listener] Mobile relay: no token — pair from Mission Control first.")
    except Exception as _exc:
        print(f"[listener] Mobile relay start failed (non-fatal): {_exc}")

    stream = AudioStream()
    stream.start()
    print("[listener] Albedo is online. Microphone active.")

    try:
        while True:
            # Phase 1: idle — wait for wake word
            wait_for_wakeword(stream)

            # Phase 2: acknowledge immediately to confirm detection
            print("[listener] Wake word detected.")
            speak(WAKE_ACK_PHRASE)

            # Phase 3: capture utterance via VAD
            print("[listener] Listening for command...")
            audio = record_utterance(stream)

            # Phase 4: transcribe
            query = transcribe(audio)
            if not query:
                speak("Sorry, I didn't catch that.")
                continue
            print(f"[listener] Transcribed: {query!r}")

            # Phase 5: run through Hybrid RAG pipeline
            print("[listener] Processing...")
            response = pipeline_run(query, use_web=use_web)

            # Phase 6: speak response
            if response:
                speak(response)
            else:
                speak("I wasn't able to find an answer.")

    finally:
        stream.stop()
