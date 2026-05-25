@echo off
:: Albedo-Hard-Uninstall.bat — STANDALONE, no companion .ps1 needed
:: Double-click and run as Administrator.
:: Self-elevates if not already admin, then runs embedded PowerShell.

:: ── Self-elevation ────────────────────────────────────────────────────────
net session >nul 2>&1
if %errorLevel% NEQ 0 (
    echo Requesting administrator privileges...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

:: ── Extract and run embedded PowerShell ──────────────────────────────────
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
"$script = @'" & echo. & ^
"# embedded" & echo. & ^
"'@" & echo. & ^
"Invoke-Expression $script"

:: The above approach is unreliable for large scripts.
:: Instead write the script to a temp file and run it.

set "TMPSCRIPT=%TEMP%\albedo_hard_uninstall_%RANDOM%.ps1"

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
 "$c=Get-Content -Raw -LiteralPath '%~f0'; $m=[regex]::Match($c,'(?s)::##PS1_START##\r?\n(.+?)\r?\n::##PS1_END##'); [System.IO.File]::WriteAllText('%TMPSCRIPT%',$m.Groups[1].Value,[System.Text.Encoding]::UTF8)"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%TMPSCRIPT%"
del /f /q "%TMPSCRIPT%" 2>nul

echo.
echo  Press any key to close...
pause >nul
exit /b

::##PS1_START##
# Albedo-Hard-Uninstall - embedded PowerShell (do not edit this section)
# Called by the .bat wrapper above. Requires admin (bat handles elevation).

$ErrorActionPreference = "Continue"
$ProgressPreference    = "SilentlyContinue"
$InstallDir            = "C:\Albedo"

function Write-Step { param($msg) Write-Host "`n[>>] $msg" -ForegroundColor Cyan }
function Write-OK   { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Skip { param($msg) Write-Host "  [--] $msg" -ForegroundColor DarkGray }
function Write-Warn { param($msg) Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host "  [XX] $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "  +===========================================================+" -ForegroundColor Red
Write-Host "  |   ALBEDO HARD UNINSTALLER                                 |" -ForegroundColor Red
Write-Host "  |                                                           |" -ForegroundColor Red
Write-Host "  |   This will COMPLETELY remove Albedo from this machine.   |" -ForegroundColor Red
Write-Host "  |   C:\Albedo and ALL its contents will be deleted.         |" -ForegroundColor Red
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
foreach ($name in @("python","pythonw","pyw")) {
    $procs = Get-Process -Name $name -ErrorAction SilentlyContinue
    if ($procs) {
        $procs | Stop-Process -Force -ErrorAction SilentlyContinue
        Write-OK "Killed $name ($($procs.Count) instance(s))"
    } else { Write-Skip "$name not running" }
}
Start-Sleep -Milliseconds 2000

# Step 2: Run Inno uninstaller
Write-Step "Running Inno Setup uninstaller"
$unins = Join-Path $InstallDir "unins000.exe"
if (Test-Path $unins) {
    try {
        $p = Start-Process $unins -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART" -Wait -PassThru
        Write-OK "Inno uninstaller ran (exit $($p.ExitCode))"
    } catch { Write-Warn "Inno uninstaller failed: $_ -- continuing" }
    Start-Sleep -Milliseconds 1500
} else { Write-Skip "No Inno uninstaller found" }

# Step 3: Force-delete entire install dir
Write-Step "Force-deleting: $InstallDir"
if (Test-Path $InstallDir) {
    try { & takeown.exe /F $InstallDir /R /D Y 2>&1 | Out-Null } catch {}
    try { & icacls.exe $InstallDir /grant "Administrators:F" /T /C /Q 2>&1 | Out-Null } catch {}
    Remove-Item -Path $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path $InstallDir)) {
        Write-OK "Deleted: $InstallDir"
    } else {
        Write-Warn "Some files remain — retrying file by file..."
        Get-ChildItem $InstallDir -Recurse -Force -ErrorAction SilentlyContinue |
            Sort-Object { $_.FullName.Length } -Descending |
            ForEach-Object { try { Remove-Item $_.FullName -Force -Recurse -ErrorAction Stop } catch {} }
        try { Remove-Item $InstallDir -Force -Recurse -ErrorAction SilentlyContinue } catch {}
        if (Test-Path $InstallDir) {
            Write-Warn "$InstallDir still has locked files. Reboot and delete manually."
        } else { Write-OK "Deleted: $InstallDir (after retry)" }
    }
} else { Write-Skip "$InstallDir does not exist" }

# Step 4: Remove registry key
Write-Step "Removing registry entries"
$keys = @(
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}_is1",
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}_is1"
)
foreach ($key in $keys) {
    if (Test-Path $key) {
        try { Remove-Item $key -Force; Write-OK "Removed: $key" }
        catch { Write-Warn "Could not remove $key`: $_" }
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
        catch { Write-Warn "Could not remove $p" }
    }
}
foreach ($desk in @([System.Environment]::GetFolderPath('CommonDesktopDirectory'),
                    [System.Environment]::GetFolderPath('DesktopDirectory'))) {
    Get-ChildItem $desk -Filter "Albedo*.lnk" -ErrorAction SilentlyContinue |
        ForEach-Object { try { Remove-Item $_.FullName -Force; Write-OK "Removed: $($_.Name)" } catch {} }
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
Write-Host "  |   You can now run Albedo-Setup-x.x.x.exe for a clean     |" -ForegroundColor Green
Write-Host "  |   fresh install with the setup wizard.                    |" -ForegroundColor Green
Write-Host "  +===========================================================+" -ForegroundColor Green
Write-Host ""
::##PS1_END##
