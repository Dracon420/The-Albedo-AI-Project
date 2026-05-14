#Requires -Version 5.1
<#
.SYNOPSIS
    Albedo installer -- sets up the Python environment, ChromaDB, web-scraping
    stack, and generates a .env configured for your hardware tier.
#>

Set-StrictMode -Version Latest
# NOTE: $ErrorActionPreference = "Stop" only catches PowerShell cmdlet errors.
# Native executables (pip, python, git) must be checked via $LASTEXITCODE.
# We use "Continue" here and do explicit exit-code checks after every native call.
$ErrorActionPreference = "Continue"

# ============================================================================
# Helpers
# ============================================================================

function Write-Banner {
    Write-Host ""
    Write-Host "  +----------------------------------------------+" -ForegroundColor Cyan
    Write-Host "  |       ALBEDO  --  Spartan-Class Setup        |" -ForegroundColor Cyan
    Write-Host "  |      Wake word: Cortana  |  Hybrid RAG       |" -ForegroundColor Cyan
    Write-Host "  +----------------------------------------------+" -ForegroundColor Cyan
    Write-Host ""
}

function Ask-Path {
    param([string]$Prompt, [string]$Default = "")
    $display = if ($Default) { "$Prompt [$Default]" } else { $Prompt }
    $raw = Read-Host $display
    $value = if ($raw.Trim() -eq "" -and $Default -ne "") { $Default } else { $raw.Trim() }
    return $value
}

function Ask-YesNo {
    param([string]$Prompt, [bool]$Default = $true)
    $hint = if ($Default) { "Y/n" } else { "y/N" }
    $raw = Read-Host "$Prompt [$hint]"
    if ($raw.Trim() -eq "") { return $Default }
    return $raw.Trim() -match '^[Yy]'
}

function Write-Step {
    param([string]$Text)
    Write-Host ""
    Write-Host "  >> $Text" -ForegroundColor Yellow
}

function Write-OK {
    param([string]$Text)
    Write-Host "    [OK] $Text" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Text)
    Write-Host "    [!]  $Text" -ForegroundColor DarkYellow
}

function Write-Fail {
    param([string]$Text)
    Write-Host "    [X]  $Text" -ForegroundColor Red
}

# Run a native executable and return $true if it exited cleanly.
function Invoke-Native {
    param([scriptblock]$Cmd, [string]$Label)
    & $Cmd
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "$Label exited with code $LASTEXITCODE"
        return $false
    }
    return $true
}

# Check whether a Python module is importable inside the venv.
function Test-Module {
    param([string]$Module)
    & $script:python -c "import $Module" 2>&1 | Out-Null
    return ($LASTEXITCODE -eq 0)
}

# ============================================================================
# Prerequisites
# ============================================================================

Write-Banner

Write-Step "Checking prerequisites..."

# Python 3.10+ (with warning for 3.13+ where ML wheels may be missing)
$pyver = ""
try {
    $pyver = (& python --version 2>&1).ToString().Trim()
} catch {
    Write-Host ""
    Write-Fail "Python not found on PATH."
    Write-Host "  Install Python 3.12 from: https://python.org/downloads/" -ForegroundColor Yellow
    Write-Host "  Then re-run this installer." -ForegroundColor Yellow
    exit 1
}

if ($pyver -match "Python (\d+)\.(\d+)") {
    $major = [int]$Matches[1]
    $minor = [int]$Matches[2]

    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
        Write-Fail "Python 3.10 or higher required (found $pyver)."
        Write-Host "  Install Python 3.12: https://python.org/downloads/" -ForegroundColor Yellow
        exit 1
    }

    if ($major -eq 3 -and $minor -ge 13) {
        Write-Host ""
        Write-Host "  +-------------------------------------------------+" -ForegroundColor Red
        Write-Host "  |  WARNING: Python $pyver detected              |" -ForegroundColor Red
        Write-Host "  |                                                 |" -ForegroundColor Red
        Write-Host "  |  The ML stack (tiktoken, faster-whisper, etc.)  |" -ForegroundColor Red
        Write-Host "  |  does not yet publish prebuilt wheels for 3.13+ |" -ForegroundColor Red
        Write-Host "  |  Packages will attempt to compile from source   |" -ForegroundColor Red
        Write-Host "  |  which requires the Rust compiler on Windows.   |" -ForegroundColor Red
        Write-Host "  |                                                 |" -ForegroundColor Red
        Write-Host "  |  RECOMMENDED: Use Python 3.12                   |" -ForegroundColor Red
        Write-Host "  |  winget install --id Python.Python.3.12         |" -ForegroundColor Red
        Write-Host "  +-------------------------------------------------+" -ForegroundColor Red
        Write-Host ""
        $cont = Ask-YesNo "  Continue with Python $major.$minor anyway?" $false
        if (-not $cont) {
            Write-Host "  Aborted. Install Python 3.12 and retry." -ForegroundColor Yellow
            exit 1
        }
    }

    Write-OK "$pyver"
} else {
    Write-Fail "Could not parse Python version from: $pyver"
    exit 1
}

# Git (optional)
try {
    $gitver = (& git --version 2>&1).ToString().Trim()
    Write-OK $gitver
} catch {
    Write-Warn "git not found -- version control features will be unavailable."
}

# ============================================================================
# Virtual environment
# ============================================================================

Write-Step "Setting up Python virtual environment..."

$venvPath = Join-Path $PSScriptRoot ".venv"
if (-not (Test-Path $venvPath)) {
    $ok = Invoke-Native { & python -m venv $venvPath } "python -m venv"
    if (-not $ok) { Write-Fail "Failed to create virtual environment."; exit 1 }
    Write-OK "Created .venv"
} else {
    Write-OK ".venv already exists -- skipping creation"
}

$pip    = Join-Path $venvPath "Scripts\pip.exe"
$python = Join-Path $venvPath "Scripts\python.exe"

if (-not (Test-Path $pip) -or -not (Test-Path $python)) {
    Write-Fail "Virtual environment appears broken (pip or python missing)."
    Write-Host "  Delete .venv and re-run the installer." -ForegroundColor Yellow
    exit 1
}

# ============================================================================
# Upgrade build tools FIRST
# This is critical -- outdated pip/wheel/setuptools are the #1 cause of
# source-build failures. Do this before touching requirements.txt.
# ============================================================================

Write-Step "Upgrading pip, wheel, and setuptools..."
$ok = Invoke-Native { & $python -m pip install --upgrade pip wheel setuptools } "pip upgrade"
if (-not $ok) {
    Write-Warn "Build tool upgrade had warnings -- continuing."
} else {
    Write-OK "pip, wheel, setuptools up to date"
}

# ============================================================================
# Pre-install tiktoken with a prebuilt binary wheel
#
# tiktoken (pulled by open-interpreter) requires Rust to compile from source.
# On Windows, prebuilt wheels exist for Python 3.10-3.12. If none is found
# (e.g. Python 3.13+), we detect Rust and guide the user before continuing.
# ============================================================================

Write-Step "Pre-installing tiktoken (prebuilt binary wheel)..."
& $pip install "tiktoken" --prefer-binary --quiet 2>&1 | Out-Null
$tiktokenOk = ($LASTEXITCODE -eq 0)

if (-not $tiktokenOk) {
    Write-Warn "No prebuilt tiktoken wheel found for this Python version."
    Write-Host ""

    # Check for Rust
    $rustVer = ""
    try { $rustVer = (& rustc --version 2>&1).ToString().Trim() } catch {}

    if ($rustVer -match "rustc") {
        Write-OK "Rust found: $rustVer -- tiktoken will compile from source."
        # Retry now that we know Rust is present
        Invoke-Native { & $pip install "tiktoken" } "tiktoken (from source)" | Out-Null
        $tiktokenOk = ($LASTEXITCODE -eq 0)
    } else {
        Write-Host "  +-------------------------------------------------+" -ForegroundColor Red
        Write-Host "  |  Rust compiler NOT FOUND                        |" -ForegroundColor Red
        Write-Host "  |                                                 |" -ForegroundColor Red
        Write-Host "  |  tiktoken must be compiled from source but      |" -ForegroundColor Red
        Write-Host "  |  no Rust toolchain was detected.                |" -ForegroundColor Red
        Write-Host "  |                                                 |" -ForegroundColor Red
        Write-Host "  |  OPTION A (recommended): Switch to Python 3.12  |" -ForegroundColor Yellow
        Write-Host "  |    winget install --id Python.Python.3.12       |" -ForegroundColor Gray
        Write-Host "  |                                                 |" -ForegroundColor Yellow
        Write-Host "  |  OPTION B: Install Rust, then re-run            |" -ForegroundColor Yellow
        Write-Host "  |    winget install --id Rustlang.Rustup          |" -ForegroundColor Gray
        Write-Host "  |    (close terminal, reopen, then re-run)        |" -ForegroundColor Gray
        Write-Host "  +-------------------------------------------------+" -ForegroundColor Red
        Write-Host ""
        $cont = Ask-YesNo "  Skip tiktoken and continue? (open-interpreter may not work)" $false
        if (-not $cont) {
            Write-Host "  Aborted. Follow Option A or B above, then re-run install.ps1." -ForegroundColor Yellow
            exit 1
        }
        Write-Warn "Skipping tiktoken -- open-interpreter functionality will be limited."
    }
} else {
    Write-OK "tiktoken installed (prebuilt wheel)"
}

# ============================================================================
# Python dependencies
# ============================================================================

Write-Step "Installing Python dependencies (this may take several minutes)..."
Write-Host "  Using --prefer-binary to avoid source compilation where possible." -ForegroundColor Gray

& $pip install --prefer-binary -r (Join-Path $PSScriptRoot "requirements.txt")
$depsOk = ($LASTEXITCODE -eq 0)

if (-not $depsOk) {
    Write-Host ""
    Write-Warn "One or more packages failed to install."
    Write-Warn "Albedo may be missing features. Review the errors above."
    Write-Host "  Tip: Most failures on Python 3.13+ are solved by switching to 3.12." -ForegroundColor Gray
    $cont = Ask-YesNo "  Continue with partial installation?" $true
    if (-not $cont) { exit 1 }
} else {
    Write-OK "All core packages installed"
}

# ============================================================================
# Playwright browser (guarded -- only runs if playwright module is present)
# ============================================================================

Write-Step "Installing Playwright Chromium for Open Interpreter web scraping..."
if (Test-Module "playwright") {
    $ok = Invoke-Native { & $python -m playwright install chromium } "playwright install"
    if ($ok) {
        Write-OK "Playwright Chromium ready"
    } else {
        Write-Warn "Playwright browser download failed -- web scraping will be limited."
        Write-Warn "Retry manually: .venv\Scripts\python.exe -m playwright install chromium"
    }
} else {
    Write-Warn "playwright module not installed -- skipping browser download."
    Write-Warn "Retry after fixing deps: .venv\Scripts\pip install playwright"
}

# ============================================================================
# OpenWakeWord models (guarded -- only runs if openwakeword is present)
# ============================================================================

Write-Step "Pre-downloading OpenWakeWord base models..."
if (Test-Module "openwakeword") {
    & $python -c "import openwakeword; openwakeword.utils.download_models()" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-OK "OpenWakeWord models cached"
    } else {
        Write-Warn "Model download had errors -- wake word may need manual setup."
        Write-Warn "Retry: .venv\Scripts\python.exe -c `"import openwakeword; openwakeword.utils.download_models()`""
    }
} else {
    Write-Warn "openwakeword module not installed -- wake word detection unavailable."
    Write-Warn "Retry after fixing deps: .venv\Scripts\pip install openwakeword"
}

# ============================================================================
# Hardware tier selection
# ============================================================================

Write-Host ""
Write-Host "  +---------------------------------------------------+" -ForegroundColor Magenta
Write-Host "  |            HARDWARE TIER SELECTION                |" -ForegroundColor Magenta
Write-Host "  |                                                   |" -ForegroundColor Magenta
Write-Host "  |  [1] STANDARD  -- RTX 2060 6 GB / 16 GB RAM      |" -ForegroundColor Magenta
Write-Host "  |      Whisper small  |  int8_float16               |" -ForegroundColor Magenta
Write-Host "  |      LLM: llama3.2:3b                             |" -ForegroundColor Magenta
Write-Host "  |                                                   |" -ForegroundColor Magenta
Write-Host "  |  [2] HIGH-SPEC -- RTX 3080+ / 8 GB+ VRAM         |" -ForegroundColor Magenta
Write-Host "  |      Whisper medium  |  float16                   |" -ForegroundColor Magenta
Write-Host "  |      LLM: llama3.1:8b                             |" -ForegroundColor Magenta
Write-Host "  +---------------------------------------------------+" -ForegroundColor Magenta
Write-Host ""

do {
    $tierInput = Read-Host "  Select tier [1/2]"
} while ($tierInput -notmatch '^[12]$')

$highSpec = ($tierInput -eq "2")

if ($highSpec) {
    $whisperModel   = "medium"
    $whisperCompute = "float16"
    $ollamaModel    = "llama3.1:8b"
    $ragTopK        = "10"
    $webMaxResults  = "10"
    $vadSilence     = "2.0"
    Write-OK "High-spec profile selected"
} else {
    $whisperModel   = "small"
    $whisperCompute = "int8_float16"
    $ollamaModel    = "llama3.2:3b"
    $ragTopK        = "5"
    $webMaxResults  = "5"
    $vadSilence     = "1.5"
    Write-OK "Standard profile selected (RTX 2060 VRAM budget preserved)"
}

# ============================================================================
# Directory configuration
# ============================================================================

Write-Host ""
Write-Host "  +---------------------------------------------------+" -ForegroundColor Cyan
Write-Host "  |         LOCAL KNOWLEDGE BASE DIRECTORIES         |" -ForegroundColor Cyan
Write-Host "  +---------------------------------------------------+" -ForegroundColor Cyan
Write-Host ""
Write-Host "  These directories are indexed into ChromaDB for local RAG."
Write-Host "  Leave blank to skip a collection (you can re-run --index later)."
Write-Host ""

$chaotic3dPath = Ask-Path "  Chaotic 3D path (STLs, gcode, slicer configs)"
$exoticOsPath  = Ask-Path "  Exotic OS path  (Python code, logs, configs)"

foreach ($pair in @(
    @{ Label = "Chaotic 3D"; Path = $chaotic3dPath },
    @{ Label = "Exotic OS";  Path = $exoticOsPath  }
)) {
    if ($pair.Path -ne "" -and -not (Test-Path $pair.Path)) {
        Write-Warn "$($pair.Label) path '$($pair.Path)' does not exist -- will be skipped during indexing"
    } elseif ($pair.Path -ne "") {
        Write-OK "$($pair.Label) -> $($pair.Path)"
    }
}

$chromaPath = Ask-Path "  ChromaDB storage path" "./chroma_db"
Write-OK "ChromaDB -> $chromaPath"

# ============================================================================
# Piper TTS paths
# ============================================================================

Write-Host ""
Write-Host "  +---------------------------------------------------+" -ForegroundColor Cyan
Write-Host "  |                   PIPER TTS                       |" -ForegroundColor Cyan
Write-Host "  |  Binary : https://github.com/rhasspy/piper        |" -ForegroundColor Cyan
Write-Host "  |  Voices : https://huggingface.co/rhasspy/         |" -ForegroundColor Cyan
Write-Host "  |           piper-voices                            |" -ForegroundColor Cyan
Write-Host "  +---------------------------------------------------+" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Leave blank to use console fallback until Piper is installed."
Write-Host ""

$piperBinary = Ask-Path "  piper.exe path" "C:\piper\piper.exe"
$piperVoice  = Ask-Path "  Voice .onnx path" "C:\piper\voices\en_US-ryan-high.onnx"

# ============================================================================
# Wake word model
# ============================================================================

Write-Host ""
$wakewordModel = Ask-Path "  Wake word model (label or .onnx path)" "hey_jarvis"
Write-Warn "To use 'Cortana' as wake word, train a custom model and point this at the .onnx file."
Write-Host "  Training guide: https://github.com/dscripka/openWakeWord#training-new-models"

# ============================================================================
# Ollama model override
# ============================================================================

Write-Host ""
$ollamaOverride = Ask-Path "  Ollama model (leave blank for tier default: $ollamaModel)" ""
if ($ollamaOverride -ne "") { $ollamaModel = $ollamaOverride }

# ============================================================================
# Generate .env
# ============================================================================

Write-Step "Writing .env..."

$envPath = Join-Path $PSScriptRoot ".env"

$highSpecFlag = if ($highSpec) { "true" } else { "false" }
$tierLabel    = if ($highSpec) { "high-spec" } else { "standard" }

$envContent = @"
# Generated by install.ps1 -- $(Get-Date -Format "yyyy-MM-dd HH:mm")
# HIGH_SPEC_PROFILE=$highSpecFlag

# --- Local directory paths ---
CHAOTIC_3D_PATH=$chaotic3dPath
EXOTIC_OS_PATH=$exoticOsPath

# --- ChromaDB ---
CHROMA_DB_PATH=$chromaPath

# --- Ollama ---
OLLAMA_MODEL=$ollamaModel
OLLAMA_BASE_URL=http://localhost:11434

# --- Albedo behaviour ---
RAG_TOP_K=$ragTopK
WEB_SEARCH_MAX_RESULTS=$webMaxResults

# --- Audio / Voice ---
PIPER_BINARY=$piperBinary
PIPER_VOICE_MODEL=$piperVoice
WAKEWORD_MODEL=$wakewordModel
WAKEWORD_THRESHOLD=0.5

# --- Faster-Whisper (tier: $tierLabel) ---
WHISPER_MODEL_SIZE=$whisperModel
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=$whisperCompute

# --- VAD ---
VAD_SILENCE_DURATION=$vadSilence
VAD_SILENCE_THRESHOLD=0.01
VAD_MAX_RECORD_SECONDS=30

WAKE_ACK_PHRASE=Yes?
"@

Set-Content -Path $envPath -Value $envContent -Encoding UTF8
Write-OK ".env written to $envPath"

# ============================================================================
# Initial index (guarded -- only runs if chromadb imported cleanly)
# ============================================================================

Write-Host ""
$doIndex = Ask-YesNo "  Run initial ChromaDB indexing now?" $true

if ($doIndex) {
    if (Test-Module "chromadb") {
        Write-Step "Indexing local directories into ChromaDB..."
        $ok = Invoke-Native { & $python (Join-Path $PSScriptRoot "main.py") --index } "main.py --index"
        if ($ok) {
            Write-OK "Indexing complete"
        } else {
            Write-Warn "Indexing exited with errors. Run 'python main.py --index' manually when ready."
        }
    } else {
        Write-Warn "chromadb not installed -- skipping index."
        Write-Warn "Fix dependencies first, then run: python main.py --index"
    }
} else {
    Write-Warn "Skipped -- run 'python main.py --index' when ready"
}

# ============================================================================
# Done
# ============================================================================

Write-Host ""
Write-Host "  +----------------------------------------------+" -ForegroundColor Green
Write-Host "  |             ALBEDO IS READY                  |" -ForegroundColor Green
Write-Host "  +----------------------------------------------+" -ForegroundColor Green
Write-Host ""
Write-Host "  Activate the virtual environment:" -ForegroundColor White
Write-Host "    .\.venv\Scripts\Activate.ps1" -ForegroundColor Gray
Write-Host ""
Write-Host "  Start Albedo:" -ForegroundColor White
Write-Host "    python main.py            # text chat" -ForegroundColor Gray
Write-Host "    python main.py --voice    # wake word + voice" -ForegroundColor Gray
Write-Host "    python main.py --index    # re-index knowledge base" -ForegroundColor Gray
Write-Host ""
Write-Host "  Make sure Ollama is running:" -ForegroundColor White
Write-Host "    ollama serve" -ForegroundColor Gray
Write-Host "    ollama pull $ollamaModel" -ForegroundColor Gray
Write-Host ""
