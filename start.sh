#!/usr/bin/env bash
# PCTS - Production Control and Traceability System
# One-command launcher for macOS/Linux.
set -e
cd "$(dirname "$0")/backend"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate
echo "Installing dependencies (first run only)..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

echo ""
echo "========================================================================"
echo " Starting PCTS backend on http://127.0.0.1:8000"
echo " Open that URL in your browser once the server says it is running."
echo "========================================================================"
echo ""
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
