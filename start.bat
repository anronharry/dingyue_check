@echo off
REM 快速启动脚本 - Windows
chcp 65001 >nul

echo ========================================
echo  Telegram 机场订阅管理机器人
echo ========================================
echo.

REM ---- 1. Python 版本检查 ----
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)
echo [OK] Python: 已找到

REM ---- 2. 虚拟环境 ----
if not exist ".venv" (
    echo [*] 创建虚拟环境...
    python -m venv .venv
)
call .venv\Scripts\activate.bat
echo [OK] 虚拟环境已激活

REM ---- 3. 检查 .env ----
if not exist ".env" (
    echo.
    echo [X] 未找到 .env 配置文件
    echo     请执行: copy .env.example .env  然后填入 Bot Token
    pause
    exit /b 1
)
echo [OK] 配置文件检测通过

REM ---- 4. 按 SERVER_PROFILE 自动选择依赖套件 ----
set REQ_FILE=requirements.txt
set PROFILE_LABEL=256mb（核心依赖）

REM 从 .env 中读取 SERVER_PROFILE
for /f "tokens=2 delims==" %%A in ('findstr /B "SERVER_PROFILE=" .env 2^>nul') do set PROFILE=%%A

if "%PROFILE%"=="1gb" (
    set REQ_FILE=requirements-full.txt
    set PROFILE_LABEL=1gb（完整依赖 含 matplotlib）
)
if "%PROFILE%"=="512mb" (
    set REQ_FILE=requirements-full.txt
    set PROFILE_LABEL=512mb（完整依赖 含 matplotlib）
)

echo [*] 档位: %PROFILE_LABEL%
echo [*] 安装依赖...
pip install -q -r %REQ_FILE%
echo [OK] 依赖安装完成

REM ---- 5. 启动机器人 ----
echo.
echo ========================================
echo  启动机器人...
echo  按 Ctrl+C 停止
echo ========================================
echo.

python bot_async.py
pause
