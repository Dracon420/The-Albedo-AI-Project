#Requires -Version 5.1
<#
.SYNOPSIS
    Albedo master launcher.
    Starts Ollama serve silently in the background (if not already running),
    then launches Albedo in voice mode using the project virtual environment.
    Designed to be called directly from the desktop shortcut.
#>

$ErrorActionPreference = "Continue"

# Resolve project root relative to this script file
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$python      = Join-Path $projectRoot ".venv\Scripts\python.exe"
$mainPy      = Join-Path $projectRoot "main.py"

# ============================================================================
# Sanity checks
# ============================================================================

if (-not (Test-Path $python)) {
    Write-Host ""
    Write-Host "  [X] Virtual environment not found at:" -ForegroundColor Red
    Write-Host "      $python" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Run install.ps1 first to set up Albedo." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "  Press Enter to exit"
    exit 1
}

if (-not (Test-Path $mainPy)) {
    Write-Host ""
    Write-Host "  [X] main.py not found at: $mainPy" -ForegroundColor Red
    Write-Host "  Ensure this script is in the Albedo project root directory." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "  Press Enter to exit"
    exit 1
}

# ============================================================================
# Ollama -- start silently in background if not already running
# ============================================================================

Write-Host ""
Write-Host "  +----------------------------------------------+" -ForegroundColor Cyan
Write-Host "  |       ALBEDO  --  Spartan-Class Launch       |" -ForegroundColor Cyan
Write-Host "  +----------------------------------------------+" -ForegroundColor Cyan
Write-Host ""

$ollamaRunning = Get-Process -Name "ollama" -ErrorAction SilentlyContinue

if ($ollamaRunning) {
    Write-Host "    [OK] Ollama already running (PID $($ollamaRunning.Id))" -ForegroundColor Green
} else {
    # Verify ollama is on PATH before trying to start it
    $ollamaExe = $null
    try {
        $ollamaExe = (& where.exe ollama 2>&1 | Select-Object -First 1).ToString().Trim()
    } catch {}

    if ($ollamaExe -and (Test-Path $ollamaExe)) {
        Write-Host "  >> Starting Ollama serve in background..." -ForegroundColor Yellow
        Start-Process -FilePath "ollama" `
                      -ArgumentList "serve" `
                      -WindowStyle Hidden

        # Wait up to 8 seconds for the process to appear
        $waited = 0
        do {
            Start-Sleep -Milliseconds 500
            $waited += 500
            $ollamaRunning = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
        } while (-not $ollamaRunning -and $waited -lt 8000)

        if ($ollamaRunning) {
            Write-Host "    [OK] Ollama started (PID $($ollamaRunning.Id))" -ForegroundColor Green
        } else {
            Write-Host "    [!]  Ollama may still be starting -- continuing anyway." -ForegroundColor DarkYellow
        }
    } else {
        Write-Host "    [!]  ollama not found on PATH." -ForegroundColor DarkYellow
        Write-Host "         Install Ollama from https://ollama.com/download" -ForegroundColor Gray
        Write-Host "         or run install.ps1 again to auto-install it." -ForegroundColor Gray
        Write-Host ""
        Write-Host "  Albedo will still start but LLM calls will fail until Ollama is running." -ForegroundColor DarkYellow
    }
}

# ============================================================================
# Launch Albedo in voice mode
# ============================================================================

Write-Host ""
Write-Host "  >> Activating Albedo (voice mode)..." -ForegroundColor Cyan
Write-Host "     Say 'Cortana' to wake Albedo." -ForegroundColor Gray
Write-Host "     Press Ctrl+C to stop." -ForegroundColor Gray
Write-Host ""

& $python $mainPy --voice

# Keep the window open if Albedo exits unexpectedly
Write-Host ""
Write-Host "  Albedo exited. Press Enter to close this window." -ForegroundColor DarkYellow
Read-Host
