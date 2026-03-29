#!/bin/bash
# Quick start script - Linux / macOS / cloud servers

set -e
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

echo "========================================"
echo " Telegram Subscription Bot"
echo "========================================"
echo ""

if ! command -v python3 &>/dev/null; then
    echo "[X] python3 not found. Please install Python 3.10+."
    exit 1
fi
echo "[OK] Python: $(python3 --version)"

RUN_PYTHON="python3"
if python3 -c "import dotenv, telegram, aiohttp, urllib3" >/dev/null 2>&1; then
    echo "[OK] Current Python already has required dependencies."
else
    if [ ! -d ".venv" ]; then
        echo "[*] Creating virtual environment..."
        python3 -m venv .venv
    fi
    source .venv/bin/activate
    RUN_PYTHON="python3"

    if ! python3 -c "import dotenv, telegram, aiohttp, urllib3" >/dev/null 2>&1; then
        echo "[*] Installing dependencies into .venv..."
        pip install -q -r requirements.txt
    fi

    if ! python3 -c "import dotenv, telegram, aiohttp, urllib3" >/dev/null 2>&1; then
        echo "[X] Dependencies are still unavailable after setup."
        exit 1
    fi
    echo "[OK] Virtual environment ready."
fi

if [ ! -f ".env" ]; then
    echo ""
    echo "[X] .env file not found."
    echo "    Run: cp .env.example .env"
    exit 1
fi
echo "[OK] .env file found."

echo ""
echo "========================================"
echo " Starting bot..."
echo " Press Ctrl+C to stop"
echo "========================================"
echo ""

exec "$RUN_PYTHON" main.py
