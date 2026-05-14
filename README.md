# ALBEDO: Spartan-Class Local Assistant

> **Wake Word:** `Cortana` · **Architecture:** Hybrid RAG · **Ecosystem:** Exotic OS · Chaotic 3D Solutions

Albedo is a fully local AI assistant. No cloud. No API keys. No subscription. It fuses a persistent local knowledge base (ChromaDB) with live web search, runs on your GPU via Ollama, and takes direct command of your Windows desktop through Open Interpreter. Say *Cortana* — it answers.

---

## Installation

### Path A — Standard Deployment *(Recommended)*

**No terminal required. One download, one click.**

<div align="center">

### [⬇ Download Albedo-Setup.exe](https://github.com/Dracon420/Albedo-Local-AI/raw/master/Albedo-Setup.exe)

</div>

**Pre-requisites (installer checks these automatically):**

| Requirement | Why | Auto-install? |
|---|---|---|
| Windows 10 / 11 (64-bit) | Platform target | — |
| Python 3.12 | Albedo's runtime | Guided prompt |
| Ollama | Local LLM engine | Yes, via winget |
| GPU with 4 GB+ VRAM | Whisper + Ollama inference | — |

**Steps:**

1. **Download** `Albedo-Setup.exe` from the link above
2. **Run** the installer — accept the UAC prompt (needed to write to Program Files)
3. The **Setup Wizard** opens automatically after installation and walks you through:
   - Confirming Python 3.12 and Ollama are ready
   - Selecting your 3D printing and knowledge-base folders
   - Running the pip dependency install with a live progress bar
   - Pulling the Ollama model (`llama3.2:3b`)
   - Creating the **Albedo Mission Control** desktop shortcut
4. **Double-click** the Albedo shortcut — Mission Control opens

> **Piper TTS (optional):** Albedo works without voice output. To enable Kristin's voice, download the [Piper binary](https://github.com/rhasspy/piper/releases) and the `en_US-kristin-medium.onnx` voice model, then point the Setup Wizard to them.

---

### Path B — Developer Deployment *(Build from Source)*

For users who want to inspect, modify, or contribute to Albedo.

#### B.1 — Clone the repository

```powershell
cd "$env:USERPROFILE\Desktop"
git clone https://github.com/Dracon420/Albedo-Local-AI.git
cd Albedo-Local-AI
```

#### B.2 — Authorize and run the installer

Open **Terminal (Admin)** and run:

```powershell
Set-ExecutionPolicy Bypass -Scope Process
.\install.ps1
```

The script auto-detects your Python version, installs Python 3.12 if needed, creates `.venv`, installs all dependencies, pulls the Ollama model, and creates the desktop shortcut. Answer the prompts using the table below.

| Prompt | Recommended answer |
|---|---|
| Hardware tier | `1` — Standard (RTX 2060 / 16 GB RAM) |
| Chaotic 3D path | Your 3D printing folder, or blank to skip |
| Exotic OS path | Your code / log folder, or blank to skip |
| Piper paths | Press Enter for defaults |
| Wake word model | Press Enter (`hey_jarvis` placeholder) |
| Pull Ollama model now? | `y` |
| Run initial indexing? | `y` if you entered folder paths, else `n` |

#### B.3 — Launch

```powershell
.\Launch-Albedo.ps1
```

Or double-click the **Albedo** shortcut created on your Desktop.

---

## Mission Control — Quick Reference

| Action | How |
|---|---|
| Text query | Type in the input box, press **Enter** or **SEND** |
| Force web search | Prefix query with `web:` |
| Voice input | Press **MIC**, speak, then go silent or press **STOP** |
| Toggle TTS audio | Press **MIC** while text mode is active |
| RAG directories | Click **SETTINGS** in the Mission Control window |
| Re-index knowledge base | SETTINGS → RE-INDEX NOW, or `python main.py --index` |
| Terminal (text only) | `python main.py` |
| Terminal (voice mode) | `python main.py --voice` |
| Generate 3D inventory | `python generate_stl_manifest.py` then re-index |

---

## Maintenance & Uninstallation

`Albedo-Maintenance.ps1` is a menu-driven utility for keeping Albedo current.

```powershell
Set-ExecutionPolicy Bypass -Scope Process
.\Albedo-Maintenance.ps1
```

```
[1]  Update Albedo      -- git pull + pip upgrade
[2]  Uninstall Albedo   -- removes .venv, shortcut, optional chroma_db wipe
[3]  Exit
```

Python, Ollama, and Piper are **not** removed by the uninstaller. Remove those via **Settings → Apps** if needed.

---

## Hardware Tiers

| Setting | Standard (RTX 2060 · 6 GB VRAM) | High-Spec (RTX 3080+ · 8 GB+ VRAM) |
|---|---|---|
| `OLLAMA_MODEL` | `llama3.2:3b` | `llama3.1:8b` |
| `WHISPER_MODEL_SIZE` | `small` | `medium` |
| `WHISPER_COMPUTE_TYPE` | `int8_float16` | `float16` |
| `RAG_TOP_K` | `5` | `10` |

Edit `.env` directly and restart Albedo to switch tiers. No reinstall needed.

---

## RAG Initialization

Albedo's knowledge base indexes your own files into ChromaDB.

### Configure directories

Open `.env` and set:

```env
CHAOTIC_3D_PATH=D:\Chaotic 3D
EXOTIC_OS_PATH=D:\Exotic OS
```

**What gets indexed:**

| Collection | File types |
|---|---|
| Chaotic 3D | `.gcode` `.cfg` `.ini` `.json` `.txt` `.md` `.xml` |
| Exotic OS | `.py` `.sh` `.log` `.txt` `.md` `.json` `.yaml` `.toml` |

For reptile husbandry records, store feeding logs and enclosure notes as `.txt` or `.md` inside `EXOTIC_OS_PATH`.

### 3D model inventory (STL / 3MF / OBJ)

Binary geometry files cannot be indexed directly. Generate a text manifest first:

```powershell
python generate_stl_manifest.py
python main.py --index
```

### Run the indexer

```powershell
.\.venv\Scripts\Activate.ps1
python main.py --index
```

> **Indexing appears stalled?** Close any running 3D slicer (PrusaSlicer, Bambu Studio, Cura) — they hold file handles that saturate disk I/O. Wait at least 60 seconds before concluding it has frozen.

---

## Custom Wake Word (Cortana)

The default wake word (`hey_jarvis`) is a placeholder. To activate Albedo with **"Cortana"**, train a personal acoustic model:

1. Record 150–500 samples of yourself saying "Cortana" in varied conditions
2. Follow the [openWakeWord training guide](https://github.com/dscripka/openWakeWord#training-new-models) → output: `cortana.onnx`
3. Update `.env`:

```env
WAKEWORD_MODEL=C:\path\to\cortana.onnx
```

---

## Custom Desktop Icon

Place a file named **`albedo_icon.ico`** in the project root before running the installer. The Setup Wizard and `install.ps1` both detect it automatically and apply it to the shortcut. To update the icon after installation, replace the file and re-run the installer.

---

## Albedo Mobile HUD *(Optional)*

A React Native companion app that extends Albedo to your phone over Tailscale. No ports exposed to the internet.

**Prerequisites:** Expo Go ([iOS](https://apps.apple.com/app/expo-go/id982107779) · [Android](https://play.google.com/store/apps/details?id=host.exp.exponent)) · Tailscale on both devices

**Configuration:**

```powershell
tailscale ip -4   # note your desktop's IP
```

Edit `albedo-mobile/src/api/client.ts` line 6:

```typescript
export const SERVER_BASE = 'http://100.64.0.1:8000';  // replace with your Tailscale IP
```

**Launch:**

```powershell
# Terminal 1
python server.py

# Terminal 2
cd albedo-mobile
npx expo start
```

Scan the QR code with Expo Go. Tap the **AUDIO** chip to suppress TTS and receive text-only responses.

---

## Stack Reference

| Layer | Technology |
|---|---|
| LLM runtime | [Ollama](https://ollama.com) |
| Desktop control | [Open Interpreter](https://github.com/OpenInterpreter/open-interpreter) |
| Vector store | [ChromaDB](https://www.trychroma.com) |
| Speech-to-text | [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) |
| Wake word | [OpenWakeWord](https://github.com/dscripka/openWakeWord) |
| Text-to-speech | [Piper](https://github.com/rhasspy/piper) · voice: en_US-kristin-medium |
| Web search | [ddgs](https://github.com/deedy5/ddgs) — DuckDuckGo, no API key |
| Web scraping | Playwright · Trafilatura · BeautifulSoup4 |
| Desktop GUI | [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) |
| Mobile client | React Native · Expo 51 · Tailscale |
| Mobile bridge | FastAPI · Uvicorn |
| Installer | [Inno Setup 6](https://jrsoftware.org/isinfo.php) |

---

*Albedo is a local system. It does not call home.*
