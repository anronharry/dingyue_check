#!/bin/bash
# 快速启动脚本 - Linux / macOS / 云服务器

set -e  # 遇错立即退出

echo "========================================"
echo " Telegram 机场订阅管理机器人"
echo "========================================"
echo ""

# ---- 1. Python 版本检查 ----
if ! command -v python3 &>/dev/null; then
    echo "❌ 未找到 python3，请先安装 Python 3.10+"
    echo "💡 提示: 在 Debian/Ubuntu 上可执行: apt update && apt install -y python3 python3-venv python3-pip"
    echo "💡 提示: 在 CentOS/RHEL 上可执行: yum install -y python3"
    exit 1
fi
echo "✅ Python: $(python3 --version)"

# ---- 2. 虚拟环境 ----
if [ ! -d ".venv" ]; then
    echo "⚙️  创建虚拟环境..."
    python3 -m venv .venv
fi
source .venv/bin/activate
echo "✅ 虚拟环境已激活"

# ---- 3. 检查 .env ----
if [ ! -f ".env" ]; then
    echo ""
    echo "❌ 未找到 .env 配置文件"
    echo "   请执行: cp .env.example .env  然后填入 Bot Token"
    exit 1
fi
echo "✅ 配置文件检测通过"

# ---- 4. 按 SERVER_PROFILE 自动选择依赖套件 ----
# 从 .env 读取配置（忽略注释行）
PROFILE=$(grep -E "^SERVER_PROFILE=" .env | cut -d= -f2 | tr -d '[:space:]')

if [ "$PROFILE" = "1gb" ] || [ "$PROFILE" = "512mb" ] && [ -f "requirements-full.txt" ]; then
    # 仅 512MB / 1GB 档位需要安装可视化图表库
    REQ_FILE="requirements-full.txt"
    echo "📦 档位: ${PROFILE:-1gb}（安装完整依赖 含 matplotlib）"
else
    REQ_FILE="requirements.txt"
    echo "📦 档位: ${PROFILE:-256mb}（安装核心依赖）"
fi

echo "⏳ 安装依赖..."
pip install -q -r "$REQ_FILE"
echo "✅ 依赖安装完成"

# ---- 5. 启动机器人 ----
echo ""
echo "========================================"
echo " 启动机器人..."
echo " 按 Ctrl+C 停止"
echo "========================================"
echo ""

exec python3 bot_async.py
