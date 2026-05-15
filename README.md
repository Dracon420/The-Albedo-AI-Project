<div align="center">

<img src="./albedo_icon.jpg" alt="Albedo Icon" width="160"/>

# ALBEDO // MISSION CONTROL

**A Spartan-class, locally hosted, multi-persona AI construct.**
Built to operate free of commercial constraints, providing absolute loyalty and universal assistance,
while natively managing the hardware ecosystems of Chaotic 3D Systems and Exotic OS.

---

![Platform](https://img.shields.io/badge/Platform-Windows%2011-0078D4?style=flat-square&logo=windows)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python)
![Ollama](https://img.shields.io/badge/LLM-Ollama%20%7C%20Llama%203.2-black?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Status](https://img.shields.io/badge/Status-V1%20Golden%20Master-00F5FF?style=flat-square)

</div>

---

## OPERATIONAL BRIEFING

Albedo is not a chatbot. It is an AI construct — a fully local, offline-capable intelligence framework engineered for absolute system control. No cloud endpoints. No API subscriptions. No telemetry. Every inference cycle executes on your hardware, under your authority.

The system fuses a **Hybrid Retrieval-Augmented Generation (Hybrid RAG)** pipeline with live web search capability, a multimodal vision cortex, and a dual-persona voice interface — all orchestrated through a stealth-deployed GUI that leaves no console footprint.

When given a directive, Albedo executes it.

---

## CORE ARCHITECTURE

### 100% Local Processing

Powered by **Llama 3.2:3b** via Ollama, quantized and memory-mapped to operate within the 6 GB VRAM envelope of an RTX 2060. ChromaDB vector embeddings run on CPU to preserve every byte of VRAM for inference. Offline-first by design — web search is additive intelligence, not a dependency.

### Zero-Latency Audio Pipeline

**Faster-Whisper** (`small`, `int8_float16`) loads on a daemon thread at startup, eliminating the cold-start penalty on the first voice command. The **OpenWakeWord** listener runs a parallel VAD loop with 80 ms inference frames, checking the stop event every chunk so `STOP` response is instantaneous rather than waiting for the silence gate.

### Dynamic Multi-Persona Engine

Albedo ships with two fully synchronized AI personas. Switching persona in **SETTINGS** simultaneously hot-swaps the TTS voice model, updates the active wake word model in memory, and persists the configuration — no restart required.

| Persona | Voice Model | Wake Word Model | Character |
|---|---|---|---|
| **Cortana** | `en_US-kristin-medium.onnx` (female) | `hey_core_tah_nuh.onnx` | Primary construct |
| **Jarvis** | `en_US-ryan-medium.onnx` (male) | `hey_jarvis_v0.1.onnx` | Secondary construct |

Both voice models are downloaded automatically by the installer from the official Piper HuggingFace repository. The bundled Piper binary runs entirely on CPU, preserving the full VRAM budget for the LLM.

### Multimodal Vision Cortex

The **SCAN** button activates the hardware vision bridge. A live frame is captured from the connected webcam via OpenCV, JPEG-encoded, and dispatched to the **Moondream** multimodal model running inside Ollama. The analysis is returned as a natural-language report, spoken aloud by the active persona's TTS voice, and logged to the Mission Control chat window. Environmental awareness on demand.

### Hybrid RAG Knowledge Architecture

Three indexed knowledge domains, each scoped to its own ChromaDB collection:

| Collection | Domain | Indexed File Types |
|---|---|---|
| `chaotic_3d` | 3D printing — STL manifests, slicer configs, print profiles | `.gcode` `.cfg` `.ini` `.json` `.txt` `.md` `.xml` |
| `exotic_os` | Python source, logs, reptile husbandry records | `.py` `.sh` `.log` `.txt` `.md` `.json` `.yaml` `.toml` |

Every query simultaneously hits both local ChromaDB and DuckDuckGo web search. Results are ranked, merged, and injected into the LLM context window before generation. Queries shorter than 5 characters bypass RAG entirely to prevent noise.

### Stealth Deployment Architecture

Albedo runs under **`pythonw.exe`** — the windowless Python launcher. There is no console window for a user to accidentally close. The **LOGS** button in the Mission Control header opens an in-app **Developer Console** that captures all `stdout`/`stderr` output from every module, including the live Whisper pre-warm status, Ollama bridge responses, and ChromaDB indexing progress. Background `sys.stdout` and `sys.stderr` are redirected to the console buffer at startup so nothing is silently discarded.

---

## QUICK START — DEPLOYMENT

### Standard Deployment *(Recommended)*

**No terminal. No configuration. One installer.**

<div align="center">

### [⬇ Download Albedo-Setup.exe](https://github.com/Dracon420/Albedo-Local-AI/raw/master/Albedo-Setup.exe)

</div>

**Pre-flight requirements — the installer verifies all of these automatically:**

| Requirement | Specification | Auto-install |
|---|---|---|
| OS | Windows 10 / 11 (64-bit) | — |
| Python | 3.12 | Guided via winget |
| Ollama | Latest | Yes, via winget |
| GPU VRAM | 4 GB minimum · 6 GB recommended | — |

**Deployment sequence:**

1. **Download** `Albedo-Setup.exe` from the link above
2. **Run** the installer — accept the UAC prompt
3. The **Setup Wizard** launches automatically and executes:
   - System dependency verification (Python 3.12 + Ollama)
   - Virtual environment creation and full pip dependency installation
   - Piper voice model download (Kristin + Ryan from HuggingFace)
   - OpenWakeWord base model pre-cache
   - `.env` configuration write with persona, voice, and wake word paths
   - Ollama model pull (`llama3.2:3b`) with live progress output
   - Desktop shortcut creation
4. **Select your initial persona** (Cortana or Jarvis) in the wizard
5. **Double-click** the Albedo shortcut — Mission Control is online

**Post-deployment hardware configuration:**

Open Mission Control → click **HARDWARE** to assign your microphone input and speaker/HDMI output device. Changes apply on the next MIC press with no restart required.

---

### Developer Deployment *(Build from Source)*

```powershell
cd "$env:USERPROFILE\Desktop"
git clone https://github.com/Dracon420/Albedo-Local-AI.git
cd Albedo-Local-AI
Set-ExecutionPolicy Bypass -Scope Process
.\Launch-Albedo.ps1
```

The launcher detects a missing `.venv`, redirects to the Setup Wizard automatically, and returns to launch Mission Control once installation completes.

---

## MISSION CONTROL — OPERATOR REFERENCE

| Action | Input |
|---|---|
| Text query | Type in the input field → **SEND** or `Enter` |
| Force live web search | Prefix query with `web:` |
| Voice command | **MIC** → speak → go silent or press **STOP** |
| Visual environment scan | **SCAN** → moondream analyses live webcam frame |
| Switch persona / wake word | **SETTINGS** → Persona dropdown → **SAVE** |
| Assign audio hardware | **HARDWARE** → select input/output device → **SAVE** |
| RAG directory configuration | **SETTINGS** → update paths → **RE-INDEX NOW** |
| Developer console | **LOGS** → live stdout/stderr buffer with CLEAR |
| Re-index knowledge base | SETTINGS → **RE-INDEX NOW** |

---

## LIFECYCLE MANAGEMENT

Three Start Menu shortcuts manage the full Albedo lifecycle:

| Shortcut | Action |
|---|---|
| **Launch Albedo** | Starts Ollama silently, then opens Mission Control via pythonw |
| **Update Albedo** | `git pull` + pip upgrade + voice model sync (non-interactive) |
| **Uninstall Albedo** | Removes `.venv`, shortcuts, optional ChromaDB wipe |

Python, Ollama, and Piper are **not** touched by the uninstaller. Remove those via **Settings → Apps** if required.

---

## HARDWARE TIERS

| Parameter | Standard — RTX 2060 · 6 GB VRAM | High-Spec — RTX 3080+ · 8 GB+ VRAM |
|---|---|---|
| `OLLAMA_MODEL` | `llama3.2:3b` | `llama3.1:8b` |
| `WHISPER_MODEL_SIZE` | `small` | `medium` |
| `WHISPER_COMPUTE_TYPE` | `int8_float16` | `float16` |
| `RAG_TOP_K` | `5` | `10` |
| `num_ctx` | `2048` | `4096` |

Edit `.env` and restart to switch tiers. No reinstall required.

---

## FULL STACK REFERENCE

| Layer | Technology |
|---|---|
| LLM runtime | [Ollama](https://ollama.com) · `llama3.2:3b` |
| Vision model | [Moondream](https://github.com/vikhyat/moondream) via Ollama |
| Vector store | [ChromaDB](https://www.trychroma.com) · CPU embeddings (`all-MiniLM-L6-v2`) |
| Speech-to-text | [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) · CUDA |
| Wake word | [OpenWakeWord](https://github.com/dscripka/openWakeWord) · custom Cortana model |
| Text-to-speech | [Piper](https://github.com/rhasspy/piper) · CPU · kristin-medium / ryan-medium |
| Webcam capture | [OpenCV](https://opencv.org) · DirectShow |
| Desktop GUI | [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) · dark mode |
| Desktop control | [Open Interpreter](https://github.com/OpenInterpreter/open-interpreter) |
| Web search | [ddgs](https://github.com/deedy5/ddgs) — DuckDuckGo, zero API key |
| Web scraping | Playwright · Trafilatura · BeautifulSoup4 |
| Mobile bridge | FastAPI · Uvicorn · Tailscale |
| Installer | [Inno Setup 6](https://jrsoftware.org/isinfo.php) |

---

<div align="center">

*Albedo is a local system. It does not call home.*
*No telemetry. No cloud. No compromise.*

**[ MISSION CONTROL ONLINE ]**

</div>
