# post_upgrade.ps1 — called by the installer during an in-place upgrade
# Runs setup_utility.py --upgrade to refresh pip deps only (no wizard).
# Also patches any stale .env values that must change between versions.
param([string]$AppDir)

Set-Location $AppDir

# ── .env migration patches ────────────────────────────────────────────────
# v2.0.0 → v2.0.1: ALBEDO_UI defaulted to "tk"; force it to "eel" so
# existing installs get the Cyberdeck UI without a full reinstall.
$envFile = Join-Path $AppDir ".env"
if (Test-Path $envFile) {
    $content = Get-Content $envFile -Raw
    if ($content -match 'ALBEDO_UI\s*=\s*tk') {
        $content = $content -replace '(?m)^ALBEDO_UI\s*=\s*tk\s*$', 'ALBEDO_UI=eel'
        Set-Content $envFile $content -Encoding UTF8 -NoNewline
        Write-Host "  [OK] Patched ALBEDO_UI=tk -> ALBEDO_UI=eel in .env" -ForegroundColor Green
    }
}

# ── Refresh pip dependencies ───────────────────────────────────────────────
try {
    & pyw.exe -3.12 "$AppDir\setup_utility.py" --upgrade
} catch {
    try {
        & py.exe -3.12 "$AppDir\setup_utility.py" --upgrade
    } catch {
        # Non-fatal on upgrade — app still works with existing .venv
    }
}
