# ALBEDO: Spartan-Class Local Assistant — Field Manual

> **Wake Word:** `Cortana` · **Architecture:** Hybrid RAG · **Ecosystem:** Exotic OS · Chaotic 3D Solutions

Albedo is a fully local AI assistant. No cloud. No API keys. No subscription. It fuses a persistent local knowledge base (ChromaDB) with live web search, runs on your GPU via Ollama, and takes direct command of your Windows desktop through Open Interpreter. Say *Cortana* — it answers.

This document is the complete operational field manual. Read each phase before executing it.

---

## Phase 0 — Acquiring the Core

Download the Albedo repository to your machine before running anything else.

**Step 1.** Open **Windows PowerShell** (no admin required for this step).

**Step 2.** Navigate to where you want the project to live — the Desktop is recommended:

```powershell
cd "$env:USERPROFILE\Desktop"
```

**Step 3.** Clone the repository and enter the project directory:

```powershell
git clone https://github.com/Dracon420/Albedo-Local-AI.git
cd Albedo-Local-AI
```

> If `git` is not recognised, install it from [git-scm.com/download/win](https://git-scm.com/download/win) and reopen the terminal.

You now have the full project at `Desktop\Albedo-Local-AI`. All subsequent commands are run from inside this folder.

---

## Phase 1 — Pre-Flight: Authorization

The installer is a PowerShell script. Windows blocks unsigned scripts by default. You must unlock execution rights for the current terminal session before anything else.

### 1.1 Open an elevated terminal

Right-click the **Start menu** and select **Terminal (Admin)** or **Windows PowerShell (Admin)**. Standard (non-admin) terminals will fail silently on certain installer steps.

### 1.2 Set execution policy

Paste this command and press **Enter**:

```powershell
Set-ExecutionPolicy Bypass -Scope Process
```

Windows will display an **Execution Policy Change** warning and ask:

```
Do you want to change the execution policy?
[Y] Yes  [A] Yes to All  [N] No  [L] No to All  [S] Suspend  [?] Help (default is "N"):
```

Type **`y`** and press **Enter**. The terminal is now authorized for this session only.

> `-Scope Process` limits the bypass to the current window. It expires the moment you close the terminal — your system policy is never permanently changed.

### 1.3 Navigate to the project directory

```powershell
cd "C:\Users\YourName\Desktop\Local Cortana AI"
```

Replace the path with wherever you cloned or placed the repository.

---

## Phase 2 — Deployment: Running the Installer

Execute the installer from the project directory:

```powershell
.\install.ps1
```

The script is **fully autonomous**. It will auto-detect your Python version, install Python 3.12 silently if needed, install Ollama, upgrade all build tools, and install every dependency. You only need to answer a few prompts.

### 2.1 Installer prompt guide

Work through each prompt using the reference below.

---

**HARDWARE TIER SELECTION**

```
[1] STANDARD  -- RTX 2060 6 GB / 16 GB RAM
[2] HIGH-SPEC -- RTX 3080+ / 8 GB+ VRAM
```

| Your Hardware | Select |
|---|---|
| RTX 2060 · 16 GB RAM (baseline build) | **1** |
| RTX 3080 / 3090 / 4080 / 4090 · 8 GB+ VRAM | **2** |

Standard tier uses `llama3.2:3b` + Whisper small (`int8_float16`) — tuned to stay within the RTX 2060's 6 GB VRAM ceiling.

---

**LOCAL KNOWLEDGE BASE DIRECTORIES**

```
Chaotic 3D path (STLs, gcode, slicer configs):
Exotic OS path  (Python code, logs, configs):
```

**Leave both blank and press Enter to skip.** You can point Albedo at your directories later with a single command:

```powershell
python main.py --index
```

If you want to configure them now, enter the full path to each folder (e.g. `D:\Chaotic 3D`). Non-existent paths are skipped automatically — the installer will not crash.

---

**PIPER TTS PATHS**

```
piper.exe path [C:\piper\piper.exe]:
Voice .onnx path [C:\piper\voices\en_US-ryan-high.onnx]:
```

**Press Enter to accept the defaults.** Albedo will fall back to console text output if Piper is not installed. You can install Piper and update `.env` at any time without re-running the installer.

Download Piper: [github.com/rhasspy/piper/releases](https://github.com/rhasspy/piper/releases)

---

**WAKE WORD MODEL**

```
Wake word model (label or .onnx path) [hey_jarvis]:
```

**Press Enter to accept `hey_jarvis` as the temporary wake word.** The custom `Cortana` wake word requires training a personal acoustic model — see **Phase 6** for the training guide. The system is fully functional with `hey_jarvis` in the meantime.

---

**PULL OLLAMA MODEL**

```
Pull Ollama model now? (llama3.2:3b -- may take several minutes) [Y/n]:
```

Type **`y`** or press Enter. See **Phase 3 — The Patience Protocol** before proceeding.

---

**RUN INITIAL CHROMADB INDEXING**

```
Run initial ChromaDB indexing now? [Y/n]:
```

If you left the directory paths blank above, type **`n`**. If you entered paths, type **`y`**.

---

### 2.2 What the installer does automatically

The following steps require no input and run in sequence:

1. Detects Python version — installs Python 3.12 via winget silently if system default is 3.13+ (no ML wheels available for newer versions)
2. Detects Ollama — installs via winget silently if missing
3. Creates `.venv` using the verified Python 3.12 binary
4. Upgrades `pip`, `wheel`, and `setuptools` before touching any packages
5. Installs all dependencies from `requirements.txt` using `--prefer-binary` to avoid source compilation
6. Installs Playwright Chromium for Open Interpreter web scraping
7. Pre-downloads OpenWakeWord base acoustic models
8. Writes `.env` with all your selections
9. Creates the **Albedo desktop shortcut** pointing to `Launch-Albedo.ps1`

---

## Phase 3 — The Patience Protocol

Two steps in the installer look frozen and are not. **Do not close the terminal.**

### 3.1 Ollama model download (5–15 minutes)

When the installer pulls the Ollama model, the output will look like this:

```
pulling manifest
pulling 00e1317cbf74... ████░░░░░░░░░░░░░░░░  0% ▕ 0 B/2.0 GB
```

The progress bar may sit at **0%** for several minutes before the download speed stabilises. This is normal — Ollama is negotiating the download from the registry. It will also appear to **hang near 99%** while it finalises the manifest and writes the model to disk.

**Do not close the terminal.** The download is active even when the counter is not moving.

### 3.2 Python dependency installation (3–10 minutes)

Installing packages like `torch`, `faster-whisper`, and `sentence-transformers` downloads hundreds of megabytes of prebuilt wheels. The terminal output will scroll rapidly, then appear to pause. This is normal — pip is decompressing and linking large packages.

---

## Phase 4 — Handling Red Text

During dependency installation you will see red warning output that looks like this:

```
ERROR: pip's dependency resolver does not currently take into account all the
packages that are installed. This behaviour is the source of the following
dependency conflicts.
torch 2.x.x requires setuptools, which is not installed.
```

**This is a benign resolver warning, not a failure.** pip prints it in red because the conflict message is routed to stderr, but the packages install correctly. The installer has already upgraded `setuptools` before this step runs — the warning is a known pip reporting artefact when multiple large ML packages interact.

If the installer prints `[OK] All packages installed successfully` immediately after the red block, the installation succeeded. If it prints `[X]` and asks whether to continue, review the specific package that failed — the torch/setuptools message alone is not a failure.

---

## Phase 5 — High-Spec Calibration

> **Applies to:** RTX 3080 / 3090 / 4080 / 4090 — any GPU with 8 GB+ VRAM

If you selected Tier 1 during install and later upgrade your hardware, update `.env` without re-running the installer:

### 5.1 Pull the upgraded model

```powershell
ollama pull llama3.1:8b
```

### 5.2 Edit `.env`

```env
# Standard (RTX 2060 / 6 GB VRAM)
OLLAMA_MODEL=llama3.2:3b
WHISPER_MODEL_SIZE=small
WHISPER_COMPUTE_TYPE=int8_float16
RAG_TOP_K=5

# High-Spec (RTX 3080+ / 8 GB+ VRAM) -- replace all four lines above with:
OLLAMA_MODEL=llama3.1:8b
WHISPER_MODEL_SIZE=medium
WHISPER_COMPUTE_TYPE=float16
RAG_TOP_K=10
```

Save `.env`. No reinstall needed — all settings are read at runtime.

---

## Phase 6 — RAG Initialization

Albedo's local knowledge base is built from your own files. Two collections are indexed independently.

### 6.1 Configure your directories

Open `.env` and set both paths:

```env
# 3D printing files: gcode, slicer configs, print profiles, material notes
CHAOTIC_3D_PATH=D:\Chaotic 3D

# Exotic OS directory: Python code, reptile logs, system telemetry
EXOTIC_OS_PATH=D:\Exotic OS
```

**What Albedo indexes:**

| Collection | File Types |
|---|---|
| Chaotic 3D | `.gcode` `.cfg` `.ini` `.json` `.txt` `.md` `.xml` |
| Exotic OS | `.py` `.sh` `.log` `.txt` `.md` `.json` `.yaml` `.toml` |

For herpetology — store feeding records, enclosure temperature and humidity logs, vet notes, and husbandry schedules as `.txt` or `.md` files inside `EXOTIC_OS_PATH`. Albedo will embed and retrieve them.

### 6.2 Run the indexer

Activate the virtual environment first, then index:

```powershell
.\.venv\Scripts\Activate.ps1
python main.py --index
```

The indexer skips files already in the database. Run it any time you add or update files.

### 6.3 Verify indexing

```powershell
python main.py
```

Test a retrieval query:

```
You: what are my current print profiles for PLA?
You: what was the last recorded temperature for enclosure 2?
```

If results are empty, confirm the paths in `.env` are correct and re-run `--index`.

### 6.4 Troubleshooting: indexing appears stalled

If `python main.py --index` appears to hang with low CPU and GPU usage, the indexer is not frozen — it is parsing large binary-adjacent or configuration files (dense gcode, large JSON exports, multi-thousand-line logs) that are slow to tokenise and embed.

**What to check:**

- Close any running 3D slicer applications (PrusaSlicer, Bambu Studio, Cura, etc.). Slicers aggressively hold file handles and saturate disk I/O, which directly starves the indexer's read throughput.
- Check Task Manager → Performance → Disk. If disk utilisation is near 100%, another process is competing for I/O. Wait for it to settle, or pause it before indexing.
- Very large individual files (gcode over 50 MB, logs over 10 MB) are skipped by default per the `INDEXER_MAX_FILE_BYTES` limit in `.env`. This is intentional — oversized files degrade retrieval precision without adding useful context.

The indexer will resume printing batch progress as soon as the current file completes. Give it at least 60 seconds before concluding it has stalled.

---

## Phase 7 — Wake Word Training: Custom Cortana Model

The default wake word (`hey_jarvis`) is a placeholder. To activate Albedo by saying **"Cortana"**, you must train a personal acoustic model using openWakeWord's training pipeline. The process requires approximately 30 minutes of setup and generates a portable `.onnx` file.

### 7.1 Requirements

- Python environment with openWakeWord installed (already done by the installer)
- A microphone to record positive training samples
- Approximately 150–500 recordings of you saying "Cortana" in varied conditions (distance, background noise, vocal tone)

### 7.2 Training procedure

Follow the official openWakeWord training guide:

**[github.com/dscripka/openWakeWord — Training New Models](https://github.com/dscripka/openWakeWord#training-new-models)**

The guide walks through:
1. Recording positive samples (`cortana_001.wav` through `cortana_N.wav`)
2. Generating synthetic negative samples using the built-in tools
3. Training the model with `train.py` — outputs `cortana.onnx`

### 7.3 Deploying the trained model

Once you have `cortana.onnx`, update `.env`:

```env
# Replace this:
WAKEWORD_MODEL=hey_jarvis

# With the full path to your trained model:
WAKEWORD_MODEL=C:\path\to\cortana.onnx
```

Restart Albedo. It will now respond only to your voice saying "Cortana".

> **Tip:** Record samples at your normal speaking distance from your desk microphone, not close-range. The model must recognise the wake word under real ambient conditions.

---

## Phase 8 — One-Click Launch

The installer creates a permanent **Albedo** shortcut on your Windows desktop and a `Launch-Albedo.ps1` script in the project root. Both are configured at install time — no manual editing required.

### How it works

Double-click the **Albedo** desktop shortcut. PowerShell runs `Launch-Albedo.ps1`, which:

1. **Checks for a running Ollama process.** If Ollama is already running, nothing changes. If not, it starts `ollama serve` silently in the background with no visible window, then waits up to 8 seconds for it to bind its port.
2. **Launches Albedo in voice mode** using the `.venv` Python binary directly — no manual activation required.
3. **Keeps the console window open** after exit so any error output is readable before the window closes.

### Manual launch (fallback)

If the shortcut is ever deleted or the project is moved, re-create it by re-running `install.ps1`, or launch manually:

```powershell
# From an Admin PowerShell in the project directory:
Set-ExecutionPolicy Bypass -Scope Process
.\.venv\Scripts\Activate.ps1
.\Launch-Albedo.ps1
```

### Terminal commands (direct control)

```powershell
python main.py                  # Text chat (no voice)
python main.py --voice          # Voice mode -- say wake word to activate
python main.py --voice --web    # Voice mode with live web search always on
python main.py --index          # Re-index knowledge base
python main.py --web "query"    # One-shot web-augmented query
```

---

## Optional: Albedo Mobile HUD

A React Native client that extends Albedo to your phone — full voice recording, TTS playback, and text chat over your Tailscale private network. No ports exposed to the internet.

### Prerequisites

- **Expo Go** on your iOS or Android device ([iOS](https://apps.apple.com/app/expo-go/id982107779) · [Android](https://play.google.com/store/apps/details?id=host.exp.exponent))
- **Tailscale** running on both your phone and desktop, joined to the same tailnet ([tailscale.com/download](https://tailscale.com/download))

### Configuration

Find your desktop's Tailscale IP:

```powershell
tailscale ip -4
```

Open `albedo-mobile/src/api/client.ts` line 6 and replace the placeholder:

```typescript
// Before
export const SERVER_BASE = 'http://YOUR_TAILSCALE_IP:8000';

// After (example)
export const SERVER_BASE = 'http://100.64.0.1:8000';
```

### Launch sequence

**Terminal 1 — Start the Bridge:**

```powershell
python server.py
```

Confirm the output shows `Starting Albedo Bridge on 0.0.0.0:8000`.

**Terminal 2 — Start the mobile bundler:**

```powershell
cd albedo-mobile
npx expo start
```

Scan the QR code with Expo Go. The Albedo Spartan HUD will initialise on your device. The header shows a cyan **BRIDGE** chip when the server connection is confirmed.

> **Silent Protocol:** tap the `AUDIO` chip to suppress TTS and receive text-only responses.

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
| Mobile client | React Native · Expo 51 · Tailscale |
| Mobile bridge | FastAPI · Uvicorn |

---

*Albedo is a local system. It does not call home.*
