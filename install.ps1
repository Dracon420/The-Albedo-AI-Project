#Requires -Version 5.1
<#
.SYNOPSIS
    Albedo installer -- sets up the Python environment, ChromaDB, web-scraping
    stack, and generates a .env configured for your hardware tier.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

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

# ============================================================================
# Prerequisites
# ============================================================================

Write-Banner

Write-Step "Checking prerequisites..."

# Python 3.10+
try {
    $pyver = & python --version 2>&1
    if ($pyver -match "Python (\d+)\.(\d+)") {
        $major = [int]$Matches[1]; $minor = [int]$Matches[2]
        if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
            Write-Error "Python 3.10 or higher is required (found $pyver). Aborting."
        }
        Write-OK "$pyver"
    }
} catch {
    Write-Error "Python not found. Install from https://python.org and retry."
}

# Git
try {
    $gitver = & git --version 2>&1
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
    & python -m venv $venvPath
    Write-OK "Created .venv"
} else {
    Write-OK ".venv already exists -- skipping creation"
}

$pip    = Join-Path $venvPath "Scripts\pip.exe"
$python = Join-Path $venvPath "Scripts\python.exe"

# ============================================================================
# Python dependencies
# ============================================================================

Write-Step "Installing Python dependencies (this may take a few minutes)..."
& $pip install --upgrade pip --quiet
& $pip install -r (Join-Path $PSScriptRoot "requirements.txt")
Write-OK "Core packages installed"

# ============================================================================
# Playwright browser
# ============================================================================

Write-Step "Installing Playwright Chromium for Open Interpreter web scraping..."
& $python -m playwright install chromium
Write-OK "Playwright Chromium ready"

# ============================================================================
# OpenWakeWord models
# ============================================================================

Write-Step "Pre-downloading OpenWakeWord base models..."
& $python -c "import openwakeword; openwakeword.utils.download_models()" 2>$null
Write-OK "OpenWakeWord models cached"

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
# Initial index
# ============================================================================

Write-Host ""
$doIndex = Ask-YesNo "  Run initial ChromaDB indexing now?" $true

if ($doIndex) {
    Write-Step "Indexing local directories into ChromaDB..."
    & $python (Join-Path $PSScriptRoot "main.py") --index
    Write-OK "Indexing complete"
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
