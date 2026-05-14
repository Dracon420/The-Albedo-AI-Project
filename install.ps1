#Requires -Version 5.1
<#
.SYNOPSIS
    Albedo installer -- fully autonomous one-click setup.
    Auto-detects Python version, installs Python 3.12 via winget if the system
    default is 3.13+ (no ML wheels), creates the venv with the correct binary,
    upgrades build tools, installs all dependencies, and writes .env.
#>

# $ErrorActionPreference = "Continue" so native exe exit codes don't throw;
# we check $LASTEXITCODE manually after every external call.
$ErrorActionPreference = "Continue"
Set-StrictMode -Off

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
    if ($raw.Trim() -eq "" -and $Default -ne "") { return $Default }
    return $raw.Trim()
}

function Ask-YesNo {
    param([string]$Prompt, [bool]$Default = $true)
    $hint = if ($Default) { "Y/n" } else { "y/N" }
    $raw = Read-Host "$Prompt [$hint]"
    if ($raw.Trim() -eq "") { return $Default }
    return $raw.Trim() -match '^[Yy]'
}

function Write-Step  { param([string]$T); Write-Host ""; Write-Host "  >> $T" -ForegroundColor Yellow }
function Write-OK    { param([string]$T); Write-Host "    [OK] $T" -ForegroundColor Green }
function Write-Warn  { param([string]$T); Write-Host "    [!]  $T" -ForegroundColor DarkYellow }
function Write-Fail  { param([string]$T); Write-Host "    [X]  $T" -ForegroundColor Red }
function Write-Info  { param([string]$T); Write-Host "         $T" -ForegroundColor Gray }

# Runs a script block, returns $true on exit code 0, $false otherwise.
function Invoke-Native {
    param([scriptblock]$Cmd, [string]$Label)
    & $Cmd
    if ($LASTEXITCODE -ne 0) { Write-Fail "$Label failed (exit $LASTEXITCODE)"; return $false }
    return $true
}

# Returns $true if the given Python module is importable inside the venv.
function Test-Module {
    param([string]$Module)
    & $script:python -c "import $Module" 2>&1 | Out-Null
    return ($LASTEXITCODE -eq 0)
}

# Returns a hashtable @{Major;Minor;Full} or $null.
function Get-PyVersion {
    param([string]$Exe)
    try {
        $raw = (& $Exe --version 2>&1).ToString().Trim()
        if ($raw -match "Python (\d+)\.(\d+)") {
            return @{ Major = [int]$Matches[1]; Minor = [int]$Matches[2]; Full = $raw }
        }
    } catch {}
    return $null
}

# Tries every known strategy to locate a Python 3.12 executable.
function Find-Python312 {
    # Refresh PATH first so winget installs are visible
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH","User")

    # 1. Python Launcher (most reliable on Windows -- reads registry, not PATH)
    try {
        $exe = (& py -3.12 -c "import sys; print(sys.executable)" 2>&1).ToString().Trim()
        if ($exe -and (Test-Path $exe)) { return $exe }
    } catch {}

    # 2. Common install paths (user install and machine install)
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "C:\Python312\python.exe",
        "$env:ProgramW6432\Python312\python.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }

    # 3. Scan PATH entries for python3.12 or python.exe that reports 3.12
    foreach ($dir in ($env:PATH -split ";")) {
        $candidate = Join-Path $dir "python.exe"
        if (Test-Path $candidate) {
            $v = Get-PyVersion $candidate
            if ($null -ne $v -and $v.Major -eq 3 -and $v.Minor -eq 12) { return $candidate }
        }
    }

    return $null
}

# ============================================================================
# Banner
# ============================================================================

Write-Banner

# ============================================================================
# Step 1 -- Detect Python and auto-install 3.12 if needed
# ============================================================================

Write-Step "Detecting Python version..."

# Probe the system default python
$sysPyExe = $null
$sysPyVer = $null
try {
    $sysPyExe = (& python -c "import sys; print(sys.executable)" 2>&1).ToString().Trim()
    $sysPyVer = Get-PyVersion $sysPyExe
} catch {}

$pythonExe = $null   # will hold the exe we'll actually use

if ($null -eq $sysPyVer) {
    # No python on PATH at all
    Write-Warn "No Python found on PATH. Attempting auto-install of Python 3.12..."
    $pythonExe = $null   # handled below
} elseif ($sysPyVer.Major -eq 3 -and $sysPyVer.Minor -le 12 -and $sysPyVer.Minor -ge 10) {
    # Perfect -- 3.10, 3.11, or 3.12
    $pythonExe = $sysPyExe
    Write-OK "$($sysPyVer.Full) detected -- compatible"
} elseif ($sysPyVer.Major -eq 3 -and $sysPyVer.Minor -ge 13) {
    # 3.13+ -- ML wheels missing, need 3.12
    Write-Warn "$($sysPyVer.Full) detected -- ML packages lack prebuilt wheels for 3.13+."
    Write-Info "Searching for an existing Python 3.12 installation..."
    $pythonExe = Find-Python312
    if ($pythonExe) {
        $v312 = Get-PyVersion $pythonExe
        Write-OK "Found Python $($v312.Full) at: $pythonExe"
    }
} else {
    Write-Fail "Python $($sysPyVer.Full) is too old (3.10 minimum required)."
    Write-Info "Run: winget install --id Python.Python.3.12"
    exit 1
}

# -- Auto-install Python 3.12 via winget if we still don't have a good exe --

if ($null -eq $pythonExe) {
    Write-Host ""
    Write-Host "  +--------------------------------------------------+" -ForegroundColor Yellow
    Write-Host "  |  Python 3.12 not found -- auto-installing now    |" -ForegroundColor Yellow
    Write-Host "  |  This takes ~2 minutes. Please wait...           |" -ForegroundColor Yellow
    Write-Host "  +--------------------------------------------------+" -ForegroundColor Yellow
    Write-Host ""

    # Verify winget is available
    $wingetExe = $null
    try {
        $wingetExe = (& where.exe winget 2>&1 | Select-Object -First 1).ToString().Trim()
    } catch {}

    if (-not $wingetExe -or -not (Test-Path $wingetExe)) {
        Write-Fail "winget is not available on this system."
        Write-Host ""
        Write-Host "  Install Python 3.12 manually, then re-run install.ps1:" -ForegroundColor Yellow
        Write-Info "  https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
        exit 1
    }

    Write-Info "Running: winget install Python.Python.3.12 --silent ..."
    & winget install --id Python.Python.3.12 --silent `
        --accept-package-agreements --accept-source-agreements 2>&1

    $wingetOk = ($LASTEXITCODE -eq 0 -or $LASTEXITCODE -eq -1978335189)
    # -1978335189 = WINGET_INSTALLED_STATUS_ALREADY_INSTALLED (treat as success)

    if (-not $wingetOk) {
        Write-Fail "winget install exited with code $LASTEXITCODE."
        Write-Host ""
        Write-Host "  Install Python 3.12 manually, then re-run install.ps1:" -ForegroundColor Yellow
        Write-Info "  https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
        exit 1
    }

    Write-OK "winget install completed -- locating Python 3.12..."

    # Give the installer a moment to register paths
    Start-Sleep -Seconds 3

    $pythonExe = Find-Python312

    if ($null -eq $pythonExe) {
        Write-Fail "Python 3.12 installed but could not be located on disk."
        Write-Host ""
        Write-Host "  Close this terminal, open a new Admin PowerShell, and re-run:" -ForegroundColor Yellow
        Write-Info "  .\install.ps1"
        Write-Host "  (A new terminal picks up the updated PATH from winget.)" -ForegroundColor Gray
        exit 1
    }

    $v312 = Get-PyVersion $pythonExe
    Write-OK "Python $($v312.Full) ready at: $pythonExe"
}

# Final version sanity check
$chosenVer = Get-PyVersion $pythonExe
if ($null -eq $chosenVer) {
    Write-Fail "Cannot determine version of: $pythonExe"
    exit 1
}
Write-OK "Using $($chosenVer.Full) -- $pythonExe"

# ============================================================================
# Step 2 -- Git (optional)
# ============================================================================

try {
    $gitver = (& git --version 2>&1).ToString().Trim()
    Write-OK $gitver
} catch {
    Write-Warn "git not found -- version control features will be unavailable."
}

# ============================================================================
# Step 3 -- Ollama (check installed; auto-install via winget if missing)
# ============================================================================

Write-Step "Checking Ollama..."

$ollamaInstalled = $false
try {
    $ollamaVer = (& ollama --version 2>&1).ToString().Trim()
    if ($LASTEXITCODE -eq 0 -and $ollamaVer -ne "") {
        $ollamaInstalled = $true
        Write-OK "Ollama found: $ollamaVer"
    }
} catch {}

if (-not $ollamaInstalled) {
    Write-Warn "Ollama not found -- auto-installing via winget..."

    $wingetOk = $false
    try {
        & where.exe winget 2>&1 | Out-Null
        $wingetOk = ($LASTEXITCODE -eq 0)
    } catch {}

    if ($wingetOk) {
        & winget install -e --id Ollama.Ollama --silent `
            --accept-source-agreements --accept-package-agreements 2>&1

        # -1978335189 = WINGET_INSTALLED_STATUS_ALREADY_INSTALLED (treat as success)
        $wingetExitOk = ($LASTEXITCODE -eq 0 -or $LASTEXITCODE -eq -1978335189)

        if ($wingetExitOk) {
            # Refresh PATH so the new ollama.exe is visible in this session
            $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                        [System.Environment]::GetEnvironmentVariable("PATH","User")
            Start-Sleep -Seconds 2

            try {
                $ollamaVer = (& ollama --version 2>&1).ToString().Trim()
                if ($LASTEXITCODE -eq 0) {
                    $ollamaInstalled = $true
                    Write-OK "Ollama installed: $ollamaVer"
                }
            } catch {}

            if (-not $ollamaInstalled) {
                Write-Warn "Ollama installed but not yet on PATH in this session."
                Write-Info "Close and reopen this terminal, then re-run install.ps1 OR"
                Write-Info "launch Ollama from the Start Menu first."
            }
        } else {
            Write-Warn "winget install Ollama exited with code $LASTEXITCODE."
            Write-Info "Install manually from: https://ollama.com/download/windows"
        }
    } else {
        Write-Warn "winget not available -- cannot auto-install Ollama."
        Write-Info "Download from: https://ollama.com/download/windows"
    }
}

# ============================================================================
# Step 4 -- Virtual environment (created with the verified Python 3.12 binary)
# ============================================================================

Write-Step "Setting up Python 3.12 virtual environment..."

$venvPath = Join-Path $PSScriptRoot ".venv"

# If an existing .venv was built with the wrong Python version, wipe it.
$existingVenvPy = Join-Path $venvPath "Scripts\python.exe"
if (Test-Path $existingVenvPy) {
    $existingVer = Get-PyVersion $existingVenvPy
    if ($null -ne $existingVer -and $existingVer.Minor -ne $chosenVer.Minor) {
        Write-Warn "Existing .venv was built with Python 3.$($existingVer.Minor) -- rebuilding with 3.$($chosenVer.Minor)."
        Remove-Item $venvPath -Recurse -Force
    }
}

if (-not (Test-Path $venvPath)) {
    $ok = Invoke-Native { & $pythonExe -m venv $venvPath } "python -m venv"
    if (-not $ok) {
        Write-Fail "Failed to create virtual environment."
        Write-Info "Try: Remove-Item .venv -Recurse -Force  then re-run."
        exit 1
    }
    Write-OK "Created .venv (Python $($chosenVer.Full))"
} else {
    Write-OK ".venv already exists (Python $($chosenVer.Full))"
}

$pip    = Join-Path $venvPath "Scripts\pip.exe"
$python = Join-Path $venvPath "Scripts\python.exe"

if (-not (Test-Path $pip) -or -not (Test-Path $python)) {
    Write-Fail "Virtual environment is broken (pip or python missing inside .venv\Scripts\)."
    Write-Info "Delete .venv and re-run install.ps1."
    exit 1
}

# ============================================================================
# Step 4 -- Upgrade pip + wheel + setuptools BEFORE touching requirements.txt
# Outdated build tools are the #1 cause of wheel-not-found failures.
# ============================================================================

Write-Step "Upgrading pip, wheel, and setuptools..."
$ok = Invoke-Native {
    & $python -m pip install --upgrade pip wheel setuptools --quiet
} "pip/wheel/setuptools upgrade"
if ($ok) {
    Write-OK "Build tools upgraded"
} else {
    Write-Warn "Build tool upgrade had warnings -- continuing anyway."
}

# ============================================================================
# Step 5 -- Install requirements.txt
# --prefer-binary tells pip to always take a prebuilt wheel over source.
# With Python 3.12 this covers every package in the stack.
# ============================================================================

Write-Step "Installing Python dependencies (this may take several minutes)..."
Write-Info "Using --prefer-binary to skip source compilation."

& $pip install --prefer-binary -r (Join-Path $PSScriptRoot "requirements.txt")
$depsOk = ($LASTEXITCODE -eq 0)

if ($depsOk) {
    Write-OK "All packages installed successfully"
} else {
    Write-Host ""
    Write-Warn "One or more packages reported errors."
    Write-Info "Review the output above. If tiktoken still fails, ensure Python 3.12 is in use."
    $cont = Ask-YesNo "  Continue with partial installation?" $true
    if (-not $cont) { exit 1 }
}

# ============================================================================
# Step 6 -- Playwright browser (guarded)
# ============================================================================

Write-Step "Installing Playwright Chromium..."
if (Test-Module "playwright") {
    $ok = Invoke-Native { & $python -m playwright install chromium } "playwright install chromium"
    if ($ok) {
        Write-OK "Playwright Chromium ready"
    } else {
        Write-Warn "Browser download failed -- web scraping will be limited."
        Write-Info "Retry: .venv\Scripts\python.exe -m playwright install chromium"
    }
} else {
    Write-Warn "playwright not installed -- skipping browser download."
    Write-Info "Retry after fixing deps: .venv\Scripts\pip install playwright"
}

# ============================================================================
# Step 7 -- OpenWakeWord base models (guarded)
# ============================================================================

Write-Step "Pre-downloading OpenWakeWord models..."
if (Test-Module "openwakeword") {
    & $python -c "import openwakeword; openwakeword.utils.download_models()" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-OK "OpenWakeWord models cached"
    } else {
        Write-Warn "Model download had errors."
        Write-Info "Retry: .venv\Scripts\python.exe -c `"import openwakeword; openwakeword.utils.download_models()`""
    }
} else {
    Write-Warn "openwakeword not installed -- wake word detection unavailable."
    Write-Info "Retry after fixing deps: .venv\Scripts\pip install openwakeword"
}

# ============================================================================
# Step 8 -- Hardware tier selection
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

do { $tierInput = Read-Host "  Select tier [1/2]" } while ($tierInput -notmatch '^[12]$')
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
# Step 9 -- Directory configuration
# ============================================================================

Write-Host ""
Write-Host "  +---------------------------------------------------+" -ForegroundColor Cyan
Write-Host "  |         LOCAL KNOWLEDGE BASE DIRECTORIES         |" -ForegroundColor Cyan
Write-Host "  +---------------------------------------------------+" -ForegroundColor Cyan
Write-Host ""
Write-Host "  These directories are indexed into ChromaDB for local RAG."
Write-Host "  Leave blank to skip a collection (run --index later to add it)."
Write-Host ""

$chaotic3dPath = Ask-Path "  Chaotic 3D path (STLs, gcode, slicer configs)"
$exoticOsPath  = Ask-Path "  Exotic OS path  (Python code, logs, configs)"

foreach ($pair in @(
    @{ Label = "Chaotic 3D"; Path = $chaotic3dPath },
    @{ Label = "Exotic OS";  Path = $exoticOsPath  }
)) {
    if ($pair.Path -ne "" -and -not (Test-Path $pair.Path)) {
        Write-Warn "$($pair.Label) path does not exist -- will be skipped during indexing"
    } elseif ($pair.Path -ne "") {
        Write-OK "$($pair.Label) -> $($pair.Path)"
    }
}

$chromaPath = Ask-Path "  ChromaDB storage path" "./chroma_db"
Write-OK "ChromaDB -> $chromaPath"

# ============================================================================
# Step 10 -- Piper TTS
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
$piperVoice  = Ask-Path "  Voice .onnx path" "C:\piper\voices\en_US-kristin-medium.onnx"

# ============================================================================
# Step 11 -- Wake word model
# ============================================================================

Write-Host ""
$wakewordModel = Ask-Path "  Wake word model (label or .onnx path)" "hey_jarvis"
Write-Warn "To use 'Cortana', train a custom model and point this at the .onnx file."
Write-Info "Training guide: https://github.com/dscripka/openWakeWord#training-new-models"

# ============================================================================
# Step 12 -- Ollama model override
# ============================================================================

Write-Host ""
$ollamaOverride = Ask-Path "  Ollama model (leave blank for tier default: $ollamaModel)" ""
if ($ollamaOverride -ne "") { $ollamaModel = $ollamaOverride }

# ============================================================================
# Step 13 -- Generate .env
# ============================================================================

Write-Step "Writing .env..."

$envPath      = Join-Path $PSScriptRoot ".env"
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
# Step 14 -- Pull Ollama model
# ============================================================================

Write-Host ""
$doPull = Ask-YesNo "  Pull Ollama model now? ($ollamaModel -- may take several minutes)" $true

if ($doPull) {
    Write-Step "Pulling $ollamaModel from Ollama registry..."
    Write-Info "(Download size varies: 2-5 GB depending on model)"

    # Ollama pull does not require 'ollama serve' to be running.
    & ollama pull $ollamaModel
    if ($LASTEXITCODE -eq 0) {
        Write-OK "$ollamaModel ready"
    } else {
        Write-Warn "ollama pull exited with code $LASTEXITCODE."
        Write-Info "Retry manually: ollama pull $ollamaModel"
        Write-Info "Make sure Ollama is installed and 'ollama serve' is running."
    }
} else {
    Write-Warn "Skipped -- run 'ollama pull $ollamaModel' before launching Albedo."
}

# ============================================================================
# Step 15 -- Initial ChromaDB index (guarded)
# ============================================================================

Write-Host ""
$doIndex = Ask-YesNo "  Run initial ChromaDB indexing now?" $true

if ($doIndex) {
    if (Test-Module "chromadb") {
        Write-Step "Indexing local directories into ChromaDB..."
        $ok = Invoke-Native {
            & $python (Join-Path $PSScriptRoot "main.py") --index
        } "main.py --index"
        if ($ok) {
            Write-OK "Indexing complete"
        } else {
            Write-Warn "Indexing exited with errors."
            Write-Info "Run manually when ready: python main.py --index"
        }
    } else {
        Write-Warn "chromadb not installed -- skipping index."
        Write-Info "Fix deps first, then run: python main.py --index"
    }
} else {
    Write-Warn "Skipped -- run 'python main.py --index' when ready."
}

# ============================================================================
# Step 16 -- Desktop shortcut
# ============================================================================

Write-Step "Creating desktop shortcut..."

# Resolve to absolute path so the shortcut works from any drive or folder
$projectAbs   = (Resolve-Path $PSScriptRoot).Path
$launcherPath = Join-Path $projectAbs "Launch-Albedo.ps1"
$desktopPath  = [System.Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopPath "Albedo.lnk"

if (-not (Test-Path $launcherPath)) {
    Write-Warn "Launch-Albedo.ps1 not found -- skipping shortcut creation."
    Write-Info "Ensure Launch-Albedo.ps1 is in the same folder as install.ps1."
} else {
    try {
        # Delete the existing shortcut first so Windows does not serve a
        # stale cached icon from the old .lnk file
        if (Test-Path $shortcutPath) {
            Remove-Item -Force $shortcutPath
        }

        $shell    = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($shortcutPath)

        $shortcut.TargetPath       = "powershell.exe"
        $shortcut.Arguments        = "-ExecutionPolicy Bypass -WindowStyle Normal -File `"$launcherPath`""
        $shortcut.WorkingDirectory = $projectAbs
        $shortcut.Description      = "Launch Albedo -- Spartan-Class Local AI"

        # Absolute icon path -- relative paths silently fall back to the
        # default PowerShell icon because the shell resolves them from
        # system32, not the project root
        $icoPath = Join-Path $projectAbs "albedo_icon.ico"
        if (Test-Path $icoPath) {
            $shortcut.IconLocation = "$icoPath,0"
            Write-Info "Custom icon applied: albedo_icon.ico"
        } else {
            $shortcut.IconLocation = "powershell.exe,0"
        }

        $shortcut.Save()
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($shell) | Out-Null

        Write-OK "Desktop shortcut created: $shortcutPath"
        Write-Info "Double-click 'Albedo' on your desktop to launch."
    } catch {
        Write-Warn "Could not create shortcut: $_"
        Write-Info "Run Launch-Albedo.ps1 directly to start Albedo."
    }
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
Write-Info "  .\.venv\Scripts\Activate.ps1"
Write-Host ""
Write-Host "  Start Albedo:" -ForegroundColor White
Write-Info "  python main.py              # text chat"
Write-Info "  python main.py --voice      # wake word + voice"
Write-Info "  python main.py --index      # re-index knowledge base"
Write-Host ""
Write-Host "  Make sure Ollama is running:" -ForegroundColor White
Write-Info "  ollama serve"
Write-Info "  ollama pull $ollamaModel"
Write-Host ""
