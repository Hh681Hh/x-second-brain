@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-windows.ps1" %*
if errorlevel 1 (
  echo Installation failed. Read the error above and README.md.
  pause
  exit /b 1
)
pause
