@echo off
title FastAPI Snapshots Server - Start

REM Проверка наличия Python 3.14+
python --version >nul 2>&1
if errorlevel 1 (
    echo Ошибка: Python не найден. Пожалуйста, установите Python 3.14+
    pause
    exit /b 1
)
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 14) else 1)" >nul 2>&1
if errorlevel 1 (
    echo Ошибка: требуется Python 3.14+. Текущая версия:
    python --version
    pause
    exit /b 1
)

echo ========================================
echo FastAPI Snapshots Server - Запуск
echo ========================================
echo.

REM Активация виртуального окружения (если существует)
if exist venv\Scripts\activate.bat (
    echo Активация виртуального окружения...
    call venv\Scripts\activate.bat
) else (
    echo Предупреждение: Виртуальное окружение не найдено.
    echo Создайте его: python -m venv venv ^&^& venv\Scripts\python -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo.
echo Запуск сервера на http://localhost:8000
echo Нажмите Ctrl+C для остановки сервера
echo ========================================
echo.

REM Запуск uvicorn с параметрами разработки
uvicorn main:app --reload --host 0.0.0.0 --port 8000

pause
