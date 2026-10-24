#!/usr/bin/env bash
# Video Downloader launcher for macOS and Linux. First run sets everything up (needs internet).
cd "$(dirname "$0")" || exit 1

PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1 &&
     "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    PY="$cand"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 or newer is required."
  echo "  macOS:  https://www.python.org/downloads/  (or: brew install python)"
  echo "  Linux:  sudo apt install python3 python3-venv   (Debian/Ubuntu)"
  read -r -p "Press Enter to close." _; exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up (this takes a minute)..."
  "$PY" -m venv .venv || { echo "Could not create a virtual environment (Linux: sudo apt install python3-venv)."; read -r _; exit 1; }
  .venv/bin/python -m pip install -q --upgrade pip
  .venv/bin/python -m pip install -q -r requirements.txt || { echo "Install failed. Check your internet connection."; read -r _; exit 1; }
  # Native window on macOS; Linux uses your browser.
  [ "$(uname)" = "Darwin" ] && .venv/bin/python -m pip install -q pywebview >/dev/null 2>&1
fi

# Sites change often; keep yt-dlp current so downloads keep working.
.venv/bin/python -m pip install -q -U "yt-dlp[default,deno]" >/dev/null 2>&1

exec .venv/bin/python app.py
