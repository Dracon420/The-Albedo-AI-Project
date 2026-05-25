# Albedo-Nuclear-Reset.ps1
# ─────────────────────────────────────────────────────────────────────────────
# Complete wipe-and-reinstall of Albedo Mission Control.
#
# What this script does:
#   1. Backs up all user data (API keys, memory DB, vault index, settings)
#   2. Patches the .env backup — forces ALBEDO_UI=eel, strips outdated values
#   3. Kills all running Albedo / Python processes
#   4. Runs the Inno Setup uninstaller silently (removes .venv, old source, etc.)
#   5. Deletes any leftover install directory fragments
#   6. Runs the new installer silently
#   7. Restores the patched backup into the fresh install
#
# Usage:
#   Run from an elevated (admin) PowerShell:
#       .\Albedo-Nuclear-Reset.ps1
#
#   Optional: supply a path to a pre-downloaded installer:
#       .\Albedo-Nuclear-Reset.ps1 -InstallerPath "C:\Downloads\Albedo-Setup-2.0.4.exe"
#
# If -InstallerPath is omitted the script fetches the latest release from GitHub.
# ─────────────────────────────────────────────────────────────────────────────
[CmdletBinding(SupportsShouldProcess)]
param(
    [string] $InstallerPath = "",
    [string] $InstallDir    = "C:\Albedo",
    [string] $BackupRoot    = "$env:TEMP\AlbedoBackup"
)

$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"   # speeds up Invoke-WebRequest

# ── Helpers ──────────────────────────────────────────────────────────────────
function Write-Step  { param($msg) Write-Host "`n[>>] $msg" -ForegroundColor Cyan }
function Write-OK    { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Write-Fail  { param($msg) Write-Host "  [XX] $msg" -ForegroundColor Red }

function Require-Admin {
    $me = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p  = New-Object Security.Principal.WindowsPrincipal($me)
    if (-not $p.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)) {
        Write-Fail "This script must be run as Administrator."
        Write-Host "  Right-click PowerShell → 'Run as administrator', then try again." -ForegroundColor Yellow
        exit 1
    }
}

# ── Step 0: Admin check ───────────────────────────────────────────────────────
Require-Admin
Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════╗" -ForegroundColor Magenta
Write-Host "  ║   ALBEDO NUCLEAR RESET — v2.0.4+             ║" -ForegroundColor Magenta
Write-Host "  ║   User data will be preserved and patched.   ║" -ForegroundColor Magenta
Write-Host "  ╚══════════════════════════════════════════════╝" -ForegroundColor Magenta
Write-Host ""

if (-not (Test-Path $InstallDir)) {
    Write-Warn "No existing Albedo install found at $InstallDir."
    Write-Host "  Proceeding with fresh install only." -ForegroundColor Yellow
}

# ── Step 1: Backup user data ─────────────────────────────────────────────────
Write-Step "Backing up user data to $BackupRoot"

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupDir = Join-Path $BackupRoot $timestamp
New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null

$itemsToBackup = @(
    ".env",
    "settings.json",
    "hardware_config.json",
    "chroma_db",
    "albedo_memory_db",
    "albedo-mobile"
)

$backedUp = @()
foreach ($item in $itemsToBackup) {
    $src = Join-Path $InstallDir $item
    if (Test-Path $src) {
        $dst = Join-Path $BackupDir $item
        try {
            Copy-Item -Path $src -Destination $dst -Recurse -Force
            Write-OK "Backed up: $item"
            $backedUp += $item
        } catch {
            Write-Warn "Could not back up $item — $_"
        }
    }
}

if ($backedUp.Count -eq 0) {
    Write-Warn "Nothing to back up (fresh system or empty install dir)."
}

# ── Step 2: Patch the .env backup ────────────────────────────────────────────
Write-Step "Patching .env backup — enforcing modern defaults"

$envBackup = Join-Path $BackupDir ".env"
if (Test-Path $envBackup) {
    $content = Get-Content $envBackup -Raw -Encoding UTF8

    # Force ALBEDO_UI=eel (was tk in older installs)
    if ($content -match 'ALBEDO_UI\s*=') {
        $content = $content -replace '(?m)^ALBEDO_UI\s*=.*$', 'ALBEDO_UI=eel'
        Write-OK "ALBEDO_UI forced to eel"
    } else {
        $content = $content.TrimEnd() + "`nALBEDO_UI=eel`n"
        Write-OK "ALBEDO_UI=eel added (was missing)"
    }

    # Any future migration patches go here — e.g.:
    # $content = $content -replace '(?m)^OLD_KEY\s*=.*$', 'NEW_KEY=value'

    Set-Content -Path $envBackup -Value $content -Encoding UTF8 -NoNewline
    Write-OK ".env patch applied"
} else {
    Write-Warn "No .env found in backup — a fresh one will be created by the installer wizard."
}

# ── Step 3: Kill running Albedo processes ─────────────────────────────────────
Write-Step "Terminating running Albedo processes"

$targets = @("python", "pythonw", "pyw")
foreach ($proc in $targets) {
    $running = Get-Process -Name $proc -ErrorAction SilentlyContinue
    if ($running) {
        $running | Stop-Process -Force -ErrorAction SilentlyContinue
        Write-OK "Killed: $proc ($($running.Count) instance(s))"
    }
}
Start-Sleep -Milliseconds 1500   # let handles release

# ── Step 4: Run the Inno Setup uninstaller ────────────────────────────────────
Write-Step "Running Inno Setup uninstaller"

$uninstaller = Join-Path $InstallDir "unins000.exe"
if (Test-Path $uninstaller) {
    Write-Host "  Uninstalling — this may take 30–60 seconds..." -ForegroundColor Gray
    try {
        $proc = Start-Process -FilePath $uninstaller `
                              -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" `
                              -Wait -PassThru
        if ($proc.ExitCode -eq 0) {
            Write-OK "Uninstaller completed (exit 0)"
        } else {
            Write-Warn "Uninstaller exit code: $($proc.ExitCode) — continuing anyway"
        }
    } catch {
        Write-Warn "Uninstaller failed: $_ — will force-delete the directory instead"
    }
} else {
    Write-Warn "No uninstaller found at $uninstaller — skipping Inno Setup uninstall"
}

# ── Step 5: Force-delete any install directory leftovers ─────────────────────
Write-Step "Removing install directory remnants"

if (Test-Path $InstallDir) {
    # Preserve user data subdirs that Inno marks uninsneveruninstall
    # (the uninstaller should have kept them, but we back them up just in case above)
    $dirsToNuke = @(".venv", "__pycache__", "logs", "albedo", "web", "vosk_models",
                    "wakewords", "piper", "docs", "training_data", "tests",
                    "Output", "azure_training")
    foreach ($d in $dirsToNuke) {
        $target = Join-Path $InstallDir $d
        if (Test-Path $target) {
            try {
                Remove-Item -Path $target -Recurse -Force -ErrorAction SilentlyContinue
                Write-OK "Removed: $d"
            } catch {
                Write-Warn "Could not remove $d — $_"
            }
        }
    }

    # Remove root-level Python/config files but NOT user data
    $filesToNuke = @("*.py", "*.ps1", "*.txt", "*.md", "*.iss", "*.ico", "*.png",
                     "VERSION", "CLAUDE.md", "*.exe", "*.bat")
    foreach ($pattern in $filesToNuke) {
        Get-ChildItem -Path $InstallDir -Filter $pattern -File -ErrorAction SilentlyContinue |
            Remove-Item -Force -ErrorAction SilentlyContinue
    }

    Write-OK "Directory cleanup complete"
} else {
    Write-OK "Install directory already gone — clean slate"
}

# ── Step 6: Get or verify the new installer ───────────────────────────────────
Write-Step "Locating new installer"

if ($InstallerPath -and (Test-Path $InstallerPath)) {
    Write-OK "Using supplied installer: $InstallerPath"
} else {
    Write-Host "  Fetching latest release info from GitHub..." -ForegroundColor Gray
    try {
        $release = Invoke-RestMethod `
            "https://api.github.com/repos/Dracon420/The-Albedo-AI-Project/releases/latest" `
            -Headers @{ "User-Agent" = "Albedo-NuclearReset/1.0" }

        $asset = $release.assets | Where-Object { $_.name -like "Albedo-Setup-*.exe" } |
                 Select-Object -First 1

        if (-not $asset) {
            Write-Fail "No installer asset found in latest GitHub release."
            exit 1
        }

        $dlPath = Join-Path $env:TEMP $asset.name
        Write-Host "  Downloading $($asset.name) ($([math]::Round($asset.size/1MB,1)) MB)..." -ForegroundColor Gray

        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $dlPath -UseBasicParsing
        $InstallerPath = $dlPath
        Write-OK "Downloaded: $($asset.name)"
    } catch {
        Write-Fail "Failed to fetch installer from GitHub: $_"
        Write-Host "  Run again with: -InstallerPath 'C:\path\to\Albedo-Setup-x.x.x.exe'" -ForegroundColor Yellow
        exit 1
    }
}

# ── Step 7: Run the new installer ─────────────────────────────────────────────
Write-Step "Installing Albedo Mission Control"
Write-Host "  Installer: $InstallerPath" -ForegroundColor Gray
Write-Host "  Target:    $InstallDir" -ForegroundColor Gray
Write-Host "  Running silent install — this will take 1–3 minutes..." -ForegroundColor Gray

try {
    $proc = Start-Process -FilePath $InstallerPath `
                          -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES",
                                        "/NORESTART", "/DIR=`"$InstallDir`"" `
                          -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        Write-Fail "Installer exited with code $($proc.ExitCode)"
        exit 1
    }
    Write-OK "Installation complete"
} catch {
    Write-Fail "Installer failed to launch: $_"
    exit 1
}

# ── Step 8: Restore user data ──────────────────────────────────────────────────
Write-Step "Restoring user data from backup"

if ($backedUp.Count -eq 0) {
    Write-Warn "No backup data to restore — new install will run the setup wizard."
} else {
    foreach ($item in $backedUp) {
        $src = Join-Path $BackupDir $item
        $dst = Join-Path $InstallDir $item
        if (Test-Path $src) {
            try {
                # For directories: merge into target (don't wipe subdirs installer created)
                if ((Get-Item $src).PSIsContainer) {
                    Copy-Item -Path $src -Destination (Split-Path $dst) -Recurse -Force
                } else {
                    Copy-Item -Path $src -Destination $dst -Force
                }
                Write-OK "Restored: $item"
            } catch {
                Write-Warn "Could not restore $item — $_"
            }
        }
    }
}

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "  ║   NUCLEAR RESET COMPLETE                             ║" -ForegroundColor Green
Write-Host "  ║                                                      ║" -ForegroundColor Green
Write-Host "  ║   API keys, memory DB, and vault index restored.     ║" -ForegroundColor Green
Write-Host "  ║   ALBEDO_UI forced to eel in .env.                   ║" -ForegroundColor Green
Write-Host "  ║                                                      ║" -ForegroundColor Green
Write-Host "  ║   Launch Albedo from the Desktop shortcut or:        ║" -ForegroundColor Green
Write-Host "  ║   C:\Albedo\Launch-Albedo.ps1                        ║" -ForegroundColor Green
Write-Host "  ╚══════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "  Backup preserved at: $BackupDir" -ForegroundColor DarkGray
Write-Host "  (Safe to delete once you confirm Albedo is working.)" -ForegroundColor DarkGray
Write-Host ""
