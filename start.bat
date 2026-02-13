@echo off
REM 快速启动脚本 - Windows

echo ================================
echo Telegram 订阅解析机器人
echo ================================
echo.

REM 检查 Python 版本
python --version
if %errorlevel% neq 0 (
    echo ❌ 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

REM 检查虚拟环境
if not exist ".venv" (
    echo ⚠ 未检测到虚拟环境，正在创建...
    python -m venv .venv
    echo ✓ 虚拟环境创建完成
)

REM 激活虚拟环境
call .venv\Scripts\activate.bat
echo ✓ 虚拟环境已激活

REM 安装依赖
echo.
echo 正在检查依赖...
pip install -q -r requirements.txt
echo ✓ 依赖安装完成

REM 检查配置
if not exist ".env" (
    echo.
    echo ❌ 未找到 .env 配置文件
    echo 请复制 .env.example 为 .env 并填入 Bot Token
    pause
    exit /b 1
)

echo ✓ 配置文件存在

REM 启动机器人
echo.
echo ================================
echo 启动机器人（异步版本）...
echo 按 Ctrl+C 停止
echo ================================
echo.

python bot_async.py

pause
