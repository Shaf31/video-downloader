@echo off
rem Video Downloader launcher for Windows. First run sets everything up (needs internet).
setlocal
cd /d "%~dp0"
title Video Downloader

set "PY="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1 && set "PY=python"

if not defined PY (
  echo Python 3.10 or newer is required.
  choice /m "Install Python 3.12 now with winget"
  if errorlevel 2 (
    start https://www.python.org/downloads/
    echo Install Python ^(tick "Add python.exe to PATH"^), then run this file again.
    pause & exit /b 1
  )
  winget install -e --id Python.Python.3.12 --accept-package-agreements
  echo.
  echo Python installed. Close this window and run this file again.
  pause & exit /b 0
)

if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up ^(this takes a minute^)...
  %PY% -m venv .venv || (echo Could not create a virtual environment. & pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install -q --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || (echo Install failed. Check your internet connection. & pause & exit /b 1)
  rem Native app window via Edge WebView2; if this fails the app opens in your browser.
  ".venv\Scripts\python.exe" -m pip install -q pywebview >nul 2>&1
)

rem Sites change often; keep yt-dlp current so downloads keep working.
".venv\Scripts\python.exe" -m pip install -q -U "yt-dlp[default,deno]" >nul 2>&1

".venv\Scripts\python.exe" app.py
if errorlevel 1 pause
