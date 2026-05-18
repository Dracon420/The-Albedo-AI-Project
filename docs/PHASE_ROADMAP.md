# Phase II Cyberdeck Overhaul — Roadmap & Decisions

This document tracks the architecture overhaul of Albedo from the v2.0.2 Tkinter
GUI to the v3.0 Eel + HTML/CSS/JS Cyberdeck UI. Each phase has its own commit
on the `phase-2-cyberdeck` branch (or a successor branch). Phases are
**independent and individually shippable** wherever possible — the
no-UI-impact phases (1, 3, 5, 6) can all merge to master as point releases
on the 2.x line while the bigger Eel + audio work lives on its own branch.

## Status

| # | Phase | Status | Commit |
|---|---|---|---|
| 1 | Black box + hardware cache | shipped | `62d09e5` |
| 3 | Live telemetry with deltas | shipped | `39021f5` |
| 5 | Safety interceptor + 127.0.0.1 webhook | shipped | `8b76b7f` |
| 6 | Hardware assignment protocol | **queued — implement at start of Phase 4** | — |
| 4 | Audio stack (Kokoro + Deepgram + distil-whisper + wake-word toggle) | not started | — |
| 2 | Eel + HTML/CSS/JS frontend | not started | — |

## Phase ordering rationale

The original directive listed phases 1→5 in numeric order, but the dependency
graph isn't linear:

- Phases 1, 3, 5 are pure backend infrastructure with no UI coupling — they
  can land in any order and on any UI stack (Tk or Eel). Done.
- Phase 6 (resource binding) is configuration *for the models Phase 4
  introduces*. Building it before Phase 4 means Phase 4's model loaders
  consume the policy from line 1, rather than being retrofitted after.
- Phase 4 (audio) depends on Phase 6 (resource policy) and benefits from
  Phase 2 (UI) but doesn't require it — could ship a headless audio
  upgrade on the Tk GUI if needed.
- Phase 2 (Eel frontend) is the biggest piece by far. Should be its own
  dedicated session(s), and lands last so it has every backend feature
  it needs to bind to.

## Phase 6 — Hardware Assignment Protocol

**Goal:** Pin each ML/runtime component to specific execution hardware so
the 6 GB VRAM budget on the target RTX 2060 isn't blown by simultaneous
loads.

**Implementation deferred** until Phase 4 starts — speculation about model
APIs we haven't integrated yet would force rework. When Phase 4 begins,
Phase 6 is the first sub-task: build `albedo/resource_policy.py` BEFORE
the Kokoro/whisper loaders so they consume the policy from line 1.

### Resource map (binding contract)

| Component | Bound to | Fallback | Load strategy |
|---|---|---|---|
| OpenWakeWord listener | CPU (ONNX `CPUExecutionProvider`) | none | eager at boot |
| Kokoro TTS | CPU (ONNX `CPUExecutionProvider`) | none | eager at boot |
| distil-whisper STT | CUDA | **CPU with audible-quality warning** | **lazy — only on Deepgram failure** |
| Eel server | CPU (asyncio) | — | eager |
| Delta calculator (`albedo/telemetry.py`) | CPU | — | eager (already CPU-bound) |
| Ollama LLM | Ollama-managed | — | external |

### Two fixes to the original directive (agreed)

The original directive said *"explicitly initialize the distil-whisper
model with `device='cuda'`"* — taken literally that breaks Albedo on every
non-NVIDIA machine and risks OOMing Ollama on RTX 2060.

**Fix 1: CUDA-with-CPU-fallback.** If `torch.cuda.is_available()` returns
False, distil-whisper falls back to CPU and logs an audible-quality
warning to the user via the chat feed. This makes the offline fallback
*available* on Mac, AMD GPU, Intel Arc, and integrated-graphics laptops
even if it's slower.

**Fix 2: Lazy whisper loading.** Don't load distil-whisper into VRAM at
startup. Only load it the first time the Deepgram WebSocket fails. Under
normal operation (Deepgram up) the LLM gets the full VRAM budget; only
during cloud outages does whisper compete for VRAM, at which point a brief
LLM pause is acceptable.

### Public API (target)

```python
from albedo.resource_policy import (
    providers_for,      # ONNX providers list for a component
    device_for,         # "cuda" | "cpu" — for torch / transformers
    should_load_eagerly,  # True for OWW/Kokoro/Eel, False for whisper
    vram_budget_mb,     # advisory cap for a component
    log_resource_map,   # dumps active policy to logs/resource_map.log
)

# Phase 4 loaders use it like this:
wakeword = OpenWakeWord(providers=providers_for("wakeword"))
tts      = KokoroONNX(model_path, providers=providers_for("tts_kokoro"))

def _load_whisper_fallback():       # called only on Deepgram failure
    return WhisperModel(
        "distil-small.en",
        device=device_for("stt_whisper"),
    )
```

### Startup behavior

`resource_policy.detect()` runs once at boot:

1. Reads existing `hardware_config.json` (Phase 1) for the cached GPU info.
2. Probes `torch.cuda.is_available()` and `nvidia-smi` to confirm CUDA is
   actually working (cache could be stale after a driver crash).
3. Computes the effective device map by checking the policy against
   reality — every "want CUDA" entry that can't get it gets demoted to
   its fallback chain.
4. Appends the resulting map to `hardware_config.json` under a `resource_map`
   key for the crash recorder to include in reports.
5. Writes a human-readable copy to `logs/resource_map.log`.

### Tests to write (with Phase 6 implementation)

- `test_cpu_fallback_when_no_cuda` — torch.cuda mocked to False → whisper
  policy returns `device="cpu"`, warning is logged.
- `test_cuda_used_when_available` — torch.cuda mocked to True → whisper
  policy returns `device="cuda"`.
- `test_lazy_components_not_loaded_at_boot` — `should_load_eagerly("stt_whisper")`
  returns False; `should_load_eagerly("tts_kokoro")` returns True.
- `test_providers_for_cpu_component` — `providers_for("tts_kokoro")` ==
  `["CPUExecutionProvider"]`.
- `test_resource_map_persisted_to_hardware_config` — after `detect()`,
  `hardware_config.json` gains a `resource_map` key.
- `test_unknown_component_raises_keyerror` — typo-protection.

## Phase 4 — Audio Stack

**Depends on Phase 6.** Three new ML runtimes, one new websocket protocol,
new UI control panel. Estimated 15-20 hours.

### Components

1. **Kokoro TTS** (`albedo/audio/tts_kokoro.py`) — local ONNX runtime,
   CPU-bound per Phase 6, replaces current Piper TTS path. Piper stays
   as a fallback for one release to ease migration.

2. **Deepgram WebSocket STT** (`albedo/audio/stt_deepgram.py`) — primary
   STT, cloud-backed, zero local cost. Requires API key in `.env`
   (`DEEPGRAM_API_KEY`). Streams audio chunks and emits partial + final
   transcripts. New dependency: `deepgram-sdk` or hand-rolled websocket
   client.

3. **distil-whisper fallback** (`albedo/audio/stt_whisper.py`) —
   CUDA-with-CPU-fallback per Phase 6 fix 1. Lazy-loaded per Phase 6
   fix 2. Triggered when Deepgram websocket fails or returns >2s with
   no partial.

4. **Wake-word toggle UI** — three controls on the chat panel:
   - Master mode switch: Push-to-Talk vs. Latch
   - Main MIC button (visual recording state)
   - Wake-word arm/disarm (background OpenWakeWord thread for
     "Hey Cortana" / "Jarvis")

### Migration plan

- Keep current Vosk STT and Piper TTS as the v2.x backward-compat path.
- Add `AUDIO_STACK=v2|v3` env var so users can opt into the new stack
  per-install before we make v3 the default.
- One release of side-by-side operation, then deprecate v2 stack.

### Open questions for Phase 4 kickoff

- Should wake-word detection migrate from Vosk grammar back to dedicated
  OpenWakeWord (better accuracy) or stay Vosk-based (smaller dep tree)?
- Deepgram has multiple models (`nova-2`, `nova-2-general`, `whisper-large`)
  — which to default to? Probably `nova-2` for latency.

## Phase 2 — Eel Frontend

**Independent of everything else** but should land last because it's the
biggest change and benefits from having every backend feature it'll
display already implemented.

Strips CustomTkinter, replaces with `eel` + a `web/` directory:

```
web/
  index.html
  static/
    css/
      cyberdeck.css        — frosted glass, alpha transparency
      gauges.css           — SVG winged-triangle gauge styling
    js/
      app.js               — top-level controller
      gauges.js            — SVG ring rendering from telemetry payload
      drawer.js            — off-canvas tactical drawer
      swarm.js             — LED status bar logic
      approval.js          — Y/N approval dialog for safety_catch
  backgrounds/             — 4 .png files (toggled)
```

Eel exposes the existing backend modules as JS-callable:

- `eel.get_full_telemetry()` → `telemetry.get_full_telemetry()`
- `eel.send_query(text)` → routes through `albedo.pipeline.run()`
- `eel.approve_command(id, decision)` → resolves a safety_catch request
- `eel.push_update_to_ui(update)` → consumed via webhook pop_pending_updates

Two-window rule: keep the existing DEVELOPER CONSOLE window. The main
Mission Control window goes Eel; the dev console stays Tk (or becomes a
second Eel window) so logs/stderr stay visible during the rewrite.

## Releasing as v2.1.0

Current `phase-2-cyberdeck` branch (Phases 1+3+5) is mergeable to master
as **v2.1.0** without any of the audio/UI work landed. Decision deferred
to the next session — when ready:

1. Bump `VERSION` to `2.1.0` and `albedo.iss` AppVersion to match.
2. Update README (status badge, what's new section).
3. Merge `phase-2-cyberdeck` to master via PR.
4. Compile new installer, attach to GitHub release `v2.1.0`.
5. Tag and publish release notes.

Audio + Eel work resumes on a fresh branch from the new master tip.
