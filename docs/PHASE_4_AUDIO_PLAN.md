# Phase 4 — Audio Stack Kickoff Plan

Phase 6 (resource policy) is now shipped. This document captures the
remaining Phase 4 work so the next session can resume cleanly.

## Current state

| Sub-task | Status |
|---|---|
| Phase 6 — `albedo/resource_policy.py` | ✅ shipped, 16 tests |
| Kokoro TTS loader (N+1) | ✅ shipped, 13 tests |
| Deepgram REST STT (N+2) | ✅ shipped, 10 tests |
| distil-whisper fallback, lazy CUDA (N+2) | ✅ shipped, 10 tests |
| STT router with failover audit (N+2) | ✅ shipped, 8 tests |
| Wake-word toggle UI panel + PTT (N+3) | ✅ shipped, 14 tests |

**Phase 4 complete.** All audio sub-tasks have shipped to the
`phase-2-cyberdeck` branch. The remaining cyberdeck work is **Phase 2 —
Eel HTML/CSS/JS frontend**, which is independent and can be its own
dedicated multi-session project.

The resource policy is the **contract** every audio loader must consume.
The pre-existing `albedo/audio/` modules (stt.py = Vosk, tts.py = Piper)
stay untouched in v2.x — Phase 4 ADDS new loaders alongside them and
introduces an env-var switch to pick the stack.

## Environment matrix discovered during Phase 6

This dev box surfaced a non-trivial reality:

```
torch         2.12.0+cpu       (CPU-only build — no CUDA runtime)
onnxruntime   1.26.0           (CPU-only — Azure + CPU providers)
nvidia-smi    works            (RTX 2060 reports correctly)
```

So `resource_policy.detect()` correctly demotes `stt_whisper` to CPU
even though the hardware has a real GPU. **First requirements.txt change
for Phase 4 will be adding the CUDA-capable torch/onnxruntime builds**
to the install instructions (the .iss-driven installer may or may not
need new logic — likely the user-side `pip install` step picks them up
when `nvidia-smi` is present).

## Sub-task 1: Kokoro TTS

**File:** `albedo/audio/tts_kokoro.py`

**New dependency:** `kokoro-onnx` (PyPI) + the ONNX model + voices.json.
Model download is ~300 MB so it goes through `setup_utility.py` like the
Piper voice download already does.

**API surface:**
```python
class KokoroTTS:
    def __init__(self):
        from albedo.resource_policy import providers_for
        self._session = kokoro_onnx.Kokoro(
            model_path,
            voices_path,
            providers=providers_for("tts_kokoro"),
        )

    def synthesize_to_bytes(self, text: str, voice: str = "af_sky") -> bytes:
        """Return WAV bytes — drop-in compatible with current tts.synthesize_to_bytes."""
        ...
```

**Integration:**
- Add `AUDIO_TTS=kokoro|piper` env var in `.env`. Default to `piper` for v2.x backwards compat.
- `albedo/audio/tts.py` becomes a thin dispatcher that reads the env var and routes to either the Piper code or `tts_kokoro.KokoroTTS`.
- Keep `synthesize_to_bytes(text)` contract identical so server.py and any callers don't need to know which engine.

**Testing:** mock the ONNX session, verify providers_for("tts_kokoro") is consulted exactly once at init, verify the WAV output is non-empty.

## Sub-task 2: Deepgram WebSocket STT

**File:** `albedo/audio/stt_deepgram.py`

**New dependency:** `deepgram-sdk` (PyPI, ~2 MB pure Python).

**API surface:**
```python
class DeepgramStreamingSTT:
    def __init__(self):
        self._key = os.environ["DEEPGRAM_API_KEY"]
        # Asyncio websocket — kept open across utterances
        ...

    async def transcribe_chunk(self, pcm_bytes: bytes) -> tuple[str, bool]:
        """Returns (text_so_far, is_final). Streams audio in, partials out."""
        ...

    async def close(self): ...
```

**Integration:**
- New `.env` keys: `DEEPGRAM_API_KEY` (required to enable), `DEEPGRAM_MODEL` (defaults to `nova-2`).
- `setup_utility.py` adds an API key field on the same page as Gemini/Groq/Together with the existing `_api_row` helper.
- If `DEEPGRAM_API_KEY` is empty, the stack silently falls through to whisper-only.

**Failure path → triggers Sub-task 3:**
A new `albedo/audio/stt_router.py` module owns the failover logic:
1. Try Deepgram. If the websocket fails to connect within 1.5 s, OR
   no partial transcript arrives within 2 s of the user speaking, OR
   the websocket dies mid-utterance:
2. Tear down Deepgram, lazy-load whisper, retry the SAME audio buffer.
3. Log the demotion to the chat feed so the user knows STT quality changed.

## Sub-task 3: distil-whisper fallback (lazy CUDA)

**File:** `albedo/audio/stt_whisper.py`

**Dependency:** `faster-whisper` (already installed: 1.2.1) — uses the
distil-small.en model.

**API surface:**
```python
_model_singleton: WhisperModel | None = None

def get_model() -> "WhisperModel":
    """Lazy-load on first call. Respects resource_policy.device_for('stt_whisper')."""
    global _model_singleton
    if _model_singleton is None:
        from albedo.resource_policy import device_for
        from faster_whisper import WhisperModel
        device = device_for("stt_whisper")
        # CPU-build of torch demoted us → tell the user
        if device == "cpu":
            print("[stt_whisper] CUDA unavailable — loading on CPU (slower).")
        _model_singleton = WhisperModel(
            "distil-small.en",
            device=device,
            compute_type="float16" if device == "cuda" else "int8",
        )
    return _model_singleton

def transcribe(audio_int16: np.ndarray) -> str:
    segments, _ = get_model().transcribe(audio_float32_from(audio_int16))
    return " ".join(s.text for s in segments).strip()
```

**Critical:** `get_model()` is NOT called at import time. The first call
to `transcribe()` triggers the load. Phase 6's `should_load_eagerly()`
already returns False for this component — the audio router must respect
that and only invoke when Deepgram has actually failed.

## Sub-task 4: Wake-word toggle UI panel

**Scope:** Three controls bolted into the chat panel (gui.py for v2.x,
Eel for v3.x once Phase 2 lands).

| Control | Behavior |
|---|---|
| **Mode toggle** | Push-to-Talk (hold MIC button) ↔ Latch (click to start, click to stop) |
| **MIC button** | Visual state: idle / recording / processing / locked-by-wake |
| **Wake-word arm/disarm** | Enables/disables the OpenWakeWord background listener thread |

**Backend module:** `albedo/audio/comm_mode.py` — pure state machine, no UI:

```python
class CommMode(Enum):
    PUSH_TO_TALK = "ptt"
    LATCH        = "latch"

class WakeState(Enum):
    ARMED   = "armed"
    DISARMED = "disarmed"

# Persisted across runs via settings.json
def get_mode() -> CommMode: ...
def set_mode(m: CommMode) -> None: ...
def get_wake_state() -> WakeState: ...
def set_wake_state(s: WakeState) -> None: ...
```

UI binds to these — gui.py shows three buttons, Eel shows three CSS
toggles. Both call the same backend.

## Session-by-session plan

**Estimated remaining: 12-18 hours, 2-3 sessions.**

| Session | Goal | Deliverable |
|---|---|---|
| N+1 | Kokoro TTS loader + dispatcher | `tts_kokoro.py`, env var, tests, Piper still default |
| N+2 | Deepgram STT + whisper fallback + router | `stt_deepgram.py`, `stt_whisper.py`, `stt_router.py`, tests, integration with `albedo/listener.py` |
| N+3 | Wake-word UI panel + comm_mode state | `comm_mode.py`, gui.py panel, settings.json persistence, tests |

After N+3 the audio stack is v3-ready. Phase 2 (Eel rewrite) can then
consume the same `comm_mode` and audio modules without further backend
work.

## What to NOT do in Phase 4

- **Do not rip out Vosk or Piper.** They stay as backward-compat
  fallbacks for one full release after the new stack lands.
- **Do not ship without the `AUDIO_STACK` env var switch.** Users on
  v2.0.2 upgrading mid-conversation should be able to try the new stack,
  hit a problem, set `AUDIO_STACK=v2`, and have the old behavior back.
- **Do not change the chat-pipeline API.** `pipeline.run(query)` keeps
  taking text and returning text — only the bytes going in and out of
  audio change.
