"""
Albedo FastAPI Bridge — Tailscale network server for the mobile client.

Endpoints
---------
GET  /api/status          Health check + model info.
POST /api/chat            Accept text, return text response + base64 WAV.
POST /api/voice           Accept .wav upload, return transcript + text + base64 WAV.

Run
---
    python server.py
    # or via uvicorn directly:
    uvicorn server:app --host 0.0.0.0 --port 8000

The server binds to 0.0.0.0:8000 so it is reachable over Tailscale from any
device on the tailnet. Pair with Tailscale ACLs to restrict access to your own
devices only.

Audio contract
--------------
Both /api/chat and /api/voice return `audio_b64`: a base64-encoded standard
WAV file. The mobile client decodes and plays it directly. If Piper TTS is not
installed, `audio_b64` is null and the client falls back to displaying text.
"""

import asyncio
import base64
import io
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Annotated

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from albedo.audio.tts import synthesize_to_bytes
from albedo.config import OLLAMA_MODEL, VOSK_MODEL_PATH
from albedo.pipeline import run as pipeline_run
from albedo.verify import is_hardware_query

# STT is lazily imported inside _load_and_transcribe() so the server starts
# successfully even when vosk is not yet installed.
# /api/voice returns 503 if Vosk is unavailable at call time.
_transcribe_fn = None


def _get_transcribe():
    global _transcribe_fn
    if _transcribe_fn is None:
        try:
            from albedo.audio.stt import transcribe
            _transcribe_fn = transcribe
        except ImportError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Vosk STT not available: {exc}. Run: pip install vosk",
            ) from exc
    return _transcribe_fn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("albedo.server")

app = FastAPI(
    title="Albedo Bridge",
    description="Hybrid RAG + voice API for the Albedo mobile client.",
    version="1.0.0",
)

# Allow the Expo dev client and production mobile app to call the API.
# Tailscale handles network-level access control; CORS covers browser clients.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Single-worker executor: GPU is single-stream on RTX 2060.
# Requests queue rather than race for VRAM.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="albedo-worker")

TARGET_SR = 16_000  # Hz — Vosk and Piper both expect 16 kHz


# ── Helpers ───────────────────────────────────────────────────────────────────

def _encode_audio(wav_bytes: bytes | None) -> str | None:
    if not wav_bytes:
        return None
    return base64.b64encode(wav_bytes).decode("utf-8")


def _load_wav_to_array(data: bytes) -> np.ndarray:
    """Read uploaded audio bytes into a float32 mono array at TARGET_SR."""
    audio, sr = sf.read(io.BytesIO(data), dtype="float32")

    # Flatten to mono
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    # Resample if needed
    if sr != TARGET_SR:
        from scipy.signal import resample as scipy_resample
        n_samples = int(len(audio) * TARGET_SR / sr)
        audio = scipy_resample(audio, n_samples).astype(np.float32)

    return audio


def _run_pipeline(text: str, use_web: bool) -> tuple[str, str | None]:
    """Run pipeline + TTS in the thread executor (blocking, GPU-bound)."""
    verify_fired = is_hardware_query(text)
    log.info("query=%r verify=%s use_web=%s", text[:80], verify_fired, use_web)
    response_text = pipeline_run(text, use_web=use_web)
    wav_bytes = synthesize_to_bytes(response_text)
    return response_text, _encode_audio(wav_bytes)


# ── Schemas ───────────────────────────────────────────────────────────────────

class StatusResponse(BaseModel):
    status: str
    llm_model: str
    stt_engine: str
    stt_model: str


class ChatRequest(BaseModel):
    text: str
    use_web: bool = False


class ChatResponse(BaseModel):
    text: str
    audio_b64: str | None = None
    verify_protocol: bool = False


class VoiceResponse(BaseModel):
    transcript: str
    text: str
    audio_b64: str | None = None
    verify_protocol: bool = False


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/status", response_model=StatusResponse)
async def get_status():
    return StatusResponse(
        status="online",
        llm_model=OLLAMA_MODEL,
        stt_engine="vosk",
        stt_model=Path(VOSK_MODEL_PATH).name,
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not req.text.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="text must not be empty")

    loop = asyncio.get_event_loop()
    response_text, audio_b64 = await loop.run_in_executor(
        _executor,
        lambda: _run_pipeline(req.text.strip(), req.use_web),
    )

    return ChatResponse(
        text=response_text,
        audio_b64=audio_b64,
        verify_protocol=is_hardware_query(req.text),
    )


@app.post("/api/voice", response_model=VoiceResponse)
async def voice(file: Annotated[UploadFile, File(description="16 kHz mono WAV recording")]):
    # Validate content type loosely — mobile clients may send audio/wav or audio/x-wav
    if file.content_type and not file.content_type.startswith("audio/"):
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            detail=f"Expected audio/wav, got {file.content_type}")

    raw = await file.read()
    if len(raw) < 1024:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Audio file too small to contain speech")

    loop = asyncio.get_event_loop()

    # STT — run in executor so we don't block the event loop during CUDA inference
    transcribe = _get_transcribe()
    audio_array = await loop.run_in_executor(_executor, lambda: _load_wav_to_array(raw))
    transcript = await loop.run_in_executor(_executor, lambda: transcribe(audio_array))

    if not transcript:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="No speech detected in audio")

    log.info("transcript=%r", transcript[:120])

    response_text, audio_b64 = await loop.run_in_executor(
        _executor,
        lambda: _run_pipeline(transcript, use_web=False),
    )

    return VoiceResponse(
        transcript=transcript,
        text=response_text,
        audio_b64=audio_b64,
        verify_protocol=is_hardware_query(transcript),
    )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    log.info("Starting Albedo Bridge on 0.0.0.0:8000")
    log.info("LLM: %s | STT: vosk (%s)", OLLAMA_MODEL, Path(VOSK_MODEL_PATH).name)
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False, log_level="info")
