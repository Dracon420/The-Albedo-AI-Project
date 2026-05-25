@echo off
:: Albedo-Hard-Uninstall.bat
:: Double-click to run. Self-elevates to Administrator automatically.

:: ── Self-elevation check ──────────────────────────────────────────────────
net session >nul 2>&1
if %errorLevel% == 0 goto :run

echo.
echo  [Albedo Hard Uninstaller]
echo  Requesting administrator privileges...
echo.

powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b

:run
:: ── Run the PowerShell uninstaller ───────────────────────────────────────
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Albedo-Hard-Uninstall.ps1"
echo.
echo  Press any key to close...
pause >nul
