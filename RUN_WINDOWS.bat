@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment belum ada. Jalankan instalasi dari README terlebih dahulu.
  pause
  exit /b 1
)
start "" http://127.0.0.1:8080/
".venv\Scripts\python.exe" nicegui_app.py
pause
