#!/bin/bash
# 快速启动脚本 - Linux/Mac

echo "================================"
echo "Telegram 订阅解析机器人"
echo "================================"
echo ""

# 检查 Python 版本
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "✓ Python 版本: $python_version"

# 检查虚拟环境
if [ ! -d ".venv" ]; then
    echo "⚠ 未检测到虚拟环境，正在创建..."
    python3 -m venv .venv
    echo "✓ 虚拟环境创建完成"
fi

# 激活虚拟环境
source .venv/bin/activate
echo "✓ 虚拟环境已激活"

# 安装依赖
echo ""
echo "正在检查依赖..."
pip install -q -r requirements.txt
echo "✓ 依赖安装完成"

# 检查配置
if [ ! -f ".env" ]; then
    echo ""
    echo "❌ 未找到 .env 配置文件"
    echo "请复制 .env.example 为 .env 并填入 Bot Token"
    exit 1
fi

echo "✓ 配置文件存在"

# 启动机器人
echo ""
echo "================================"
echo "启动机器人（异步版本）..."
echo "按 Ctrl+C 停止"
echo "================================"
echo ""

python3 bot_async.py
