@echo off
REM Quick start script - Windows
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set RUN_PYTHON=python

echo ========================================
echo  Telegram Subscription Bot
echo ========================================
echo.

REM ---- 1. Python check ----
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Python 3.10+ not found.
    pause
    exit /b 1
)
echo [OK] Python found.

REM ---- 2. Check whether current Python already has required deps ----
python -c "import dotenv, telegram, aiohttp" >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Current Python already has required dependencies.
    goto run_bot
)

REM ---- 3. Virtualenv fallback ----
if not exist ".venv" (
    echo [*] Creating virtual environment...
    python -m venv .venv
)
call .venv\Scripts\activate.bat
set RUN_PYTHON=python
python -c "import dotenv, telegram, aiohttp" >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Installing dependencies into .venv...
    if not exist ".env" (
        set REQ_FILE=requirements.txt
        goto install_deps
    )
    set REQ_FILE=requirements.txt
    for /f "tokens=2 delims==" %%A in ('findstr /B "SERVER_PROFILE=" .env 2^>nul') do set PROFILE=%%A
    if "%PROFILE%"=="1gb" set REQ_FILE=requirements-full.txt
    if "%PROFILE%"=="512mb" set REQ_FILE=requirements-full.txt
    :install_deps
    pip install -q -r %REQ_FILE%
)
python -c "import dotenv, telegram, aiohttp" >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Dependencies are still unavailable after setup.
    pause
    exit /b 1
)
echo [OK] Virtual environment ready.

:run_bot
REM ---- 4. .env check ----
if not exist ".env" (
    echo.
    echo [X] .env file not found.
    echo     Run: copy .env.example .env
    pause
    exit /b 1
)
echo [OK] .env file found.

echo.
echo ========================================
echo  Starting bot...
echo  Press Ctrl+C to stop
echo ========================================
echo.

%RUN_PYTHON% main.py
pause
