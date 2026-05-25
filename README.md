<div align="center">

<img src="https://github.com/Dracon420/The-Albedo-AI-Project/blob/master/albedo_logo.png?raw=true" alt="Albedo" width="180"/>

# ALBEDO // MISSION CONTROL

**A Spartan-class, locally hosted, multi-persona AI construct.**
Built to operate free of commercial constraints — providing absolute loyalty and universal assistance
while natively managing the hardware ecosystems of Chaotic 3D Systems and Exotic OS.

---

![Platform](https://img.shields.io/badge/Platform-Windows%2011-0078D4?style=flat-square&logo=windows)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python)
![Ollama](https://img.shields.io/badge/LLM-Ollama%20%7C%20DeepSeek%20R1%20%7C%20Custom%20LoRA-black?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Status](https://img.shields.io/badge/Status-v2.0.0-00F0FF?style=flat-square)

📖 **[Command Reference](docs/COMMANDS.md)** — full voice & text command catalog

</div>

---

## OPERATIONAL BRIEFING

Albedo is not a chatbot. It is an AI construct — a fully local, offline-capable intelligence framework engineered for absolute system control. No cloud endpoints. No API subscriptions. No telemetry. Every inference cycle executes on your hardware, under your authority.

The system fuses a **Hybrid Retrieval-Augmented Generation (Hybrid RAG)** pipeline with live web search, a multimodal vision cortex, and a dual-persona voice interface — all orchestrated through a stealth-deployed **Eel Cyber-HUD** that runs in a frameless Chrome app window with zero console footprint.

When given a directive, Albedo executes it.

---

## CORE ARCHITECTURE

### Language Model — Dual-Persona Fine-Tuned Models (QLoRA on DeepSeek R1)

V2 ships two custom-trained Ollama models, each a QLoRA fine-tune of **DeepSeek-R1-Distill-Qwen-1.5B**, quantized to Q4_K_M GGUF (1.80 GB each) for the RTX 2060's 6 GB VRAM envelope:

| Model | Wake Word | Personality | Training |
|---|---|---|---|
| `albedo-cortana` | *"Hey Cortana"* | Halo Spartan-class AI — precise, loyal, tactical | Round 2 · 147 examples · rank 16 · cosine LR |
| `albedo-jarvis` | *"Hey Jarvis"* | Iron Man AI — formal, British wit, addresses user as "sir" | 83 examples · rank 16 · 5 epochs |

Wake word detection routes to the correct model at runtime via `set_active_persona()` in `albedo/bridge.py`. The persona can also be swapped live from the Settings panel without restarting. A fixed `num_ctx` of 2048 tokens covers the system prompt, 10-turn rolling history, and the current query. ChromaDB embeddings run entirely on CPU to preserve every byte of VRAM for LLM inference. Offline-first by design — web search is additive intelligence, not a dependency.

### Speech-to-Text & Wake Word — Vosk (CPU, offline)

**Vosk** (`vosk-model-small-en-us-0.15`, ~40 MB) handles both wake-word detection and full transcription on the CPU, eliminating the prior dual-engine stack (Faster-Whisper + OpenWakeWord). Zero VRAM cost — the entire LLM budget stays available for inference. The model is pre-warmed on a daemon thread at startup so the first MIC press has no load latency, and the recognizer uses a restricted grammar of just the configured wake words plus `[unk]` to keep idle-listen CPU usage minimal. A three-attempt stream strategy (16 kHz mono → native WASAPI → MME host API fallback) ensures compatibility across all Windows audio configurations including exclusive-mode WASAPI devices.

### Text-to-Speech — Piper (CPU, Sentence-Streamed)

**Piper** runs as a CPU subprocess, preserving the full VRAM budget for inference. Responses are sentence-split and pipelined: a producer thread synthesizes sentence N+1 via Piper while the consumer plays sentence N through sounddevice. First audio begins as soon as the opening sentence is processed — no waiting for the full response to synthesize. The **AUDIO: ON / AUDIO: MUTE** tactical toggle kills active playback instantly via `sd.stop()` and blocks subsequent TTS routing until re-enabled.

### Vision Cortex — Moondream (Ollama)

The **SCAN** button activates the hardware vision bridge. A live frame is captured from the connected webcam via OpenCV, JPEG-encoded in memory (no temp files), and dispatched to the **Moondream** multimodal model inside Ollama. The natural-language analysis is returned, spoken by the active persona's TTS voice, and logged to the chat window. Vision temperature is clamped to `0.2` for concise, deterministic descriptions.

### Mission Control Cyber-HUD — Eel (Chrome App Mode)

The GUI runs as a **frameless Chrome app window** powered by [Eel](https://github.com/python-eel/Eel) — a Python/JS bridge over a local WebSocket. Launched via `pythonw.exe` with no console footprint. The high-contrast neon HUD features:

- Animated neural-link status grid showing live state of every subsystem (Gemini, Groq, Together, Ollama, ChromaDB, STT, TTS, Wake Word, Dream Cycle, Webhook)
- Real-time telemetry gauges — CPU %, RAM %, GPU %, VRAM used/total, disk I/O, network throughput
- Swarm agent indicator LEDs (ALBEDO_CORE / WEB_SCRAPER / EXECUTION_OVERRIDE)
- Off-canvas **Tactical Drawer** — system diagnostics, resource map, settings, background selection, and Dream Cycle controls
- Four selectable background images with localStorage persistence
- Electric laser cyan (`#00F0FF`) structural borders, neon green (`#39FF14`) user turn tags, plasma amber (`#FF9900`) system indicators
- Full keyboard shortcut support — `Escape` closes the drawer, `Enter` submits queries

### Dream Cycle — Autonomous Idle Processing

When Albedo detects **20 minutes of keyboard/mouse inactivity** (configurable via `IDLE_THRESHOLD_MINUTES`), it automatically enters a three-phase **Dream Cycle**:

| Phase | Task |
|-------|------|
| **1 — File Organization** | Scans and reorganizes files per learned rules |
| **2 — System Catalog** | Rebuilds the ChromaDB file index |
| **3 — Memory Consolidation** | Runs the REM cycle: reads interaction traces, distills insights via LLM, appends to Obsidian vault |

The cycle is **interrupt-safe** — any keyboard or mouse event signals an immediate stop between phases. A 2-hour cooldown prevents re-triggering. The Dream Cycle status is visible in the Tactical Drawer's `#dreamStatus` readout, and a **FORCE DREAM NOW** button allows on-demand triggering from the UI. Live state is pushed to the UI in real-time via `eel._albedo_dream_push()`.

### Hybrid RAG Knowledge Architecture

Local knowledge is indexed into ChromaDB from a single configurable source:

| Collection | Domain | Indexed File Types |
|---|---|---|
| `obsidian_vault` | Personal notes, project records, research, reptile husbandry | `.md` `.txt` `.json` `.yaml` `.toml` `.py` `.sh` `.log` |

Configure the vault path via **Settings → OBSIDIAN VAULT** and rebuild the index with **RE-INDEX NOW**. Every query that the autonomous commander routes to `"memory"` searches this collection semantically via ChromaDB's `all-MiniLM-L6-v2` embeddings.

Web search runs in parallel via DuckDuckGo for queries routed to `"direct"`, and is always available on demand with the `web:` prefix. File-count queries (e.g. "how many STL files") are intercepted and resolved directly via `pathlib.rglob()` — the LLM never guesses the working directory.

---

## QUICK START — DEPLOYMENT

### Standard Deployment *(Recommended)*

**No terminal. No configuration. One installer.**

<div align="center">

### [⬇ Download Albedo-Setup-2.0.0.exe](https://github.com/Dracon420/The-Albedo-AI-Project/releases/download/v2.0.0/Albedo-Setup-2.0.0.exe)

</div>

**Pre-flight requirements — the installer verifies all of these automatically:**

| Requirement | Specification | Auto-install |
|---|---|---|
| OS | Windows 10 / 11 (64-bit) | — |
| Python | 3.12 | Guided via winget |
| Ollama | Latest | Yes, via winget |
| GPU VRAM | 4 GB minimum · 6 GB recommended | — |

> **Windows SmartScreen notice:** Windows may show a "Windows protected your PC" warning when running the installer. This is expected for unsigned software. Click **More info** then **Run anyway** to proceed — the installer contains no malware or telemetry.

**Upgrade behavior:** If a previous Albedo installation is detected, the installer upgrades in-place. Your data is **fully preserved**:
- API keys and settings (`.env`)
- Persona settings (`settings.json`)
- Memory database (`albedo_memory_db`)
- File catalog (`chroma_db`)
- Hardware config (`hardware_config.json`)

**Deployment sequence:**

1. **Download** `Albedo-Setup-2.0.0.exe` from the link above
2. **Run** the installer — accept the UAC prompt
3. The **Setup Wizard** launches automatically and executes:
   - System dependency verification (Python 3.12 + Ollama)
   - Virtual environment creation and full pip dependency installation
   - Piper voice model download (Kristin + Ryan from HuggingFace)
   - `.env` configuration write with persona, voice, and wake word paths
   - Ollama model pull (`albedo-cortana` + `albedo-jarvis`) with live progress output
   - Desktop shortcut creation
4. **Select your initial persona** (Cortana or Jarvis) in the wizard
5. **Double-click** the Albedo shortcut — Mission Control is online

---

### Developer Deployment *(Build from Source)*

```powershell
cd "$env:USERPROFILE\Desktop"
git clone https://github.com/Dracon420/The-Albedo-AI-Project.git
cd The-Albedo-AI-Project
Set-ExecutionPolicy Bypass -Scope Process
.\Launch-Albedo.ps1
```

The launcher detects a missing `.venv`, redirects to the Setup Wizard, and returns to Mission Control once installation completes.

---

## MOBILE REMOTE MONITORING — TAILSCALE SECURE TUNNEL

Albedo extends beyond the desktop. The FastAPI mobile bridge, routed through a **Tailscale encrypted private mesh**, allows a mobile device anywhere on the internet to connect back to the local hub — with zero open ports, zero firewall rules, and end-to-end WireGuard encryption.

### Architecture Overview

```
Mobile Device (iOS / Android)
        |
        |  WireGuard / Tailscale Mesh  (encrypted, private IP)
        v
  Tailscale MagicDNS Endpoint  (e.g. albedo-hub.tail1234.ts.net)
        |
        v
  Windows 11 Hub ──► FastAPI server  (uvicorn, port 8700)
        |                    |
        |                    ├──► Albedo pipeline (RAG + LLM)
        |                    ├──► Home Assistant REST API
        |                    └──► System vitals (CPU / GPU / RAM / temps)
        |
        └──►  Ollama  ·  ChromaDB  ·  Piper TTS
```

### Step 1 — Install Tailscale on Both Devices

1. **Hub (Windows 11):** Download and install Tailscale from [tailscale.com/download](https://tailscale.com/download). Sign in. The hub will receive a private Tailscale IP (`100.x.x.x`) and a MagicDNS hostname (e.g. `albedo-hub`).
2. **Mobile device:** Install the Tailscale app (iOS App Store / Google Play). Sign in with the **same account**. The device joins the same private mesh automatically.

No port forwarding. No public IP exposure. Tailscale handles NAT traversal and key exchange entirely.

### Step 2 — Start the Albedo FastAPI Bridge

From the project directory on the hub:

```powershell
.\.venv\Scripts\python.exe -m uvicorn albedo.server:app --host 0.0.0.0 --port 8700
```

Or add it to `Launch-Albedo.ps1` to start automatically alongside Mission Control.

### Step 3 — Connect from Mobile

From any mobile browser or the Albedo mobile companion app, reach the hub via its Tailscale MagicDNS address:

```
http://albedo-hub:8700/
```

Replace `albedo-hub` with your actual MagicDNS hostname (visible in the Tailscale admin panel at [login.tailscale.com/admin/machines](https://login.tailscale.com/admin/machines)).

### Available Mobile Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/query` | POST | Send a text query through the full Albedo RAG pipeline |
| `/tts` | POST | Synthesize a response to WAV audio for playback |
| `/vitals` | GET | Live CPU %, GPU %, RAM %, temperatures |
| `/ha/states` | GET | Home Assistant entity states via REST proxy |
| `/ha/call` | POST | Trigger a Home Assistant service action |

### Home Assistant Integration

Set `HA_BASE_URL` and `HA_TOKEN` in `.env` to connect the bridge to your Home Assistant instance:

```env
HA_BASE_URL="http://homeassistant.local:8123"
HA_TOKEN="your_long_lived_access_token"
```

---

## EXPO GO MOBILE CLIENT — DEVELOPER DEPLOYMENT

For developers who want a native-feel mobile frontend without a full React Native build, **Expo Go** bridges the custom Albedo mobile client directly to the hub over the local network — no app store submission, no Xcode, no Android Studio build pipeline required.

### Prerequisites

- Node.js 18+ and npm installed on the development machine
- Expo Go installed on the mobile device ([iOS](https://apps.apple.com/app/expo-go/id982107779) / [Android](https://play.google.com/store/apps/details?id=host.exp.exponent))
- Mobile device and development machine on the **same Wi-Fi network** (or connected via Tailscale mesh for remote access)

### Step 1 — Find the Hub's Local IP

```powershell
(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' })[0].IPAddress
```

### Step 2 — Start the Albedo API Server

```powershell
cd "C:\Albedo"
.\.venv\Scripts\python.exe -m uvicorn albedo.server:app --host 0.0.0.0 --port 8700 --reload
```

### Step 3 — Configure the Mobile Client Endpoint

In the `albedo-mobile/` project, open or create a `.env` file and set the hub address:

```env
EXPO_PUBLIC_ALBEDO_HOST=http://192.168.1.42:8700
```

### Step 4 — Launch the Expo Dev Server

```bash
cd albedo-mobile
npm install          # first run only
npx expo start
```

Expo prints a QR code to the terminal. **Scan it with the Expo Go app** on your mobile device.

### Switching Between LAN and Tailscale

| Mode | `EXPO_PUBLIC_ALBEDO_HOST` value | When to use |
|---|---|---|
| Local Wi-Fi | `http://192.168.1.42:8700` | Same network as hub |
| Tailscale mesh | `http://albedo-hub:8700` | Remote / mobile data |
| Tailscale IP | `http://100.x.x.x:8700` | When MagicDNS is unavailable |

---

## MISSION CONTROL — OPERATOR REFERENCE

| Action | Input |
|---|---|
| Text query | Type in the input field → **SEND** or `Enter` |
| Force live web search | Prefix query with `web:` |
| Voice command | **MIC** → speak → go silent or press **STOP** |
| Visual environment scan | **SCAN** → Moondream analyses live webcam frame |
| Mute / restore TTS audio | **AUDIO: ON** toggle → **AUDIO: MUTE** kills playback instantly |
| Open Tactical Drawer | Click the **☰** button (top-left) |
| Switch background | Drawer → background thumbnails |
| Switch persona / wake word | Drawer → **Settings** tab → Persona dropdown → **SAVE** |
| Assign audio hardware | Drawer → **Settings** tab → Audio Device dropdowns → **SAVE** |
| RAG directory configuration | Drawer → **Settings** tab → Obsidian Vault path → **RE-INDEX NOW** |
| Force Dream Cycle | Drawer → **Dream** tab → **FORCE DREAM NOW** |
| View system diagnostics | Drawer → **System** tab → hardware profile + resource map |
| Keyboard close drawer | `Escape` |

For the complete list of voice and text commands — including hardware audit phrases, launch targets, process management, weather, web search, and cloud routing — see **[docs/COMMANDS.md](docs/COMMANDS.md)**.

---

## LIFECYCLE MANAGEMENT

The installer creates a **Start Menu** shortcut and an optional **Desktop** shortcut.

| Shortcut / Method | Action |
|---|---|
| **Albedo Mission Control** shortcut | Starts Ollama silently, then opens Mission Control via pythonw |
| Re-run `Albedo-Setup-2.0.0.exe` | Upgrades in-place, preserves all user data |
| Windows **Add or remove programs** → Albedo | Uninstalls — preserves `.env`, `settings.json`, `chroma_db`, `albedo_memory_db` |

Python, Ollama, and Piper are **not** touched by the uninstaller. Remove those via **Settings → Apps** if required.

---

## HARDWARE TIERS

| Parameter | Standard — RTX 2060 · 6 GB VRAM | High-Spec — RTX 3080+ · 8 GB+ VRAM |
|---|---|---|
| `OLLAMA_MODEL` | `albedo-cortana` / `albedo-jarvis` | `albedo-cortana` / `albedo-jarvis` |
| `VOSK_MODEL_PATH` | `vosk-model-small-en-us-0.15` (~40 MB) | `vosk-model-en-us-0.22` (~1.8 GB) |
| `RAG_TOP_K` | `5` | `10` |
| `num_ctx` | `2048` | `4096` |

Edit `.env` and restart to switch tiers. No reinstall required.

---

## FULL STACK REFERENCE

| Layer | Technology |
|---|---|
| LLM runtime | [Ollama](https://ollama.com) · `albedo-cortana` / `albedo-jarvis` (DeepSeek-R1-Distill-Qwen-1.5B · Q4_K_M) |
| Vision model | [Moondream](https://github.com/vikhyat/moondream) via Ollama |
| Vector store | [ChromaDB](https://www.trychroma.com) · CPU embeddings (`all-MiniLM-L6-v2`) |
| Speech-to-text + wake word | [Vosk](https://alphacephei.com/vosk/) · CPU · `vosk-model-small-en-us-0.15` |
| Text-to-speech | [Piper](https://github.com/rhasspy/piper) · CPU · kristin-medium / ryan-medium |
| Webcam capture | [OpenCV](https://opencv.org) · DirectShow |
| Desktop GUI | [Eel](https://github.com/python-eel/Eel) · Chrome app-mode · Cyber-HUD |
| Desktop control | [Open Interpreter](https://github.com/OpenInterpreter/open-interpreter) |
| Web search | [ddgs](https://github.com/deedy5/ddgs) — DuckDuckGo, zero API key |
| Mobile bridge | FastAPI · Uvicorn · Tailscale WireGuard mesh |
| Home Assistant | REST API proxy via Tailscale tunnel |
| Installer | [Inno Setup 6](https://jrsoftware.org/isinfo.php) |

---

<div align="center">

*Albedo is a local system. It does not call home.*
*No telemetry. No cloud. No compromise.*

**[ MISSION CONTROL ONLINE ]**

</div>
