@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing. See README.md for first-time installation.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 -m xsecondbrain.agent_cli start --setup-if-needed
if errorlevel 1 pause
