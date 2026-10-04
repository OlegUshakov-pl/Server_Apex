@echo off
title FastAPI Snapshots Server - Install
setlocal

REM Использование: install.bat [--recreate] [--help]
if "%~1"=="--help" goto :help
if "%~1"=="-h" goto :help
if "%~1"=="/?" goto :help

echo ========================================
echo FastAPI Snapshots Server - Установка
echo ========================================
echo.

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
echo Python OK:
python --version
echo.

REM Пересоздание окружения при флаге --recreate
if "%~1"=="--recreate" (
    if exist venv (
        echo Удаление старого окружения venv...
        rmdir /s /q venv
        if errorlevel 1 (
            echo Ошибка: не удалось удалить папку venv. Закройте процессы, использующие её, и попробуйте снова.
            pause
            exit /b 1
        )
    )
)

REM Создание venv, если его нет
if not exist venv\Scripts\python.exe (
    echo Создание виртуального окружения...
    python -m venv venv
    if errorlevel 1 (
        echo Ошибка: не удалось создать venv.
        pause
        exit /b 1
    )
) else (
    echo Виртуальное окружение уже существует, использую его.
)
echo.

REM Обновление pip и установка зависимостей
echo Обновление pip...
venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 (
    echo Ошибка: не удалось обновить pip.
    pause
    exit /b 1
)
echo.

if exist requirements.txt (
    echo Установка зависимостей из requirements.txt...
    venv\Scripts\python.exe -m pip install -r requirements.txt
) else (
    echo Установка зависимостей из pyproject.toml...
    venv\Scripts\python.exe -m pip install .
)
if errorlevel 1 (
    echo Ошибка: не удалось установить зависимости.
    pause
    exit /b 1
)
echo.

REM Проверка установки
echo Проверка установки...
venv\Scripts\python.exe -c "import sys, fastapi, uvicorn, pydantic; print('Python', sys.version.split()[0]); print('fastapi', fastapi.__version__); print('uvicorn', uvicorn.__version__); print('pydantic', pydantic.__version__)"
if errorlevel 1 (
    echo Ошибка: проверка не пройдена.
    pause
    exit /b 1
)
echo.

echo ========================================
echo Установка завершена успешно.
echo Запуск сервера: start.bat
echo ========================================
pause
exit /b 0

:help
echo Использование: install.bat [--recreate]
echo   без флагов   - создать venv (если нет) и установить зависимости
echo   --recreate   - удалить venv и установить заново
exit /b 0
