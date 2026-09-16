@echo off
title FastAPI Snapshots Server - Start

REM Проверка наличия Python
python --version >nul 2>&1
if errorlevel 1 (
    echo Ошибка: Python не найден. Пожалуйста, установите Python 3.8+
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
    echo ПредупЖДЕНИЕ: Виртуальное окружение не найдено.
    echo Установите зависимости через: pip install fastapi uvicorn pydantic
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
