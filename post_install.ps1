# post_install.ps1 — called by the installer after fresh install
# Launches setup_utility.py using the Python 3.12 launcher.
# Falls back from pyw.exe (windowless) to py.exe (console) to a message box.
param([string]$AppDir)

Set-Location $AppDir

try {
    & pyw.exe -3.12 "$AppDir\setup_utility.py"
} catch {
    try {
        & py.exe -3.12 "$AppDir\setup_utility.py"
    } catch {
        $null = [System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms")
        [System.Windows.Forms.MessageBox]::Show(
            "Python 3.12 launcher not found. Install Python 3.12 from python.org (tick Add to PATH), then run setup_utility.py manually to finish Albedo setup.",
            "Albedo Setup - Action Required"
        )
    }
}
