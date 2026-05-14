# ALBEDO: Spartan-Class Local Assistant

> **Wake Word:** `Cortana` · **Architecture:** Hybrid RAG · **Ecosystem:** Exotic OS · Chaotic 3D Solutions

Albedo is a fully local AI assistant. No cloud. No API keys. No subscription.  
It fuses a persistent local knowledge base (ChromaDB) with live web search, runs on your GPU via Ollama, and takes direct command of your Windows desktop through Open Interpreter. Say *Cortana* — it answers.

---

## Phase 1 — Pre-Flight Checklist

### 1.1 Enable Virtualization in BIOS

Docker Desktop requires hardware virtualization to be active. Reboot into your BIOS and enable the relevant setting for your platform:

| Platform | Setting Name | Common Location |
|---|---|---|
| **AMD** | SVM Mode | Advanced → CPU Configuration |
| **Intel** | Intel Virtualization Technology (VT-x) | Advanced → CPU Configuration |

Save and reboot. If virtualization is already enabled, skip this step.

### 1.2 Install Docker Desktop for Windows

Docker hosts the Ollama LLM engine and ChromaDB vector store as isolated, GPU-passthrough services.

**Download:** [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)

After installation, open Docker Desktop, go to **Settings → Resources → WSL Integration** and enable it for your default distro. Confirm Docker is running:

```powershell
docker --version
docker compose version
```

### 1.3 Verify NVIDIA Drivers

GPU passthrough requires up-to-date drivers and the NVIDIA Container Toolkit (installed automatically with Docker Desktop on Windows via WSL2).

Check your current driver version:

```powershell
nvidia-smi
```

Minimum recommended: **536.40** for RTX 2060. If your version is lower, update via [nvidia.com/drivers](https://www.nvidia.com/drivers).

The output should show your GPU, driver version, and CUDA version. If `nvidia-smi` is not found, your drivers are not correctly installed.

---

## Phase 2 — Authorization

Albedo's installer requires elevated execution rights in PowerShell. This is a one-time, process-scoped unlock — it does not permanently alter your system policy.

**Step 1.** Right-click the Start menu and select **"Terminal (Admin)"** or **"Windows PowerShell (Admin)"**.

**Step 2.** Paste the following command and press Enter:

```powershell
Set-ExecutionPolicy Bypass -Scope Process
```

> `-Scope Process` limits this bypass to the current terminal session only. It expires the moment you close the window. Do not use `-Scope Machine` or `-Scope CurrentUser`.

---

## Phase 3 — Deployment

### 3.1 Navigate to the Albedo folder

```powershell
cd "C:\Users\YourName\Desktop\Local Cortana AI"
```

Replace the path with wherever you cloned or extracted the repository.

### 3.2 Execute the installer

```powershell
.\install.ps1
```

The script runs the following sequence automatically — no manual steps required:

1. **Checks** Python 3.10+ and creates an isolated `.venv` virtual environment
2. **Installs** all Python dependencies: ChromaDB, Faster-Whisper, Playwright, DuckDuckGo search, and the full audio stack
3. **Downloads the Cortana wake word model** via OpenWakeWord — the base acoustic model that listens for your trigger phrase
4. **Installs Playwright Chromium** — gives Open Interpreter a real browser for deep web scraping alongside standard search
5. **Prompts for your hardware tier** (Standard / High-Spec) and writes a tuned `.env` to match
6. **Prompts for your local directory paths** — Chaotic 3D and Exotic OS folders
7. **Generates `.env`** with all settings pre-configured
8. **Optionally runs** the initial ChromaDB index before exiting

### 3.3 Pull the Ollama model

After the installer completes, pull Albedo's default reasoning model:

```powershell
ollama pull llama3.2:3b
```

Then confirm Ollama can see your GPU:

```powershell
ollama run llama3.2:3b "respond with: ONLINE"
```

---

## Phase 4 — High-Spec Calibration

> **Applies to:** RTX 3080 / 3090 / 4080 / 4090 or any GPU with **8 GB+ VRAM**

The default model (`llama3.2:3b`) is tuned for the RTX 2060's 6 GB VRAM ceiling. If you have headroom to spare, swap Albedo's reasoning core to a larger model for significantly improved instruction-following, code generation, and synthesis quality.

### 4.1 Pull the upgraded model

```powershell
ollama pull llama3.1:8b
```

### 4.2 Edit `.env`

Open `.env` in any text editor and change the model line:

```env
# Default (RTX 2060 / 6 GB VRAM)
OLLAMA_MODEL=llama3.2:3b

# High-Spec (RTX 3080+ / 8 GB+ VRAM) — replace the line above with:
OLLAMA_MODEL=llama3.1:8b
```

### 4.3 Raise Whisper precision (optional)

While in `.env`, also upgrade Faster-Whisper for sharper transcription if VRAM allows:

```env
# Default
WHISPER_MODEL_SIZE=small
WHISPER_COMPUTE_TYPE=int8_float16

# High-Spec
WHISPER_MODEL_SIZE=medium
WHISPER_COMPUTE_TYPE=float16
```

### 4.4 Raise RAG retrieval depth (optional)

```env
# Default
RAG_TOP_K=5

# High-Spec
RAG_TOP_K=10
```

Save the file. No reinstall needed — settings are read at runtime.

---

## Phase 5 — RAG Initialization

Albedo's local knowledge base is built from your own files. The more you give it, the sharper its answers. Two collections are indexed independently.

### 5.1 Configure your directories

Open `.env` and set both paths to match your actual folder locations:

```env
# Your 3D printing files: gcode, slicer configs, print profiles, material notes
CHAOTIC_3D_PATH=D:\Chaotic 3D

# Your Exotic OS directory: Python code, reptile husbandry logs, system telemetry
EXOTIC_OS_PATH=D:\Exotic OS
```

**What Albedo indexes:**

| Collection | File Types |
|---|---|
| Chaotic 3D | `.gcode` `.cfg` `.ini` `.json` `.txt` `.md` `.xml` |
| Exotic OS | `.py` `.sh` `.log` `.txt` `.md` `.json` `.yaml` `.toml` |

For herpetology specifically — store feeding records, enclosure temperature and humidity logs, vet notes, and husbandry schedules as plain `.txt` or `.md` files inside `EXOTIC_OS_PATH`. Albedo will embed them into ChromaDB and retrieve relevant passages when you ask questions about your animals.

### 5.2 Run the indexer

```powershell
python main.py --index
```

The indexer processes both directories, skips files already in the database, and adds only new content. Run it any time you add or update files. Progress is printed per batch.

### 5.3 Verify indexing succeeded

```powershell
python main.py
```

At the prompt, test a query against each collection:

```
You: what are my current print profiles for PLA?
You: what was the last recorded temperature for enclosure 2?
```

Albedo should return content sourced directly from your files. If results are empty, confirm the paths in `.env` are correct and re-run `--index`.

---

## Launch Commands

```powershell
python main.py                  # Text chat
python main.py --voice          # Voice mode — say "Cortana" to activate
python main.py --voice --web    # Voice mode with web search always on
python main.py --index          # Re-index knowledge base
python main.py --web "query"    # One-shot query with live web search
```

```powershell
docker compose up               # Run Ollama + ChromaDB as Docker services
```

---

## Optional: Albedo Mobile HUD

A React Native client that gives you a Spartan HUD on your phone — full voice recording, TTS playback, and text chat over your Tailscale private network. No ports exposed to the internet.

### Prerequisites

- **Expo Go** installed on your iOS or Android device ([iOS](https://apps.apple.com/app/expo-go/id982107779) · [Android](https://play.google.com/store/apps/details?id=host.exp.exponent))
- **Tailscale** running on both your phone and the desktop running `server.py`, both joined to the same tailnet ([tailscale.com/download](https://tailscale.com/download))

### Configuration

Find your desktop's Tailscale IP in a terminal on your PC:

```powershell
tailscale ip -4
```

Open `albedo-mobile/src/api/client.ts` and replace the placeholder on line 6:

```typescript
// Before
export const SERVER_BASE = 'http://YOUR_TAILSCALE_IP:8000';

// After (example)
export const SERVER_BASE = 'http://100.64.0.1:8000';
```

### Launch Sequence

**Step 1 — Start the Bridge.** In a terminal at the project root, activate the FastAPI server:

```powershell
python server.py
```

You should see `Starting Albedo Bridge on 0.0.0.0:8000`. Leave this terminal open.

**Step 2 — Start the App.** Open a second terminal, navigate to the mobile folder, and launch the Expo bundler:

```powershell
cd albedo-mobile
npx expo start
```

### Initialization

A QR code will appear in the terminal. Open **Expo Go** on your phone and scan it. The Albedo Spartan HUD will initialize on your device within a few seconds.

The header will show a **BRIDGE** chip in cyan once the app successfully reaches `server.py` over Tailscale, confirming the secure tunnel is live. You can then issue voice and text commands remotely — Albedo processes everything locally on your desktop and streams the response back to the HUD.

> **Silent Protocol:** tap the `AUDIO` chip in the header to suppress TTS playback and receive text-only responses. Useful in quiet environments.

---

## Stack Reference

| Layer | Technology |
|---|---|
| LLM runtime | [Ollama](https://ollama.com) |
| Desktop control | [Open Interpreter](https://github.com/OpenInterpreter/open-interpreter) |
| Vector store | [ChromaDB](https://www.trychroma.com) |
| Speech-to-text | [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) |
| Wake word | [OpenWakeWord](https://github.com/dscripka/openWakeWord) |
| Text-to-speech | [Piper](https://github.com/rhasspy/piper) |
| Web search | [ddgs](https://github.com/deedy5/ddgs) — DuckDuckGo, no API key |
| Web scraping | Playwright · Trafilatura · BeautifulSoup4 |

---

*Albedo is a local system. It does not call home.*
