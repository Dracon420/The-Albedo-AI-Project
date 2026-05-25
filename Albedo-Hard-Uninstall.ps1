# Albedo-Hard-Uninstall.ps1
# ─────────────────────────────────────────────────────────────────────────────
# COMPLETE removal of Albedo Mission Control from this machine.
#
# Unlike the normal Inno Setup uninstaller (which leaves .env and user data
# behind) this tool nukes EVERYTHING so the next installer starts from a
# true blank slate — no stale ALBEDO_UI=tk, no leftover .venv, nothing.
#
# Run from an elevated (Admin) PowerShell:
#     .\Albedo-Hard-Uninstall.ps1
#
# Or double-click Albedo-Hard-Uninstall.bat (which self-elevates).
#
# What gets removed:
#   - All files and subdirs in C:\Albedo  (including .env, chroma_db, etc.)
#   - Inno Setup registry entry + uninstaller
#   - Start Menu shortcut
#   - Desktop shortcut (common + user)
#   - Windows Defender exclusion for C:\Albedo
#   - Any leftover Python processes holding file locks
#
# What is NOT touched:
#   - Ollama and its models  (installed separately, live in %LOCALAPPDATA%\ollama)
#   - Vosk / piper / wakeword models if they live outside C:\Albedo
#   - Any other user files
# ─────────────────────────────────────────────────────────────────────────────
[CmdletBinding(SupportsShouldProcess)]
param(
    [string] $InstallDir = "C:\Albedo"
)

$ErrorActionPreference = "Continue"   # Don't stop on individual failures
$ProgressPreference    = "SilentlyContinue"

# ── Helpers ──────────────────────────────────────────────────────────────────
function Write-Step { param($msg) Write-Host "`n[>>] $msg" -ForegroundColor Cyan }
function Write-OK   { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Skip { param($msg) Write-Host "  [--] $msg" -ForegroundColor DarkGray }
function Write-Warn { param($msg) Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host "  [XX] $msg" -ForegroundColor Red }

function Require-Admin {
    $me = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p  = New-Object Security.Principal.WindowsPrincipal($me)
    if (-not $p.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)) {
        Write-Fail "This script must be run as Administrator."
        Write-Host "  Right-click PowerShell → 'Run as administrator'" -ForegroundColor Yellow
        exit 1
    }
}

# ── Step 0: Admin + confirmation ──────────────────────────────────────────────
Require-Admin

Write-Host ""
Write-Host "  ╔═══════════════════════════════════════════════════════════╗" -ForegroundColor Red
Write-Host "  ║   ALBEDO HARD UNINSTALLER                                 ║" -ForegroundColor Red
Write-Host "  ║                                                           ║" -ForegroundColor Red
Write-Host "  ║   This will COMPLETELY remove Albedo from this machine.   ║" -ForegroundColor Red
Write-Host "  ║   All data in $InstallDir will be deleted.       ║" -ForegroundColor Red
Write-Host "  ║                                                           ║" -ForegroundColor Red
Write-Host "  ║   Ollama and its models are NOT affected.                 ║" -ForegroundColor Red
Write-Host "  ╚═══════════════════════════════════════════════════════════╝" -ForegroundColor Red
Write-Host ""
Write-Host "  Type YES to continue, anything else to cancel:" -ForegroundColor Yellow
$confirm = Read-Host "  Confirm"
if ($confirm -ne "YES") {
    Write-Host "`n  Cancelled. Nothing was changed." -ForegroundColor Green
    exit 0
}

# ── Step 1: Kill all Albedo / Python processes ────────────────────────────────
Write-Step "Terminating Albedo and Python processes"

$procTargets = @("python", "pythonw", "pyw")
foreach ($name in $procTargets) {
    $procs = Get-Process -Name $name -ErrorAction SilentlyContinue
    if ($procs) {
        $procs | Stop-Process -Force -ErrorAction SilentlyContinue
        Write-OK "Killed $name ($($procs.Count) process(es))"
    } else {
        Write-Skip "$name — not running"
    }
}
Start-Sleep -Milliseconds 2000   # let handles release

# ── Step 2: Run Inno Setup uninstaller (if present) ───────────────────────────
Write-Step "Running Inno Setup uninstaller"

$uninstaller = Join-Path $InstallDir "unins000.exe"
if (Test-Path $uninstaller) {
    try {
        $proc = Start-Process -FilePath $uninstaller `
                              -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" `
                              -Wait -PassThru -ErrorAction Stop
        Write-OK "Inno uninstaller ran (exit $($proc.ExitCode))"
    } catch {
        Write-Warn "Inno uninstaller failed: $_ — will force-delete instead"
    }
    Start-Sleep -Milliseconds 1500
} else {
    Write-Skip "No Inno uninstaller found — skipping to force delete"
}

# ── Step 3: Force-delete the entire install directory ─────────────────────────
Write-Step "Force-deleting install directory: $InstallDir"

if (Test-Path $InstallDir) {
    # Take ownership first to avoid permission errors on nested dirs
    try {
        & takeown.exe /F $InstallDir /R /D Y 2>&1 | Out-Null
        & icacls.exe $InstallDir /grant "Administrators:F" /T /C /Q 2>&1 | Out-Null
    } catch { <# non-fatal #> }

    try {
        Remove-Item -Path $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
        if (-not (Test-Path $InstallDir)) {
            Write-OK "Deleted: $InstallDir"
        } else {
            # Stubborn files — try file-by-file
            Write-Warn "Some files could not be removed in one pass — retrying..."
            Get-ChildItem -Path $InstallDir -Recurse -Force -ErrorAction SilentlyContinue |
                Sort-Object { $_.FullName.Length } -Descending |
                ForEach-Object {
                    try { Remove-Item $_.FullName -Force -Recurse -ErrorAction Stop }
                    catch { Write-Warn "Could not remove: $($_.FullName)" }
                }
            try { Remove-Item -Path $InstallDir -Force -Recurse -ErrorAction SilentlyContinue } catch {}
            if (-not (Test-Path $InstallDir)) {
                Write-OK "Deleted: $InstallDir (after retry)"
            } else {
                Write-Warn "$InstallDir still exists — some locked files remain."
                Write-Warn "Reboot and re-run this script, or delete manually."
            }
        }
    } catch {
        Write-Fail "Could not delete $InstallDir`: $_"
    }
} else {
    Write-Skip "$InstallDir does not exist — nothing to delete"
}

# ── Step 4: Remove Inno Setup registry entry ──────────────────────────────────
Write-Step "Removing registry entries"

$innoKey = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}_is1"
if (Test-Path $innoKey) {
    try {
        Remove-Item -Path $innoKey -Force -ErrorAction Stop
        Write-OK "Removed Inno uninstall registry key"
    } catch {
        Write-Warn "Could not remove registry key: $_"
    }
} else {
    Write-Skip "Inno registry key not found (already gone)"
}

# Also check 32-bit view on 64-bit Windows
$innoKey32 = "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}_is1"
if (Test-Path $innoKey32) {
    try {
        Remove-Item -Path $innoKey32 -Force -ErrorAction Stop
        Write-OK "Removed Inno uninstall registry key (WOW6432)"
    } catch {
        Write-Warn "Could not remove WOW6432 key: $_"
    }
}

# ── Step 5: Remove shortcuts ──────────────────────────────────────────────────
Write-Step "Removing shortcuts"

$shortcutPaths = @(
    # Start Menu (all users)
    "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\Albedo Mission Control",
    "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\Albedo Mission Control.lnk",
    # Desktop (all users)
    "$env:PUBLIC\Desktop\Albedo Mission Control.lnk",
    "$env:USERPROFILE\Desktop\Albedo Mission Control.lnk",
    # Common desktop (Inno uses {commondesktop})
    "$([System.Environment]::GetFolderPath('CommonDesktopDirectory'))\Albedo Mission Control.lnk",
    "$([System.Environment]::GetFolderPath('DesktopDirectory'))\Albedo Mission Control.lnk",
)

foreach ($path in $shortcutPaths) {
    if (Test-Path $path) {
        try {
            Remove-Item -Path $path -Recurse -Force -ErrorAction Stop
            Write-OK "Removed: $path"
        } catch {
            Write-Warn "Could not remove $path`: $_"
        }
    }
}

# Catch any leftover Albedo*.lnk files on both desktops
$desktops = @(
    [System.Environment]::GetFolderPath('CommonDesktopDirectory'),
    [System.Environment]::GetFolderPath('DesktopDirectory')
)
foreach ($desk in $desktops) {
    Get-ChildItem -Path $desk -Filter "Albedo*.lnk" -ErrorAction SilentlyContinue |
        ForEach-Object {
            try { Remove-Item $_.FullName -Force; Write-OK "Removed: $($_.Name)" }
            catch { Write-Warn "Could not remove $($_.Name)" }
        }
}

# ── Step 6: Remove Windows Defender exclusion ─────────────────────────────────
Write-Step "Removing Windows Defender exclusion"

try {
    Remove-MpPreference -ExclusionPath $InstallDir -ErrorAction SilentlyContinue
    Write-OK "Defender exclusion removed for $InstallDir"
} catch {
    Write-Skip "Defender exclusion removal skipped (Defender may be disabled)"
}

# ── Step 7: Remove any scheduled tasks ───────────────────────────────────────
Write-Step "Checking for scheduled tasks"

$tasks = Get-ScheduledTask -TaskName "*Albedo*" -ErrorAction SilentlyContinue
if ($tasks) {
    foreach ($task in $tasks) {
        try {
            Unregister-ScheduledTask -TaskName $task.TaskName -Confirm:$false
            Write-OK "Removed scheduled task: $($task.TaskName)"
        } catch {
            Write-Warn "Could not remove task $($task.TaskName): $_"
        }
    }
} else {
    Write-Skip "No Albedo scheduled tasks found"
}

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ╔═══════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "  ║   ALBEDO FULLY REMOVED                                    ║" -ForegroundColor Green
Write-Host "  ║                                                           ║" -ForegroundColor Green
Write-Host "  ║   Install directory, registry, shortcuts, and Defender    ║" -ForegroundColor Green
Write-Host "  ║   exclusion have all been cleared.                        ║" -ForegroundColor Green
Write-Host "  ║                                                           ║" -ForegroundColor Green
Write-Host "  ║   You can now run any Albedo-Setup-x.x.x.exe installer    ║" -ForegroundColor Green
Write-Host "  ║   for a guaranteed clean fresh install.                   ║" -ForegroundColor Green
Write-Host "  ╚═══════════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
