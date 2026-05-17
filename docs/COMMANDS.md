# ALBEDO // COMMAND REFERENCE

Complete catalog of voice and text commands recognized by Albedo Mission Control.
Commands are processed in priority order — local intercepts fire before any LLM or cloud call.

---

## CONVERSATIONAL

### Identity & Capability

Bypass all RAG and LLM routing. Instant hardcoded response.

| Example Phrase | Variants |
|---|---|
| "who are you" | "what are you", "tell me about yourself" |
| "what can you do" | "what are your capabilities", "what are you capable of" |
| "introduce yourself" | "who is albedo", "what is albedo", "describe yourself" |
| "what do you do" | "what can you help with", "your functions" |

---

### Social Exchanges

Queries under 40 characters with no technical keywords bypass RAG entirely and get an instant brief reply.

| Category | Phrases |
|---|---|
| Greetings | hello, hi, hey, howdy, sup, yo |
| Acknowledgements | ok, okay, got it, understood, sure, alright, sounds good |
| Affirmations | yes, no, nope, yep, yeah, yup |
| Thanks | thanks, thank you, ty, thx, cheers, appreciate it |
| Farewells | bye, goodbye, cya, later, see you |
| Time of day | good morning, good afternoon, good evening, good night |
| Status check | how are you, how are you doing, how's it going |
| Reactions | cool, nice, great, awesome, perfect |

---

## LOCAL

Local commands are intercepted in Python before the LLM pipeline. No cloud calls, no latency.

### Hardware — Audit & Diagnostics

Returns a full tactical report: CPU, cores, clock speed, RAM, GPU name, VRAM, thermals, storage, temp-file cleanup, top processes, and system advisories.

**Exact phrases (any of these trigger the audit):**

```
audit                    sitrep                   hardware audit
system audit             tactical audit           system report
hardware report          run audit                run sitrep
my hardware              my specs                 my system specs
my pc specs              my rig specs             hardware info
system info              system specs             pc specs
rig specs                detect my hardware       what is my hardware
what's my hardware       my system info           show my hardware
show my specs            my computer specs        what hardware
what cpu                 what gpu                 what ram
what processor           what graphics            what is in my computer
what is in my pc         whats in my pc           inside my computer
my computer hardware     my pc hardware           my rig hardware
```

**Natural verb + noun patterns also match:**

- **Verbs:** optimize, check, scan, diagnose, analyse, analyze, clean, audit, detect, identify, report, display, show, list, find, get, tell, give, what, which, how
- **Nouns:** computer, system, pc, rig, machine, hardware, specs, specifications, components, vitals, cpu, gpu, ram, memory, vram, processor, graphics card, storage, drive, ssd, hdd

**Examples:**
```
"scan my system"
"diagnose my pc"
"show my vitals"
"what graphics card do i have"
"identify my components"
```

---

### Hardware — Optimization & Overclocking

Detects overclocking intent, injects your real hardware specs into the prompt, and routes to Gemini for specific tuning guidance tailored to your rig.

| Trigger Keyword | Example |
|---|---|
| overclock / overclocking | "how do I overclock my GPU" |
| oc my / oc the | "oc my RTX 2060" |
| boost my / tune my | "boost my RAM", "tune my CPU" |
| push my / max out my | "push my GPU to the limit" |
| best settings for | "best settings for my RTX 2060" |
| xmp / expo / docp | "how do I enable XMP" |
| undervolting / undervolt | "how to undervolt my GPU" |
| power limit | "set GPU power limit" |
| optimize my gpu | "optimize my GPU performance" |
| optimize my cpu | "optimize my CPU" |
| optimize my ram | "optimize my RAM timings" |

---

### Hardware — Verify Protocol

Queries containing any of these keywords trigger the Verify Protocol: local Obsidian vault search + live web cross-reference before generating a response.

```
error        crash        driver       temperature   thermal
overheat     gpu          cpu          ram           memory
vram         bsod         freeze       lag           bottleneck
fps          stuttering   artifact     kernel        hardware
diagnose     diagnosis    not working  failed        failure
```

**Examples:**
```
"my GPU is overheating"
"why is my RAM showing wrong in BIOS"
"fix my driver crash"
"what causes BSOD on Windows 11"
"my fps is dropping after driver update"
```

---

### System — Process Management

#### List Running Processes

```
"what processes are running"
"show top processes"
"list programs consuming RAM"
"what apps are using the most CPU"
"which processes are eating memory"
"top apps by memory"
```

Returns the top 8 processes by RAM usage with memory and CPU percentages.

#### Kill / Terminate a Process

```
kill {name}           "kill chrome"
close {name}          "close explorer"
end process {name}    "end process java"
terminate {name}      "terminate notepad"
stop {name}           "stop task manager"
```

---

### System — Disk & Temp Cleanup

Clears Windows temporary files. Reports MB freed and locked files skipped.

```
"clean my disk"
"clear temp"
"free up space"
"wipe storage"
"clean my drive"
"clean temp files"
"free up drive space"
```

Pattern matches: `clean / clear / free up / wipe` + `disk / storage / drive / space / temp / junk`

---

### System — Program Launch

```
open {app}      "open notepad"
start {app}     "start steam"
launch {app}    "launch chrome"
run {app}       "run blender"
execute {app}   "execute powershell"
```

**Supported applications:**

| App Name | Aliases |
|---|---|
| Notepad | notepad |
| Calculator | calculator, calc |
| File Explorer | file explorer, explorer |
| Task Manager | task manager, taskmgr |
| Paint | paint |
| Command Prompt | cmd, command prompt |
| PowerShell | powershell |
| Google Chrome | chrome, google chrome |
| Firefox | firefox |
| Microsoft Edge | edge, microsoft edge |
| Spotify | spotify |
| Steam | steam |
| Discord | discord |
| VS Code | vs code, vscode, visual studio code |
| Blender | blender |
| OBS Studio | obs |
| VLC | vlc |
| MSI Afterburner | afterburner, msi afterburner |
| HWiNFO64 | hwinfo, hwinfo64 |
| GPU-Z | gpu-z |
| CPU-Z | cpu-z |
| Task Scheduler | task scheduler |
| Device Manager | device manager |
| Disk Management | disk management |
| Registry Editor | regedit |

---

### Files — Count by Extension

```
"how many PNG files do I have"
"count my jpg files"
"how many mp3s"
"total STL files"
"do I have any gcode files"
"find all txt files"
```

Pattern matches: `how many / count / number of / total / do i have any / find / list / show` + `{extension} files`

Searches configured paths (CHAOTIC_3D_PATH, OBSIDIAN_VAULT_PATH) plus standard Windows user directories.

---

### Memory — Obsidian Vault / RAG

#### Reindex Knowledge Vault

Rebuilds the semantic ChromaDB index from your Obsidian vault.

```
"index vault"
"reindex vault"
"re-index vault"
```

Also accessible via **Settings → RE-INDEX NOW** button.

#### Query Local Memory

Any query routed to the `"memory"` channel searches your indexed Obsidian notes:

```
"what did I write about {topic}"
"find my notes on {subject}"
"what do I know about {topic}"
"check my vault for {keyword}"
```

---

### Memory — Dream Cycle / Consolidation

Runs LLM reflection over daily interaction traces and appends insights back to the knowledge vault.

```
"dream cycle"
"rem cycle"
"initiate dream"
"run dream"
```

---

## ONLINE

Online commands reach external services. Requires internet access. Web search and weather are always additive — local RAG runs first where applicable.

### Web Search

Force a live DuckDuckGo search regardless of routing.

```
web: {your query}
```

**Examples:**
```
"web: latest RTX 5090 benchmarks"
"web: Python 3.13 release notes"
"web: price of NVIDIA stock today"
```

Without the `web:` prefix, Albedo decides whether to search the web based on query type.

---

### Weather

Any query containing "weather" is intercepted, location-normalized, and answered via Gemini in a single sentence using Fahrenheit.

```
"what's the weather"
"weather in Seattle"
"weather near me"
"is it raining locally"
"what's the forecast for tomorrow"
"weather in my city"
```

**Location phrases automatically resolved to your configured NODE_LOCATION:**

| Phrase | Resolved to |
|---|---|
| "near me" | in {NODE_LOCATION} |
| "my location" | in {NODE_LOCATION} |
| "where I am" | in {NODE_LOCATION} |
| "my area" | the {NODE_LOCATION} area |
| "my city" / "my town" | {NODE_LOCATION} |
| "nearby" | near {NODE_LOCATION} |
| "locally" | in {NODE_LOCATION} |

Set `NODE_LOCATION` in `.env` to your city/region. Default: Raymond, Washington.

---

### Cloud-Routed Intelligence

Queries that don't match a local intercept are routed by the autonomous commander to the appropriate cloud backend:

| Route | Backend | Used for |
|---|---|---|
| `direct` | Gemini | General questions, weather, factual queries, casual conversation |
| `groq` | Groq API | Python scripts, fast data formatting, code generation |
| `together` | Together AI | Complex debugging, logic puzzles, multi-step reasoning |
| `local` | Ollama (Llama 3.2) | Local system tasks, offline operation, fallback |
| `memory` | Obsidian RAG | Past projects, personal notes, Albedo configs |

Set API keys via **Settings → API KEYS** or directly in `.env`.

---

## VISION

Triggered via the **SCAN** button in Mission Control (not voice-activated).

Captures a live webcam frame, sends it to the Moondream multimodal model via Ollama, and speaks + logs the visual analysis.

```
Click SCAN → Moondream describes what the webcam sees
```

Temperature is clamped to `0.2` for concise, deterministic output. No files written to disk.

---

## VOICE & PERSONA

### Wake Words

Albedo listens passively for the active persona's wake word via OpenWakeWord.

| Persona | Wake Word | Voice |
|---|---|---|
| Cortana | "hey cortana" | Kristin (en_US, medium) |
| Jarvis | "hey jarvis" | Ryan (en_US, medium) |

Switch active persona via **Settings → PERSONA & WAKE WORD → SAVE**.

### Voice Input Flow

1. Say the wake word — or press **MIC** in Mission Control
2. Speak your command
3. Go silent (VAD gate) or press **STOP** to submit immediately
4. Albedo processes and responds via TTS + chat log

---

## GUI CONTROLS

Button-driven actions in Mission Control — not available via voice.

| Control | Action |
|---|---|
| **SEND** / `Enter` | Submit typed query |
| **MIC** | Begin voice input session |
| **STOP** | End voice capture immediately |
| **SCAN** | Capture webcam frame → Moondream visual analysis |
| **AUDIO: ON / MUTE** | Toggle TTS playback (kills active audio instantly) |
| **SETTINGS** | Open settings: vault path, persona, API keys, auto-update, background |
| **HARDWARE** | Open hardware settings: audio input/output device assignment |
| **LOGS** | Open developer console (live stdout/stderr from all modules) |
| **UPDATE** | Check GitHub for new commits → pull → restart if update found |
| **RESTART** | Gracefully restart Mission Control |
| **RE-INDEX NOW** | Rebuild ChromaDB index from Obsidian vault (in Settings) |

---

## ENVIRONMENT VARIABLES

Key `.env` values that control command behavior:

| Variable | Purpose | Default |
|---|---|---|
| `NODE_LOCATION` | Location used for weather queries | Raymond, Washington |
| `OBSIDIAN_VAULT_PATH` | Path indexed for local RAG | — |
| `CHAOTIC_3D_PATH` | Path scanned for file-count queries | — |
| `OLLAMA_MODEL` | LLM model for local inference | llama3.2:3b |
| `GEMINI_API_KEY` | Gemini (direct/OC routing) | — |
| `GROQ_API_KEY` | Groq (script/format routing) | — |
| `TOGETHER_API_KEY` | Together AI (complex reasoning) | — |
| `PIPER_VOICE_MODEL` | Active TTS voice path | kristin-medium.onnx |

---

*Last updated: 2026-05-16*
