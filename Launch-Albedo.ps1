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
$pythonw     = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
$mainPy      = Join-Path $projectRoot "main.py"

# ============================================================================
# Sanity checks
# ============================================================================

if (-not (Test-Path $python)) {
    Write-Host ""
    Write-Host "  [X] Virtual environment not found." -ForegroundColor Red
    Write-Host "      Expected: $python" -ForegroundColor Gray
    Write-Host ""

    # If setup_utility.py is present, offer to run it now rather than
    # leaving the user stranded at an error prompt.
    $setupScript = Join-Path $projectRoot "setup_utility.py"
    if (Test-Path $setupScript) {
        Write-Host "  The Albedo Setup Wizard was not completed." -ForegroundColor Yellow
        Write-Host "  Launching it now to finish installation..." -ForegroundColor Yellow
        Write-Host ""

        # Use pyw (windowless Python) so there is no console window to
        # accidentally close, which would kill the wizard mid-install.
        $pywExe = (Get-Command "pyw" -ErrorAction SilentlyContinue)
        if ($pywExe) {
            Start-Process -FilePath "pyw" `
                          -ArgumentList "-3.12 `"$setupScript`"" `
                          -Wait
        } else {
            $pythonwExe = (Get-Command "pythonw" -ErrorAction SilentlyContinue)
            if ($pythonwExe) {
                Start-Process -FilePath "pythonw" `
                              -ArgumentList "`"$setupScript`"" `
                              -Wait
            } else {
                Write-Host "  [X] Python not found on PATH." -ForegroundColor Red
                Write-Host "      Install Python 3.12 then re-run this shortcut." -ForegroundColor Gray
                Read-Host "  Press Enter to exit"
            }
        }
    } else {
        Write-Host "  Run setup_utility.py or install.ps1 to complete setup." -ForegroundColor Yellow
        Write-Host ""
        Read-Host "  Press Enter to exit"
    }
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
# Package health check -- redirect to wizard if customtkinter is missing
# ============================================================================

& $python -c "import customtkinter" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  [!]  Required packages are not installed in the virtual environment." -ForegroundColor Yellow
    Write-Host "       Launching Setup Wizard to complete installation..." -ForegroundColor Yellow
    Write-Host ""

    $setupScript = Join-Path $projectRoot "setup_utility.py"
    if (Test-Path $setupScript) {
        $pywExe = (Get-Command "pyw" -ErrorAction SilentlyContinue)
        if ($pywExe) {
            Start-Process -FilePath "pyw" `
                          -ArgumentList "-3.12 `"$setupScript`"" `
                          -Wait
        } else {
            $pythonw = $python -replace "python\.exe$", "pythonw.exe"
            $fwExe = if (Test-Path $pythonw) { $pythonw } else { $python }
            Start-Process -FilePath $fwExe `
                          -ArgumentList "`"$setupScript`"" `
                          -Wait
        }
    } else {
        Write-Host "  [X] setup_utility.py not found." -ForegroundColor Red
        Write-Host "      Re-run the installer or run: pip install -r requirements.txt" -ForegroundColor Gray
        Read-Host "  Press Enter to exit"
    }
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

$guiPy = Join-Path $projectRoot "gui.py"

Write-Host ""
Write-Host "  >> Launching Albedo Mission Control..." -ForegroundColor Cyan
Write-Host "     Close the window or press Ctrl+C to stop." -ForegroundColor Gray
Write-Host ""

if (Test-Path $guiPy) {
    # Prefer pythonw.exe (windowless) so no console can be accidentally closed.
    # Fall back to python.exe if the venv was created without pythonw (rare).
    $launcher = if (Test-Path $pythonw) { $pythonw } else { $python }
    & $launcher $guiPy
} else {
    Write-Host "    [!]  gui.py not found -- falling back to voice mode." -ForegroundColor DarkYellow
    & $python $mainPy --voice
}
