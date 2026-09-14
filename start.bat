@echo off
REM PCTS - Production Control and Traceability System
REM One-command launcher for Windows.
cd /d "%~dp0backend"

if not exist ".venv" (
  echo Creating virtual environment...
  python -m venv .venv
)

call .venv\Scripts\activate.bat
echo Installing dependencies (first run only)...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

echo.
echo ========================================================================
echo  Starting PCTS backend on http://127.0.0.1:8000
echo  Open that URL in your browser once the server says it is running.
echo ========================================================================
echo.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
