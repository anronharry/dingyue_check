#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="bot.log"
START_CMD="python3 main.py"

cd "$PROJECT_DIR"

echo "==> project: $PROJECT_DIR"

if [ -d "venv" ]; then
  echo "==> activating virtualenv: venv"
  # shellcheck disable=SC1091
  source venv/bin/activate
elif [ -d ".venv" ]; then
  echo "==> activating virtualenv: .venv"
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

if [ ! -f ".env" ]; then
  echo "ERROR: .env not found. Please create it from .env.example first."
  exit 1
fi

env_get() {
  local key="$1"
  local value
  value="$(grep -E "^${key}=" .env 2>/dev/null | tail -n 1 | cut -d'=' -f2- || true)"
  # Trim one layer of surrounding quotes if present.
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  echo "$value"
}

ENABLE_WEB_ADMIN="$(env_get ENABLE_WEB_ADMIN)"
APP_RUN_MODE="$(env_get APP_RUN_MODE)"
WEB_ADMIN_REDIS_URL="$(env_get WEB_ADMIN_REDIS_URL)"

echo "==> stopping old process"
PIDS="$(ps -ef | awk '/python3 main\.py/ && !/awk/ {print $2}')"
if [ -n "${PIDS:-}" ]; then
  echo "$PIDS" | xargs -r kill
  sleep 3
fi

REMAINING="$(ps -ef | awk '/python3 main\.py/ && !/awk/ {print $2}')"
if [ -n "${REMAINING:-}" ]; then
  echo "==> force killing remaining process: $REMAINING"
  echo "$REMAINING" | xargs -r kill -9
  sleep 1
fi

echo "==> pulling latest code"
git pull --ff-only

echo "==> syncing dependencies"
pip install -r requirements.txt

echo "==> compile check"
python3 -m compileall app core handlers renderers services shared tests web bot_async.py main.py

echo "==> running tests"
if python3 -c "import pytest" >/dev/null 2>&1; then
  python3 -m pytest -q
else
  echo "==> pytest not installed, fallback to unittest discover"
  python3 -m unittest discover -s tests
fi

if [ "${ENABLE_WEB_ADMIN,,}" = "true" ] && [ "${APP_RUN_MODE,,}" != "unified_async" ]; then
  echo "WARNING: ENABLE_WEB_ADMIN=true but APP_RUN_MODE is not unified_async."
  echo "         Web console will not start unless APP_RUN_MODE=unified_async."
fi

if [ -n "${WEB_ADMIN_REDIS_URL:-}" ]; then
  if ! python3 -c "import redis.asyncio" >/dev/null 2>&1; then
    echo "WARNING: WEB_ADMIN_REDIS_URL is set but redis package is unavailable."
    echo "         Runtime will fallback to in-memory auth backend."
  fi
fi

echo "==> starting bot"
nohup $START_CMD > "$LOG_FILE" 2>&1 &
sleep 3

NEW_PID="$(ps -ef | awk '/python3 main\.py/ && !/awk/ {print $2}' | head -n 1)"
if [ -z "${NEW_PID:-}" ]; then
  echo "ERROR: bot failed to start"
  tail -n 100 "$LOG_FILE" || true
  exit 1
fi

echo "==> bot started, pid: $NEW_PID"
echo "==> recent log"
tail -n 50 "$LOG_FILE" || true

if grep -Ei "traceback|error|exception|fatal" "$LOG_FILE" >/dev/null 2>&1; then
  echo "==> warning: suspicious log lines detected"
  grep -Ein "traceback|error|exception|fatal" "$LOG_FILE" | tail -n 20 || true
else
  echo "==> startup log looks clean"
fi
