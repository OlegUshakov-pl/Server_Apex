@echo off
chcp 65001 >nul
title FastAPI Snapshots Server - Start
cd /d "%~dp0"

REM Check for Python 3.14+
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python not found. Please install Python 3.14+
    pause
    exit /b 1
)
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 14) else 1)" >nul 2>&1
if errorlevel 1 (
    echo Error: Python 3.14+ is required. Current version:
    python --version
    pause
    exit /b 1
)

echo ========================================
echo FastAPI Snapshots Server - Starting
echo ========================================
echo.

REM Check virtual environment (use venv python directly,
REM no dependency on activate or PATH)
if not exist venv\Scripts\python.exe (
    echo Warning: virtual environment not found.
    echo Create it with: install.bat
    pause
    exit /b 1
)

echo.
echo Starting server at http://localhost:8000
echo Status page will open at http://localhost:8000/status
echo Press Ctrl+C to stop the server
echo ========================================
echo.

REM Open the status page in the browser once the server is up
start /min cmd /c "timeout /t 4 /nobreak >nul & start http://localhost:8000/status"

REM Start uvicorn in dev mode
venv\Scripts\python.exe -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

pause
