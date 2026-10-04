@echo off
chcp 65001 >nul
title FastAPI Snapshots Server - Install
cd /d "%~dp0"
setlocal

REM Usage: install.bat [--recreate] [--help]
if "%~1"=="--help" goto :help
if "%~1"=="-h" goto :help
if "%~1"=="/?" goto :help

echo ========================================
echo FastAPI Snapshots Server - Installation
echo ========================================
echo.

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
echo Python OK:
python --version
echo.

REM Recreate the environment with --recreate
if "%~1"=="--recreate" (
    if exist venv (
        echo Removing old venv environment...
        rmdir /s /q venv
        if errorlevel 1 (
            echo Error: could not remove the venv folder. Close any processes using it and try again.
            pause
            exit /b 1
        )
    )
)

REM Create venv if missing
if not exist venv\Scripts\python.exe (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo Error: could not create venv.
        pause
        exit /b 1
    )
) else (
    echo Virtual environment already exists, using it.
)
echo.

REM Upgrade pip and install dependencies
echo Upgrading pip...
venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 (
    echo Error: could not upgrade pip.
    pause
    exit /b 1
)
echo.

if exist requirements.txt (
    echo Installing dependencies from requirements.txt...
    venv\Scripts\python.exe -m pip install -r requirements.txt
) else (
    echo Installing dependencies from pyproject.toml...
    venv\Scripts\python.exe -m pip install .
)
if errorlevel 1 (
    echo Error: could not install dependencies.
    pause
    exit /b 1
)
echo.

REM Verify installation
echo Verifying installation...
venv\Scripts\python.exe -c "import sys, fastapi, uvicorn, pydantic; print('Python', sys.version.split()[0]); print('fastapi', fastapi.__version__); print('uvicorn', uvicorn.__version__); print('pydantic', pydantic.__version__)"
if errorlevel 1 (
    echo Error: verification failed.
    pause
    exit /b 1
)
echo.

echo ========================================
echo Installation completed successfully.
echo Start the server: start.bat
echo ========================================
pause
exit /b 0

:help
echo Usage: install.bat [--recreate]
echo   no flags     - create venv (if missing) and install dependencies
echo   --recreate   - remove venv and reinstall from scratch
exit /b 0
