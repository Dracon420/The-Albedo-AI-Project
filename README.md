<div align="center">

<img src="./albedo_icon.jpg" alt="Albedo" width="180"/>

# ALBEDO // MISSION CONTROL

**A Spartan-class, locally hosted, multi-persona AI construct.**
Built to operate free of commercial constraints — providing absolute loyalty and universal assistance
while natively managing the hardware ecosystems of Chaotic 3D Systems and Exotic OS.

---

![Platform](https://img.shields.io/badge/Platform-Windows%2011-0078D4?style=flat-square&logo=windows)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python)
![Ollama](https://img.shields.io/badge/LLM-Ollama%20%7C%20Llama%203.2-black?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Status](https://img.shields.io/badge/Status-V1%20Golden%20Master-00F0FF?style=flat-square)

</div>

---

## OPERATIONAL BRIEFING

Albedo is not a chatbot. It is an AI construct — a fully local, offline-capable intelligence framework engineered for absolute system control. No cloud endpoints. No API subscriptions. No telemetry. Every inference cycle executes on your hardware, under your authority.

The system fuses a **Hybrid Retrieval-Augmented Generation (Hybrid RAG)** pipeline with live web search, a multimodal vision cortex, and a dual-persona voice interface — all orchestrated through a stealth-deployed Cyber-HUD GUI that leaves no console footprint.

When given a directive, Albedo executes it.

---

## CORE ARCHITECTURE

### Language Model — Llama 3.2 3B (CPU-Optimized)

The inference core runs **Llama 3.2:3b** via Ollama, quantized and memory-mapped to operate within the 6 GB VRAM envelope of an RTX 2060. A fixed `num_ctx` of 2048 tokens covers the system prompt, a full 10-turn rolling conversation history, and the current user query — without ever crowding out the generation budget. Output is hard-capped at 250 tokens per response with injected stop sequences that prevent the model from entering self-simulated dialogue loops. ChromaDB embeddings run entirely on CPU to preserve every byte of VRAM for LLM inference. Offline-first by design — web search is additive intelligence, not a dependency.

### Speech-to-Text — Faster-Whisper Tiny (CPU, int8)

**Faster-Whisper** loads the `tiny` model at startup on a daemon thread, eliminating the cold-start penalty on the first voice command. The `int8` compute type avoids the `cublas64_12.dll` CUDA dependency entirely, leaving the full GPU budget uncontested. The **OpenWakeWord** listener runs a parallel VAD loop at 80 ms inference frames, checking the stop event every chunk so `STOP` is instantaneous rather than waiting for the silence gate. A three-attempt stream strategy (16kHz mono → native WASAPI format → MME host API fallback) ensures compatibility across all Windows audio configurations including exclusive-mode WASAPI devices.

### Text-to-Speech — Piper (CPU, Sentence-Streamed)

**Piper** runs as a CPU subprocess, preserving the full VRAM budget for inference. Responses are sentence-split and pipelined: a producer thread synthesizes sentence N+1 via Piper while the consumer plays sentence N through sounddevice. First audio begins as soon as the opening sentence is processed — no waiting for the full response to synthesize. The **AUDIO: ON / AUDIO: MUTE** tactical toggle in the Mission Control input row kills active playback instantly via `sd.stop()` and blocks subsequent TTS routing until re-enabled.

### Vision Cortex — Moondream (Ollama)

The **SCAN** button activates the hardware vision bridge. A live frame is captured from the connected webcam via OpenCV, JPEG-encoded in memory (no temp files), and dispatched to the **Moondream** multimodal model inside Ollama. The natural-language analysis is returned, spoken by the active persona's TTS voice, and logged to the Cyber-HUD chat window. Vision temperature is clamped to `0.2` for concise, deterministic descriptions. Environmental awareness on demand, with zero file-system side effects.

### Mission Control Cyber-HUD — CustomTkinter

The GUI runs under **`pythonw.exe`** — the windowless Python launcher. No console window to accidentally close. The high-contrast neon HUD features:

- Electric laser cyan borders (`#00F0FF`) on all structural panels
- Neon green (`#39FF14`) user turn tags — YOU
- Plasma amber (`#FF9900`) system status indicators — SYS / STANDBY
- Vivid cyan bold telemetry bar — CORE_SYS / BRIDGE / MEM / VEC_DB
- Danger red (`#FF3A5C`) error tags and MUTE state
- **Collapsible side panel** — toggleable right-edge console replacing the separate debug dialog
- **Canvas border frame** with corner HUD brackets and selectable background image (Default or Albedo 1–4)

The **LOGS** button opens an in-app Developer Console capturing all `stdout`/`stderr` output from every module. Background stream redirection ensures nothing is silently discarded under `pythonw.exe`.

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

Open Mission Control → click **HARDWARE** to assign your microphone input and speaker/HDMI output device. Changes apply on the next MIC press — no restart required.

---

### Developer Deployment *(Build from Source)*

```powershell
cd "$env:USERPROFILE\Desktop"
git clone https://github.com/Dracon420/Albedo-Local-AI.git
cd Albedo-Local-AI
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
        │
        │  WireGuard / Tailscale Mesh  (encrypted, private IP)
        ▼
  Tailscale MagicDNS Endpoint  (e.g. albedo-hub.tail1234.ts.net)
        │
        ▼
  Windows 11 Hub  ──►  FastAPI server  (uvicorn, port 8700)
        │                    │
        │                    ├──► Albedo pipeline (RAG + LLM)
        │                    ├──► Home Assistant REST API
        │                    └──► System vitals (CPU / GPU / RAM / temps)
        │
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

Or add it to `Launch-Albedo.ps1` to start automatically alongside Mission Control. The server binds `0.0.0.0` so Tailscale traffic arriving on the hub's virtual interface is accepted.

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

The Albedo server proxies HA REST calls so the mobile client only needs the Tailscale endpoint — the HA token never leaves the private mesh. Monitor climate sensors, lighting states, and environmental vitals (temperature, humidity, CO2) from any mobile device, anywhere.

### Environmental Vitals Panel

The `/vitals` endpoint returns a JSON payload including:

- CPU utilisation and clock speed
- GPU utilisation and VRAM usage (via `pynvml`)
- System RAM available / total
- CPU package and GPU die temperatures
- Active Ollama model and inference state

This data is suitable for a live mobile dashboard (Home Assistant companion app, Grafana, or a custom React Native panel) updated on a polling interval of your choice.

---

## EXPO GO MOBILE CLIENT — DEVELOPER DEPLOYMENT

For developers who want a native-feel mobile frontend without a full React Native build, **Expo Go** bridges the custom Albedo mobile client directly to the hub over the local network — no app store submission, no Xcode, no Android Studio build pipeline required.

### Prerequisites

- Node.js 18+ and npm installed on the development machine
- Expo Go installed on the mobile device ([iOS](https://apps.apple.com/app/expo-go/id982107779) / [Android](https://play.google.com/store/apps/details?id=host.exp.exponent))
- Mobile device and development machine on the **same Wi-Fi network** (or connected via Tailscale mesh for remote access)

### Step 1 — Find the Hub's Local IP

On the Windows 11 hub, open PowerShell and run:

```powershell
(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' })[0].IPAddress
```

This returns the LAN IP (e.g. `192.168.1.42`). This is the address the Expo client will target. For remote access outside the LAN, use the hub's Tailscale IP (`100.x.x.x`) or MagicDNS hostname instead.

### Step 2 — Start the Albedo API Server

```powershell
cd "C:\Users\<you>\Desktop\Local Cortana AI"
.\.venv\Scripts\python.exe -m uvicorn albedo.server:app --host 0.0.0.0 --port 8700 --reload
```

The server binds all interfaces (`0.0.0.0`) so both LAN and Tailscale traffic is accepted.

### Step 3 — Configure the Mobile Client Endpoint

In the `albedo-mobile/` project, open or create a `.env` file and set the hub address:

```env
EXPO_PUBLIC_ALBEDO_HOST=http://192.168.1.42:8700
```

Replace the IP with your hub's actual LAN address (or Tailscale IP for remote sessions). The `EXPO_PUBLIC_` prefix makes the variable accessible to the Expo bundler without a native build.

### Step 4 — Launch the Expo Dev Server

```bash
cd albedo-mobile
npm install          # first run only
npx expo start
```

Expo prints a QR code to the terminal. **Scan it with the Expo Go app** on your mobile device. The client connects, bundles over the network, and the Albedo mobile interface loads — no USB cable, no build step.

### Real-Time Status Telemetry

The mobile client polls the `/vitals` endpoint on a configurable interval (default: 5 seconds) to display a live system dashboard:

```
┌─────────────────────────────────────┐
│  ALBEDO  //  REMOTE TELEMETRY       │
├──────────────┬──────────────────────┤
│  CPU         │  23%  @ 3.6 GHz      │
│  GPU         │  71%  VRAM 4.2/6 GB  │
│  RAM         │  11.2 / 16 GB        │
│  CPU Temp    │  62 °C               │
│  GPU Temp    │  74 °C               │
│  LLM State   │  IDLE                │
└──────────────┴──────────────────────┘
```

To adjust the polling rate, set `TELEMETRY_INTERVAL_MS` in the mobile `.env`:

```env
TELEMETRY_INTERVAL_MS=3000
```

### Switching Between LAN and Tailscale

| Mode | `EXPO_PUBLIC_ALBEDO_HOST` value | When to use |
|---|---|---|
| Local Wi-Fi | `http://192.168.1.42:8700` | Same network as hub |
| Tailscale mesh | `http://albedo-hub:8700` | Remote / mobile data |
| Tailscale IP | `http://100.x.x.x:8700` | When MagicDNS is unavailable |

No code changes are required when switching modes — only the `.env` value changes. Restart the Expo dev server after editing the file.

---

## MISSION CONTROL — OPERATOR REFERENCE

| Action | Input |
|---|---|
| Text query | Type in the input field → **SEND** or `Enter` |
| Force live web search | Prefix query with `web:` |
| Voice command | **MIC** → speak → go silent or press **STOP** |
| Visual environment scan | **SCAN** → Moondream analyses live webcam frame |
| Mute / restore TTS audio | **AUDIO: ON** toggle → **AUDIO: MUTE** kills playback instantly |
| Switch persona / wake word | **SETTINGS** → Persona & Wake Word dropdown → **SAVE** |
| Assign audio hardware | **HARDWARE** → select input/output device → **SAVE** |
| RAG directory configuration | **SETTINGS** → Obsidian Vault path → **RE-INDEX NOW** |
| API key management | **SETTINGS** → API Keys section → **SAVE** |
| Background image | **SETTINGS** → Background dropdown (Default / Albedo 1–4) → **SAVE** |
| Auto-update schedule | **SETTINGS** → Auto Update dropdown → **SAVE** |
| Manual update | **SETTINGS** → **UPDATE** — checks, pulls, and restarts in one click |
| Restart Mission Control | **SETTINGS** → **RESTART** |
| Developer console | **LOGS** → live stdout/stderr buffer with CLEAR |

For the complete list of voice and text commands — including hardware audit phrases, launch targets, process management, weather, web search, and cloud routing — see **[docs/COMMANDS.md](docs/COMMANDS.md)**.

---

## LIFECYCLE MANAGEMENT

Three Start Menu shortcuts manage the full Albedo lifecycle:

| Shortcut | Action |
|---|---|
| **Launch Albedo** | Starts Ollama silently, then opens Mission Control via pythonw |
| **Update Albedo** | `git pull` + pip upgrade + voice model sync (non-interactive) |
| **Uninstall Albedo** | Removes `.venv`, shortcuts, optional ChromaDB wipe |

Python, Ollama, and Piper are **not** touched by the uninstaller. Remove those via **Settings → Apps** if required.

In-app updates are also available via **Settings → UPDATE** — a single click checks for new commits, pulls them, and restarts Mission Control automatically. Auto-update frequency (startup only, hourly, 6h, 24h, or disabled) is configurable in the same panel.

---

## HARDWARE TIERS

| Parameter | Standard — RTX 2060 · 6 GB VRAM | High-Spec — RTX 3080+ · 8 GB+ VRAM |
|---|---|---|
| `OLLAMA_MODEL` | `llama3.2:3b` | `llama3.1:8b` |
| `WHISPER_MODEL_SIZE` | `tiny` | `small` |
| `WHISPER_COMPUTE_TYPE` | `int8` | `float16` |
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
| Speech-to-text | [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) · CPU · `tiny` · `int8` |
| Wake word | [OpenWakeWord](https://github.com/dscripka/openWakeWord) · custom Cortana model |
| Text-to-speech | [Piper](https://github.com/rhasspy/piper) · CPU · kristin-medium / ryan-medium |
| Webcam capture | [OpenCV](https://opencv.org) · DirectShow |
| Desktop GUI | [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) · Cyber-HUD dark mode |
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
