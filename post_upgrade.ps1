# post_upgrade.ps1 — called by the installer during an in-place upgrade
# Runs setup_utility.py --upgrade to refresh pip deps only (no wizard).
param([string]$AppDir)

Set-Location $AppDir

try {
    & pyw.exe -3.12 "$AppDir\setup_utility.py" --upgrade
} catch {
    try {
        & py.exe -3.12 "$AppDir\setup_utility.py" --upgrade
    } catch {
        # Non-fatal on upgrade — app still works with existing .venv
    }
}
