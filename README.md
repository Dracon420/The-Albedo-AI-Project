# ALBEDO: Spartan-Class Local Assistant

> **Classification:** Personal AI — Hybrid RAG Architecture  
> **Wake Word:** `Cortana`  
> **Ecosystem:** Exotic OS · Chaotic 3D Solutions  
> **Status:** Active Development

---

## Tactical Overview

**Albedo** is a fully local, privacy-first AI assistant built for operators who need real answers — not cloud guesses. It fuses two intelligence streams: a persistent local knowledge base (ChromaDB) and live web reconnaissance (DuckDuckGo), then routes every query through a tiered pipeline before a single word is spoken.

Albedo is not a chatbot. It is a **Spartan-Class command interface** with direct access to your Windows desktop, your 3D printing workflow, and your system telemetry. When you say *Cortana*, it listens. When it doesn't know something for certain, it runs the **Verify Protocol** — cross-referencing local data against live web sources before delivering a diagnosis.

No API keys. No telemetry. No subscription. Runs on your hardware, on your terms.

---

## Key Features

| Capability | Detail |
|---|---|
| **Bridge Control** | Open Interpreter runs OS-level commands, writes and executes code, opens applications, and manages files directly on your Windows desktop |
| **Wake Word: "Cortana"** | OpenWakeWord listens passively on your mic. Drop a custom-trained `.onnx` model in `models/` to replace the placeholder |
| **Hybrid RAG** | Every query hits ChromaDB (local) and optionally DuckDuckGo (web) before reaching the LLM — two sources, one answer |
| **Verify Protocol** | Hardware diagnostic queries automatically trigger a dual-source cross-reference: Exotic OS telemetry + live web data, with explicit conflict reporting |
| **Faster-Whisper STT** | CUDA-accelerated transcription at `int8_float16` precision — keeps Whisper under 0.5 GB VRAM alongside Ollama |
| **Piper TTS** | Low-latency local voice synthesis via the Piper binary — zero cloud dependency, CPU-only so it never touches your VRAM budget |
| **Offline-Capable** | Web search is additive. Albedo runs fully offline; the web layer activates only when you ask or when Verify fires |

---

## Hardware Specifications

| Component | Baseline (Current) | High-Spec (Upgrade Path) |
|---|---|---|
| **CPU** | AMD Ryzen 5 3600 | Ryzen 9 7900X or equivalent |
| **RAM** | 16 GB DDR4 | 32 GB DDR5 |
| **GPU** | NVIDIA RTX 2060 6 GB | NVIDIA RTX 3080+ 10 GB+ |
| **OS** | Windows 11 Home | Windows 11 Pro |
| **Whisper Model** | `small` · `int8_float16` | `medium` · `float16` |
| **LLM (Ollama)** | `mistral` Q4 (~4 GB VRAM) | `mixtral` or `llama3:70b` |
| **RAG top-k** | 5 chunks | 10 chunks |

> **VRAM budget on RTX 2060:** Ollama `mistral` Q4 ≈ 4.0 GB + Whisper `small` int8_float16 ≈ 0.5 GB = **~4.5 GB** — 1.5 GB headroom for ChromaDB ONNX inference.

Switch profiles by selecting tier `[2]` during `install.ps1`, or manually set the variables in `.env`. The `docker-compose.yml` includes a commented high-spec service block ready to uncomment.

---

## Quick Start

### Prerequisites

- Python 3.10 or higher
- [Ollama](https://ollama.com) installed and running (`ollama serve`)
- [NVIDIA drivers](https://www.nvidia.com/drivers) up to date (536.40+ recommended for RTX 2060)
- A microphone connected (for voice mode)

### 1 — Clone the repository

```powershell
git clone https://github.com/Dracon420/Albedo-Local-AI.git
cd Albedo-Local-AI
```

### 2 — Run the installer

```powershell
.\install.ps1
```

The installer will:
1. Create a Python virtual environment (`.venv`)
2. Install all dependencies including Playwright Chromium for web scraping
3. Pre-cache OpenWakeWord models
4. Ask you to select a **hardware tier** (Standard / High-Spec)
5. Prompt for your local directory paths and Piper TTS location
6. Write a configured `.env` file
7. Optionally run the initial ChromaDB index before exiting

### 3 — Pull your Ollama model

```powershell
ollama pull mistral        # standard tier
# or
ollama pull mixtral        # high-spec tier
```

### 4 — Launch Albedo

```powershell
.\.venv\Scripts\Activate.ps1

python main.py              # text chat
python main.py --voice      # wake word + Piper TTS voice mode
python main.py --index      # re-index knowledge base
python main.py --web "query"  # one-shot query with web search forced on
```

> **Voice mode note:** Piper TTS requires the binary and a voice model downloaded separately.  
> Binary: [github.com/rhasspy/piper/releases](https://github.com/rhasspy/piper/releases)  
> Voice: [huggingface.co/rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) — `en_US-ryan-high.onnx` recommended.  
> Set `PIPER_BINARY` and `PIPER_VOICE_MODEL` in `.env`. Until configured, TTS prints to console — nothing breaks.

### Docker (optional)

```powershell
docker compose up
```

Requires [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) for GPU passthrough. Ollama and ChromaDB spin up as health-checked services; Albedo waits for both before starting.

---

## Mission Parameters — Configuring Local Knowledge

Albedo's local RAG is split into two domain collections in ChromaDB. Point each one at your directories, then index.

### Chaotic 3D Solutions

Set `CHAOTIC_3D_PATH` in `.env` to your 3D printing directory:

```env
CHAOTIC_3D_PATH=D:\Chaotic 3D
```

Albedo indexes the following file types from this path:

```
.gcode  .cfg  .ini  .json  .txt  .md  .xml
```

This covers slicer configuration files (PrusaSlicer, Bambu Studio, Cura), print profiles, material settings, and any notes you keep alongside your models. STL binaries are skipped — index your gcode and config exports instead.

### Exotic OS — Herpetology Logs & System Telemetry

Set `EXOTIC_OS_PATH` in `.env` to your Exotic OS working directory:

```env
EXOTIC_OS_PATH=D:\Exotic OS
```

Albedo indexes:

```
.py  .sh  .txt  .md  .log  .json  .yaml  .yml  .toml
```

This is where Albedo learns your system. Store your reptile husbandry records here — enclosure logs, temperature and humidity schedules, feeding records, vet notes — alongside any Python code, diagnostic output, or system logs from your Exotic OS builds. Albedo treats all of it as searchable context.

### Running or re-running the index

```powershell
python main.py --index
```

The indexer is incremental — it skips files already in ChromaDB and only processes new or previously unseen content. Run it any time you add files to either directory. Progress is printed per-batch; memory usage is capped at 50 chunks per ChromaDB write to stay stable on 16 GB RAM.

---

## Verify Protocol

When any query contains hardware-related language (`gpu`, `crash`, `temperature`, `driver`, `bsod`, `vram`, and others), Albedo automatically activates the **Verify Protocol**:

1. Retrieves matching records from the **Exotic OS ChromaDB collection** (your local telemetry)
2. Runs a parallel **DuckDuckGo web search** on the same query
3. Builds a structured synthesis prompt that presents both sources side-by-side
4. Explicitly flags any conflict between local findings and external documentation

This prevents hallucinated hardware advice. If your logs say one thing and the web says another, Albedo tells you — it does not silently pick one.

---

## Architecture

```
[Microphone]
     |
  OpenWakeWord  <-- passive listener, CPU
     | "Cortana"
  Piper TTS: "Yes?"
     |
  Faster-Whisper (CUDA)  -->  transcribed text
     |
  ┌──────────────── pipeline.run() ─────────────────┐
  │                                                  │
  │  Hardware query?  ──YES──>  Verify Protocol      │
  │       |                     Local RAG (Exotic OS)│
  │       NO                  + Web Search           │
  │       |                     Synthesis prompt     │
  │  ChromaDB query                  |               │
  │  (Chaotic 3D + Exotic OS)        |               │
  │  + optional Web Search           |               │
  │       |                          |               │
  └───────┴──────────────────────────┘               │
                     |
              Open Interpreter
              (Ollama backend + Bridge Control)
                     |
              Piper TTS  -->  [Speakers]
```

---

## Running Smoke Tests

```powershell
python tests/smoke_test.py
```

Tests local RAG indexing, live web search, Verify Protocol routing, and indexer RAM footprint. All 13 assertions pass on the baseline hardware configuration.

---

## Stack

| Layer | Technology |
|---|---|
| LLM runtime | [Ollama](https://ollama.com) |
| Agent / desktop control | [Open Interpreter](https://github.com/OpenInterpreter/open-interpreter) |
| Vector store | [ChromaDB](https://www.trychroma.com) |
| Embeddings | `all-MiniLM-L6-v2` via ChromaDB ONNX (CPU) |
| Speech-to-text | [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) |
| Wake word | [OpenWakeWord](https://github.com/dscripka/openWakeWord) |
| Text-to-speech | [Piper](https://github.com/rhasspy/piper) |
| Web search | [ddgs](https://github.com/deedy5/ddgs) (DuckDuckGo, no API key) |
| Web scraping | Playwright · Trafilatura · BeautifulSoup4 |

---

*Albedo is a local system. It does not call home.*
