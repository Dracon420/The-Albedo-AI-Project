"""
albedo/audio/azure_speech.py — Azure Cognitive Services Speech wrapper.

Tier 1 TTS : Azure Neural TTS  (en-US-CortanaNeural / en-US-GuyNeural)
             500 000 chars/month free with standard neural voices.
             0.5 M chars/month free with CortanaNeural specifically.
             Requires: pip install azure-cognitiveservices-speech

Tier 1 STT : Azure Speech-to-Text
             5 hours/month free on the standard tier.
             Same SDK, same key.

Opt-in via .env:
    AZURE_SPEECH_KEY=<your-key>
    AZURE_SPEECH_REGION=<e.g. eastus>
    AZURE_TTS_VOICE_CORTANA=en-US-CortanaNeural   # default
    AZURE_TTS_VOICE_JARVIS=en-US-GuyNeural        # default
    AZURE_TTS_STYLE=                              # optional: e.g. "cheerful"
    AZURE_STT_LANGUAGE=en-US                      # default

Free account: https://azure.microsoft.com/free/  (no credit card needed)
Speech resource: https://portal.azure.com → Create resource → Speech

If the SDK is not installed or the key is blank, every function in this
module returns None / False / empty string gracefully so the caller can
fall through to the next tier without any special-casing.
"""
from __future__ import annotations

import io
import os
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# Lazy SDK guard — avoids a hard ImportError if sdk isn't installed
# ---------------------------------------------------------------------------
_SDK_AVAILABLE: bool | None = None   # None = not yet checked


def _sdk_ok() -> bool:
    global _SDK_AVAILABLE
    if _SDK_AVAILABLE is None:
        try:
            import azure.cognitiveservices.speech  # noqa: F401
            _SDK_AVAILABLE = True
        except ImportError:
            _SDK_AVAILABLE = False
    return _SDK_AVAILABLE


def is_available() -> bool:
    """
    Return True when the Azure Speech SDK is installed AND
    AZURE_SPEECH_KEY + AZURE_SPEECH_REGION are set in the environment.
    Cheap to call; safe to call repeatedly.
    """
    if not _sdk_ok():
        return False
    key    = os.environ.get("AZURE_SPEECH_KEY",    "").strip()
    region = os.environ.get("AZURE_SPEECH_REGION", "").strip()
    return bool(key and region)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _speech_config():
    """Return an azure.cognitiveservices.speech.SpeechConfig or raise."""
    import azure.cognitiveservices.speech as _sdk
    key    = os.environ["AZURE_SPEECH_KEY"].strip()
    region = os.environ["AZURE_SPEECH_REGION"].strip()
    cfg = _sdk.SpeechConfig(subscription=key, region=region)
    return cfg


def _tts_voice(persona_hint: str = "cortana") -> str:
    """
    Map persona → Azure voice name. Reads env vars so users can override.
    Defaults:
      cortana → en-US-CortanaNeural
      jarvis  → en-US-GuyNeural
    """
    hint = persona_hint.lower()
    if "jarvis" in hint:
        return os.environ.get("AZURE_TTS_VOICE_JARVIS", "en-US-GuyNeural").strip()
    return os.environ.get("AZURE_TTS_VOICE_CORTANA", "en-US-CortanaNeural").strip()


# ---------------------------------------------------------------------------
# TTS — returns raw WAV bytes (PCM 16-bit, 16 kHz, mono)
# ---------------------------------------------------------------------------

def synthesize_to_bytes(
    text: str,
    persona: str = "cortana",
    style: Optional[str] = None,
) -> Optional[bytes]:
    """
    Synthesize *text* with Azure Neural TTS and return WAV bytes.

    Returns None if:
      - SDK not installed
      - AZURE_SPEECH_KEY / AZURE_SPEECH_REGION not set
      - Synthesis fails for any reason

    Parameters
    ----------
    text    : str — text to speak (must already be sanitized; no SSML)
    persona : str — "cortana" or "jarvis" → selects the voice
    style   : str | None — speaking style override (e.g. "cheerful", "sad").
              When None, reads AZURE_TTS_STYLE env var; if that is also blank,
              sends plain text without SSML. Only some Neural voices support
              styles — unsupported ones silently ignore the style element.
    """
    if not is_available() or not text:
        return None

    try:
        import azure.cognitiveservices.speech as _sdk

        cfg   = _speech_config()
        voice = _tts_voice(persona)
        cfg.speech_synthesis_voice_name = voice

        # Output: 16kHz 16-bit mono PCM WAV (matches Albedo's AUDIO_SAMPLE_RATE)
        cfg.set_speech_synthesis_output_format(
            _sdk.SpeechSynthesisOutputFormat.Riff16Khz16BitMonoPcm
        )

        # Build SSML only when a style is requested
        effective_style = style or os.environ.get("AZURE_TTS_STYLE", "").strip()
        if effective_style:
            ssml = (
                f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
                f'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="en-US">'
                f'<voice name="{voice}">'
                f'<mstts:express-as style="{effective_style}">'
                f'{_xml_escape(text)}'
                f'</mstts:express-as></voice></speak>'
            )
            synth  = _sdk.SpeechSynthesizer(speech_config=cfg, audio_config=None)
            result = synth.speak_ssml_async(ssml).get()
        else:
            synth  = _sdk.SpeechSynthesizer(speech_config=cfg, audio_config=None)
            result = synth.speak_text_async(text).get()

        if result.reason == _sdk.ResultReason.SynthesizingAudioCompleted:
            return bytes(result.audio_data)

        # Log cancellation details for debugging
        if result.reason == _sdk.ResultReason.Canceled:
            details = _sdk.SpeechSynthesisCancellationDetails(result)
            print(f"[azure_speech] TTS cancelled: {details.reason} — {details.error_details}")
        return None

    except Exception as exc:
        print(f"[azure_speech] TTS error: {exc}")
        return None


def synthesize_to_numpy(
    text: str,
    persona: str = "cortana",
    style: Optional[str] = None,
) -> Optional[tuple[np.ndarray, int]]:
    """
    Convenience wrapper: returns (float32 audio, sample_rate) or None.
    The WAV header is stripped; raw PCM int16 → float32 in [-1, 1].
    """
    wav = synthesize_to_bytes(text, persona=persona, style=style)
    if wav is None:
        return None
    try:
        import soundfile as sf
        audio, sr = sf.read(io.BytesIO(wav), dtype="float32")
        return audio, sr
    except Exception as exc:
        print(f"[azure_speech] WAV decode error: {exc}")
        return None


# ---------------------------------------------------------------------------
# STT — transcribes a numpy audio buffer
# ---------------------------------------------------------------------------

def transcribe(
    audio: np.ndarray,
    sample_rate: int = 16000,
    language: Optional[str] = None,
) -> str:
    """
    Transcribe *audio* (float32 or int16, mono) using Azure Speech STT.

    Returns the transcript string or "" on any failure.

    Parameters
    ----------
    audio       : np.ndarray — raw PCM audio (float32 [-1,1] or int16)
    sample_rate : int       — Hz (default 16000, Albedo standard)
    language    : str|None  — BCP-47 language tag. Defaults to
                              AZURE_STT_LANGUAGE env var, then "en-US".
    """
    if not is_available():
        return ""
    if audio is None or len(audio) == 0:
        return ""

    try:
        import azure.cognitiveservices.speech as _sdk

        # Normalise to int16 PCM
        if audio.dtype != np.int16:
            pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        else:
            pcm = audio

        lang = (
            language
            or os.environ.get("AZURE_STT_LANGUAGE", "en-US").strip()
            or "en-US"
        )

        cfg = _speech_config()
        cfg.speech_recognition_language = lang

        # Push stream — no file I/O required
        fmt = _sdk.audio.AudioStreamFormat(
            samples_per_second=sample_rate,
            bits_per_sample=16,
            channels=1,
        )
        stream     = _sdk.audio.PushAudioInputStream(stream_format=fmt)
        audio_cfg  = _sdk.audio.AudioConfig(stream=stream)
        recognizer = _sdk.SpeechRecognizer(speech_config=cfg, audio_config=audio_cfg)

        stream.write(pcm.tobytes())
        stream.close()

        result = recognizer.recognize_once_async().get()

        if result.reason == _sdk.ResultReason.RecognizedSpeech:
            return result.text.strip()
        if result.reason == _sdk.ResultReason.NoMatch:
            return ""
        if result.reason == _sdk.ResultReason.Canceled:
            details = _sdk.CancellationDetails(result)
            print(f"[azure_speech] STT cancelled: {details.reason} — {details.error_details}")
        return ""

    except Exception as exc:
        print(f"[azure_speech] STT error: {exc}")
        return ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _xml_escape(text: str) -> str:
    """Minimal XML escaping for SSML payloads."""
    return (
        text.replace("&",  "&amp;")
            .replace("<",  "&lt;")
            .replace(">",  "&gt;")
            .replace('"',  "&quot;")
            .replace("'",  "&apos;")
    )
