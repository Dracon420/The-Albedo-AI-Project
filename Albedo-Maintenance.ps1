#Requires -Version 5.1
<#
.SYNOPSIS
    Albedo maintenance utility.
    Provides update and uninstall operations without touching system-level
    dependencies (Python, Ollama, Piper).

.PARAMETER AutoUpdate
    Run a non-interactive update (git pull + pip upgrade) and exit.
    Used by the "Update Albedo" Start Menu shortcut.
#>
param(
    [switch]$AutoUpdate
)

$ErrorActionPreference = "Continue"

$projectRoot  = Split-Path -Parent $MyInvocation.MyCommand.Definition
$venvPip      = Join-Path $projectRoot ".venv\Scripts\pip.exe"
$venvPython   = Join-Path $projectRoot ".venv\Scripts\python.exe"
$chromaPath   = Join-Path $projectRoot "chroma_db"
$desktopPath  = [System.Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopPath "Albedo.lnk"

# ============================================================================
# Output helpers
# ============================================================================

function Write-Header {
    Write-Host ""
    Write-Host "  +------------------------------------------+" -ForegroundColor Cyan
    Write-Host "  |     ALBEDO  --  Maintenance Utility      |" -ForegroundColor Cyan
    Write-Host "  +------------------------------------------+" -ForegroundColor Cyan
    Write-Host ""
}

function Write-OK   ([string]$msg) { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Warn ([string]$msg) { Write-Host "    [!]  $msg" -ForegroundColor Yellow }
function Write-Err  ([string]$msg) { Write-Host "    [X]  $msg" -ForegroundColor Red }
function Write-Info ([string]$msg) { Write-Host "         $msg" -ForegroundColor Gray }
function Write-Step ([string]$msg) { Write-Host "  >> $msg"    -ForegroundColor Cyan }

# ============================================================================
# Update
# ============================================================================

function Invoke-DownloadVoices {
    $voicesDir = Join-Path $projectRoot "voices"
    if (-not (Test-Path $voicesDir)) { New-Item -ItemType Directory -Path $voicesDir | Out-Null }

    $base = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US"
    $files = @(
        "kristin/medium/en_US-kristin-medium.onnx",
        "kristin/medium/en_US-kristin-medium.onnx.json",
        "ryan/medium/en_US-ryan-medium.onnx",
        "ryan/medium/en_US-ryan-medium.onnx.json"
    )
    foreach ($f in $files) {
        $filename = Split-Path $f -Leaf
        $dest = Join-Path $voicesDir $filename
        if (Test-Path $dest) { continue }
        Write-Info "Downloading $filename..."
        try {
            Invoke-WebRequest -Uri "$base/$f" -OutFile $dest -UseBasicParsing -ErrorAction Stop
            Write-OK "$filename downloaded."
        } catch {
            Write-Warn "Could not download $filename (non-fatal): $_"
        }
    }
}

function Invoke-Update {
    Write-Host ""
    Write-Step "Pulling latest code from GitHub..."
    Write-Host ""

    Push-Location $projectRoot
    git pull
    $pullExit = $LASTEXITCODE
    Pop-Location

    if ($pullExit -ne 0) {
        Write-Warn "git pull returned exit code $pullExit."
        Write-Info "If this is not a git repository, updates must be applied manually."
    } else {
        Write-OK "Repository updated."
    }

    Write-Host ""

    if (-not (Test-Path $venvPip)) {
        Write-Err "Virtual environment not found. Run install.ps1 first."
        return
    }

    # Close any running Albedo GUI window before touching pip cache
    Get-Process -Name "pythonw" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1

    Write-Step "Upgrading pip, wheel, and setuptools..."
    & $venvPython -m pip install --upgrade pip wheel setuptools --no-cache-dir --quiet
    Write-OK "Build tools upgraded."

    Write-Host ""
    Write-Step "Upgrading Python dependencies..."
    # --no-cache-dir prevents Errno 13 Permission denied on locked wheel cache files
    & $venvPip install -r (Join-Path $projectRoot "requirements.txt") `
        --upgrade --prefer-binary --no-cache-dir --quiet

    if ($LASTEXITCODE -eq 0) {
        Write-OK "All packages up to date."
    } else {
        Write-Warn "One or more packages reported an issue (exit $LASTEXITCODE)."
        Write-Info "Review the output above for details."
    }

    Write-Host ""
    Write-Step "Ensuring voice models are present..."
    Invoke-DownloadVoices

    Write-Host ""
    Write-OK "Update complete. Restart Albedo to apply changes."
    Write-Host ""
}

# ============================================================================
# Uninstall
# ============================================================================

function Invoke-Uninstall {
    Write-Host ""
    Write-Host "  This will remove:" -ForegroundColor Yellow
    Write-Host "    - The .venv virtual environment"            -ForegroundColor Gray
    Write-Host "    - The Albedo desktop shortcut"              -ForegroundColor Gray
    Write-Host "  It will NOT remove Python, Ollama, or Piper." -ForegroundColor Gray
    Write-Host ""

    $confirm = Read-Host "  Type CONFIRM to proceed, or press Enter to cancel"
    if ($confirm -ne "CONFIRM") {
        Write-Warn "Uninstall cancelled."
        return
    }

    # -- Remove virtual environment ------------------------------------------
    Write-Host ""
    Write-Step "Removing virtual environment..."
    $venvDir = Join-Path $projectRoot ".venv"
    if (Test-Path $venvDir) {
        Remove-Item -Recurse -Force $venvDir -ErrorAction SilentlyContinue
        if (Test-Path $venvDir) {
            Write-Warn "Could not fully remove .venv -- some files may be locked."
            Write-Info "Close any terminals that have the venv activated and try again."
        } else {
            Write-OK ".venv removed."
        }
    } else {
        Write-Info ".venv not found -- already removed."
    }

    # -- Remove desktop shortcut ---------------------------------------------
    Write-Step "Removing desktop shortcut..."
    if (Test-Path $shortcutPath) {
        Remove-Item -Force $shortcutPath -ErrorAction SilentlyContinue
        Write-OK "Desktop shortcut removed."
    } else {
        Write-Info "Shortcut not found -- already removed."
    }

    # -- Optional: wipe ChromaDB ---------------------------------------------
    Write-Host ""
    if (Test-Path $chromaPath) {
        $wipeChroma = Read-Host "  Wipe local ChromaDB storage (./chroma_db)? All indexed knowledge will be lost. [y/N]"
        if ($wipeChroma -match "^[Yy]$") {
            Remove-Item -Recurse -Force $chromaPath -ErrorAction SilentlyContinue
            if (Test-Path $chromaPath) {
                Write-Warn "Could not fully remove chroma_db -- some files may be locked."
            } else {
                Write-OK "ChromaDB storage wiped."
            }
        } else {
            Write-Info "ChromaDB storage kept at: $chromaPath"
        }
    } else {
        Write-Info "No ChromaDB storage found."
    }

    Write-Host ""
    Write-OK "Albedo uninstalled."
    Write-Info "The project folder itself has not been deleted."
    Write-Info "To reinstall, run install.ps1 from this directory."
    Write-Host ""
}

# ============================================================================
# Entry point -- AutoUpdate short-circuits the interactive menu
# ============================================================================

if ($AutoUpdate) {
    Write-Header
    Invoke-Update
    exit 0
}

# ============================================================================
# Menu loop
# ============================================================================

Write-Header

while ($true) {
    Write-Host "  Select an operation:" -ForegroundColor White
    Write-Host ""
    Write-Host "    [1]  Update Albedo" -ForegroundColor Cyan
    Write-Host "    [2]  Uninstall Albedo" -ForegroundColor Yellow
    Write-Host "    [3]  Exit" -ForegroundColor Gray
    Write-Host ""

    $choice = Read-Host "  Enter choice"

    switch ($choice.Trim()) {
        "1" { Invoke-Update }
        "2" { Invoke-Uninstall; break }
        "3" { Write-Host ""; exit 0 }
        default {
            Write-Warn "Invalid selection. Enter 1, 2, or 3."
            Write-Host ""
        }
    }

    if ($choice.Trim() -eq "2") { exit 0 }
}
