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

echo "==> stopping old process"
PIDS=$(ps -ef | awk '/python3 main\.py/ && !/awk/ {print $2}')
if [ -n "${PIDS:-}" ]; then
  echo "$PIDS" | xargs -r kill
  sleep 3
fi

REMAINING=$(ps -ef | awk '/python3 main\.py/ && !/awk/ {print $2}')
if [ -n "${REMAINING:-}" ]; then
  echo "==> force killing remaining process: $REMAINING"
  echo "$REMAINING" | xargs -r kill -9
  sleep 1
fi

echo "==> pulling latest code"
git pull --ff-only

echo "==> syncing dependencies"
pip install -q -r requirements.txt || true

echo "==> compile check"
python3 -m compileall .

echo "==> running tests"
python3 -m unittest discover -s tests

echo "==> starting bot"
nohup $START_CMD > "$LOG_FILE" 2>&1 &
sleep 3

NEW_PID=$(ps -ef | awk '/python3 main\.py/ && !/awk/ {print $2}' | head -n 1)
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
