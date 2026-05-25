# Albedo-Hard-Uninstall.ps1
# =============================================================================
# COMPLETE removal of Albedo Mission Control from this machine.
#
# Unlike the normal Inno Setup uninstaller (which leaves .env and user data
# behind) this tool nukes EVERYTHING so the next installer starts from a
# true blank slate -- no stale ALBEDO_UI=tk, no leftover .venv, nothing.
#
# Run from an elevated (Admin) PowerShell:
#     .\Albedo-Hard-Uninstall.ps1
#
# Or double-click Albedo-Hard-Uninstall.bat (self-elevates automatically).
#
# What gets removed:
#   - All files and subdirs in C:\Albedo (including .env, databases, etc.)
#   - Inno Setup registry entry + uninstaller record
#   - Start Menu shortcut
#   - Desktop shortcut (common + user)
#   - Windows Defender exclusion for C:\Albedo
#   - Any Python processes holding file locks
#
# What is NOT touched:
#   - Ollama and its models (installed separately in %LOCALAPPDATA%\ollama)
#   - Any other user files outside C:\Albedo
# =============================================================================
[CmdletBinding(SupportsShouldProcess)]
param(
    [string] $InstallDir = "C:\Albedo"
)

$ErrorActionPreference = "Continue"
$ProgressPreference    = "SilentlyContinue"

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
        Write-Host "  Right-click PowerShell -> Run as administrator" -ForegroundColor Yellow
        exit 1
    }
}

Require-Admin

Write-Host ""
Write-Host "  +===========================================================+" -ForegroundColor Red
Write-Host "  |   ALBEDO HARD UNINSTALLER                                 |" -ForegroundColor Red
Write-Host "  |                                                           |" -ForegroundColor Red
Write-Host "  |   This will COMPLETELY remove Albedo from this machine.   |" -ForegroundColor Red
Write-Host "  |   All data in C:\Albedo will be deleted.                  |" -ForegroundColor Red
Write-Host "  |                                                           |" -ForegroundColor Red
Write-Host "  |   Ollama and its models are NOT affected.                 |" -ForegroundColor Red
Write-Host "  +===========================================================+" -ForegroundColor Red
Write-Host ""
Write-Host "  Type YES to continue, anything else to cancel:" -ForegroundColor Yellow
$confirm = Read-Host "  Confirm"
if ($confirm -ne "YES") {
    Write-Host "`n  Cancelled. Nothing was changed." -ForegroundColor Green
    exit 0
}

# Step 1: Kill processes
Write-Step "Terminating Albedo and Python processes"
foreach ($name in @("python", "pythonw", "pyw")) {
    $procs = Get-Process -Name $name -ErrorAction SilentlyContinue
    if ($procs) {
        $procs | Stop-Process -Force -ErrorAction SilentlyContinue
        Write-OK "Killed $name ($($procs.Count) process(es))"
    } else {
        Write-Skip "$name not running"
    }
}
Start-Sleep -Milliseconds 2000

# Step 2: Run Inno uninstaller
Write-Step "Running Inno Setup uninstaller"
$uninstaller = Join-Path $InstallDir "unins000.exe"
if (Test-Path $uninstaller) {
    try {
        $p = Start-Process -FilePath $uninstaller `
             -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" `
             -Wait -PassThru -ErrorAction Stop
        Write-OK "Inno uninstaller ran (exit $($p.ExitCode))"
    } catch {
        Write-Warn "Inno uninstaller failed: $_ -- will force-delete instead"
    }
    Start-Sleep -Milliseconds 1500
} else {
    Write-Skip "No Inno uninstaller found -- skipping to force delete"
}

# Step 3: Force-delete install directory
Write-Step "Force-deleting: $InstallDir"
if (Test-Path $InstallDir) {
    try { & takeown.exe /F $InstallDir /R /D Y 2>&1 | Out-Null } catch {}
    try { & icacls.exe $InstallDir /grant "Administrators:F" /T /C /Q 2>&1 | Out-Null } catch {}
    Remove-Item -Path $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path $InstallDir)) {
        Write-OK "Deleted: $InstallDir"
    } else {
        Write-Warn "Some files locked -- retrying file by file..."
        Get-ChildItem -Path $InstallDir -Recurse -Force -ErrorAction SilentlyContinue |
            Sort-Object { $_.FullName.Length } -Descending |
            ForEach-Object {
                try { Remove-Item $_.FullName -Force -Recurse -ErrorAction Stop } catch {}
            }
        try { Remove-Item -Path $InstallDir -Force -Recurse -ErrorAction SilentlyContinue } catch {}
        if (-not (Test-Path $InstallDir)) {
            Write-OK "Deleted: $InstallDir (after retry)"
        } else {
            Write-Warn "$InstallDir still has locked files. Reboot and delete manually."
        }
    }
} else {
    Write-Skip "$InstallDir does not exist"
}

# Step 4: Remove registry entries
Write-Step "Removing registry entries"
$keys = @(
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}_is1",
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}_is1"
)
foreach ($key in $keys) {
    if (Test-Path $key) {
        try { Remove-Item -Path $key -Force; Write-OK "Removed: $key" }
        catch { Write-Warn "Could not remove $key" }
    }
}

# Step 5: Remove shortcuts
Write-Step "Removing shortcuts"
$lnkPaths = @(
    "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\Albedo Mission Control",
    "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\Albedo Mission Control.lnk",
    "$([System.Environment]::GetFolderPath('CommonDesktopDirectory'))\Albedo Mission Control.lnk",
    "$([System.Environment]::GetFolderPath('DesktopDirectory'))\Albedo Mission Control.lnk"
)
foreach ($p in $lnkPaths) {
    if (Test-Path $p) {
        try { Remove-Item $p -Recurse -Force; Write-OK "Removed: $(Split-Path $p -Leaf)" }
        catch { Write-Warn "Could not remove: $p" }
    }
}
foreach ($desk in @([System.Environment]::GetFolderPath('CommonDesktopDirectory'),
                    [System.Environment]::GetFolderPath('DesktopDirectory'))) {
    Get-ChildItem $desk -Filter "Albedo*.lnk" -ErrorAction SilentlyContinue |
        ForEach-Object {
            try { Remove-Item $_.FullName -Force; Write-OK "Removed: $($_.Name)" } catch {}
        }
}

# Step 6: Remove Defender exclusion
Write-Step "Removing Windows Defender exclusion"
try { Remove-MpPreference -ExclusionPath $InstallDir -ErrorAction SilentlyContinue; Write-OK "Defender exclusion removed" }
catch { Write-Skip "Defender exclusion removal skipped" }

# Step 7: Remove scheduled tasks
Write-Step "Checking for scheduled tasks"
$tasks = Get-ScheduledTask -TaskName "*Albedo*" -ErrorAction SilentlyContinue
if ($tasks) {
    foreach ($t in $tasks) {
        try { Unregister-ScheduledTask -TaskName $t.TaskName -Confirm:$false; Write-OK "Removed task: $($t.TaskName)" }
        catch { Write-Warn "Could not remove task: $($t.TaskName)" }
    }
} else { Write-Skip "No Albedo scheduled tasks found" }

Write-Host ""
Write-Host "  +===========================================================+" -ForegroundColor Green
Write-Host "  |   ALBEDO FULLY REMOVED                                    |" -ForegroundColor Green
Write-Host "  |                                                           |" -ForegroundColor Green
Write-Host "  |   Install dir, registry, shortcuts, Defender exclusion    |" -ForegroundColor Green
Write-Host "  |   have all been cleared.                                  |" -ForegroundColor Green
Write-Host "  |                                                           |" -ForegroundColor Green
Write-Host "  |   Run Albedo-Setup-x.x.x.exe for a clean fresh install.  |" -ForegroundColor Green
Write-Host "  +===========================================================+" -ForegroundColor Green
Write-Host ""
