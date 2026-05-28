# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ⚠️ MANDATORY PROTOCOLS — Follow Every Session

### 1. Session Start — Read the Vault

Before touching any code, read these files:

```
C:\Users\demon\Desktop\Claudes Brain\Claude_Brain\Albedo\
  00_Project_Overview.md          <- identity, file map, git info
  02_Implemented_Features.md      <- everything built (running log)
  03_Known_Issues_and_Gotchas.md  <- CRITICAL: prevents repeating past mistakes
  06_Session_Log.md               <- what changed recently
  08_Live_State.md                <- Ollama models, key status, packages (auto-gen)
```

The vault is ground truth. Chat context is compacted; vault is not.
If chat summary contradicts the vault, **trust the vault**.

### 2. Pre-Edit Protocol — Before Touching Any File

Before editing ANY file in this project:

1. Read `10_Code_Snapshot.md` section for that file — note every public function listed
2. Read `09_File_Dependency_Map.md` section for that file — identify what calls it
3. Make your edit
4. Verify all functions that were in the snapshot are still present (or intentionally changed)
5. Run `python -m albedo.tools.sync_brain` to update the snapshot

**If a function existed in the snapshot but is gone after your edit = regression. Fix it.**

Key files where regressions are catastrophic:
- `tts.py` — speak(), speak_streamed(), synthesize_to_bytes(), stop_audio(), enqueue_speech()
- `stt.py` — transcribe(), prewarm()
- `swarm.py` — swarm_chat(), direct_gemini_search(), query_gemini(), query_groq()
- `bridge.py` — all @eel.expose functions (JS calls these by name)
- `app.py` — open_widget_window(), run_pipeline(), widget_mic_press()
- `pipeline.py` — run()

### 3. After Significant Changes

- Add entry to `06_Session_Log.md` (date, what changed, what files)
- Update `02_Implemented_Features.md` if a feature was added/removed
- Update `03_Known_Issues_and_Gotchas.md` if a new gotcha was discovered
- Run `python -m albedo.tools.sync_brain`

## Project Identity

**Albedo** is a Spartan-Class local AI assistant with Hybrid Retrieval-Augmented Generation (Hybrid RAG).

- **Wake words:** "Cortana" (routes to Cortana persona), "Jarvis" (routes to JARVIS persona)
- **Purpose:** A locally-run assistant combining fine-tuned local models, indexed local knowledge, and multi-source web retrieval.

## Hardware Target

| Component | Spec |
|-----------|------|
| OS | Windows 11 |
| GPU | NVIDIA RTX 2060 6 GB VRAM |
| RAM | 16 GB (upgrading to 32 GB) |

VRAM ceiling: 6 GB. All models must be Q4_K_M quantized. ChromaDB embeddings and Faster-Whisper run concurrently — budget ~1 GB for them.

## LLM Models

Two custom-trained Qwen2.5-7B models are the primary inference backend:

| Ollama name | Description |
|-------------|-------------|
| `albedo-cortana-8b` | Qwen2.5-7B-Instruct fine-tuned on Cortana persona (QLoRA, Azure T4, rank 32+64 runs) |
| `albedo-jarvis-8b` | Qwen2.5-7B-Instruct fine-tuned on JARVIS persona (same training pipeline) |
| `albedo-cortana` | Legacy 1.9 GB baseline — fallback only |
| `albedo-jarvis` | Legacy 1.9 GB baseline — fallback only |

GGUF files are stored in `outputs/gguf_azure/`. Modelfiles are in `outputs/gguf_azure/Modelfile_*`.

## Stack

| Layer | Technology |
|-------|------------|
| LLM runtime | Ollama (primary), cloud swarm (Gemini → Groq, fallback) |
| Agent / OS control | Open Interpreter (bridge.py) |
| Vector store | ChromaDB |
| Speech-to-text | Vosk (default offline) / Azure Speech / Groq Whisper / Deepgram — tiered waterfall |
| TTS | Azure Neural (Tier 0) → XTTS-v2 (Tier 1) → Edge-TTS → Kokoro → Piper — tiered waterfall |
| Wake word detection | Vosk restricted grammar |

## Architecture: Hybrid RAG

Query pipeline in `albedo/pipeline.py` — interceptors fire in order:

1. **Identity query** → hardcoded response, no LLM
2. **Wolfram Alpha** (`albedo/web/wolfram.py`) → math, units, computation. Returns exact answer, bypasses LLM entirely. Requires `WOLFRAM_API_KEY`.
3. **Overclocking / hardware optimization** → injects live sensor data, routes to cloud swarm
4. **System optimize / registry** → runs disk cleanup + prefetch clear
5. **Tactical hardware audit** → live sensor SitRep via `diagnostics.py`
6. **File count** → resolved via pathlib, never via LLM
7. **Launch / Kill / Process / Disk / Download** → direct OS control
8. **Conversational bypass** → short social exchanges direct to cloud swarm
9. **Hardware Verify protocol** → fault-diagnosis path for error/crash queries
10. **Standard RAG** → ChromaDB + Wikipedia (`albedo/web/wikipedia.py`) + Tavily/DDG web search → merged context → LLM

### Web Search Priority

`albedo/web/search.py` uses:
1. **Tavily** (if `TAVILY_API_KEY` set) — 1,000/month free, AI-optimised structured results
2. **DuckDuckGo** (`ddgs`) — unofficial fallback, no key required

### LLM Routing (bridge.py)

Priority: **Azure OpenAI → Gemini → Groq → Open Interpreter (Ollama) → bare Ollama**

- Wake word "cortana" → `albedo-cortana-8b` + Cortana system prompt
- Wake word "jarvis" → `albedo-jarvis-8b` + JARVIS system prompt
- Cloud APIs (Gemini/Groq) always get the full persona system prompt
- Ollama is offline fallback only

## Key Design Constraints

- All inference must run **offline-capable** (cloud APIs and web search are additive).
- ChromaDB collections scoped per knowledge domain (3D printing, Exotic OS, reptile husbandry).
- Wikipedia integration (`albedo/web/wikipedia.py`) is always active — no key required.
- Wolfram Alpha intercepts computation queries before the LLM ever sees them — this is intentional and must not be bypassed.
- Never add a raw HTTP scraping layer — use the sanctioned search modules.
- Security: `.env` is gitignored. Remote: `old-origin`. Branch: `phase-2-cyberdeck`.
