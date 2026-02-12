# Telegram 机场订阅解析机器人

一个功能完整的 Telegram 机器人，用于解析机场订阅链接，提取节点信息、流量数据和到期时间。

## ✨ 功能特性

- 📊 **订阅解析**：支持 Base64 和 Clash YAML 两种格式
- 🌍 **节点统计**：自动统计节点国家/地区分布（支持 15+ 个国家）
- 🔐 **协议识别**：显示协议分布（SS, VMess, VLess, Trojan 等）
- 💾 **流量信息**：总流量、已用、剩余、使用率
- ⏰ **到期时间**：自动提取订阅到期时间
- 🪟 **Windows 兼容**：完美支持 Windows 系统

## 📦 安装

### 1. 克隆项目
```bash
git clone <your-repo-url>
cd dingyue_TG
```

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 配置 Bot Token
复制 `.env.example` 为 `.env`，填入你的 Telegram Bot Token：
```bash
cp .env.example .env
```

编辑 `.env` 文件：
```
TELEGRAM_BOT_TOKEN=你的机器人Token
```

## 🚀 使用方法

### 启动机器人
```bash
python bot_manual.py
```

### 在 Telegram 中使用
1. 找到你的机器人
2. 发送 `/start` 查看欢迎信息
3. 直接发送订阅链接
4. 等待解析结果

## 📊 输出示例

```
📊 订阅信息解析结果

🏷️ 机场名称: [IPLC
📍 节点数量: 70 个

🌍 节点分布:
├─ 香港: 11 个
├─ 美国: 6 个
├─ 台湾: 4 个
├─ 新加坡: 3 个
├─ 英国: 2 个
├─ 日本: 2 个
... (更多国家/地区)

🔐 协议分布:
├─ SS: 66 个
├─ HTTP: 2 个
└─ VMESS: 2 个

💾 流量信息:
├─ 总流量: 152.11 GB
├─ 已用: 20.96 GB
├─ 剩余: 131.15 GB
└─ 使用率: 13.8%

⏰ 到期时间: 2052-10-28 15:52:41
```

## 🔧 技术实现

### User-Agent 伪装
机器人伪装成 Clash 客户端以获取完整流量信息：
```python
headers = {
    'User-Agent': 'ClashForAndroid/2.5.12'
}
```

### 多格式支持
- **Clash YAML**：使用 PyYAML 解析配置文件
- **Base64 节点列表**：支持 VMess, VLess, SS, SSR, Trojan, Hysteria

### Windows 兼容性
使用手动轮询方式绕过 Windows 上的 asyncio 问题：
```python
# 手动轮询 Telegram API
while True:
    updates = get_updates(offset)
    for update in updates:
        process_update(update)
```

## 📁 项目结构

```
dingyue_TG/
├── bot_manual.py          # 主程序（Windows 兼容版）
├── parser.py              # 订阅解析核心
├── utils.py               # 工具函数
├── requirements.txt       # 依赖列表
├── .env.example          # 配置示例
├── .gitignore            # Git 忽略文件
├── README.md             # 项目说明
└── WINDOWS_FIX.md        # Windows 问题说明
```

## 🛠️ 依赖项

- `python-telegram-bot==20.7` - Telegram Bot API
- `requests==2.31.0` - HTTP 请求
- `python-dotenv==1.0.0` - 环境变量管理
- `PyYAML==6.0.1` - YAML 解析
- `PySocks==1.7.1` - SOCKS 代理支持（可选）

## ⚙️ 配置选项

在 `.env` 文件中可配置：
```
TELEGRAM_BOT_TOKEN=你的机器人Token
PROXY_PORT=7890  # 可选，默认不使用代理
```

## 🐛 常见问题

### Windows 上无法启动？
使用 `bot_manual.py` 而不是 `bot.py`，它使用手动轮询绕过 asyncio 问题。

### 流量信息显示为空？
确保订阅服务商提供流量信息。有些订阅不在响应头中包含流量数据。

### 节点数量为 0？
检查订阅格式。如果是 Clash YAML 格式但解析失败，请提交 issue。

## 📝 已解决的问题

- ✅ Windows asyncio 兼容性
- ✅ 流量信息获取（User-Agent 伪装）
- ✅ Clash YAML 配置解析
- ✅ 节点国家/地区统计
- ✅ 协议分布统计

## 🌟 特色功能

1. **智能格式检测** - 自动识别 Base64 或 YAML 格式
2. **详细统计信息** - 节点分布、协议统计一目了然
3. **完美 Windows 支持** - 无需 WSL 或虚拟机
4. **零配置代理** - 默认直接访问，无需配置代理

## � 海外 NAT 服务器部署指南（Debian/Ubuntu）

针对你的 **Debian 6.1 (海外)** 服务器，这是最快、最稳的部署方法。
因为服务器在海外，**不需要配置代理**，且可以直接使用 `systemd` 守护进程，重启自动运行。

### 1️⃣ 第一步：环境准备
登录服务器（SSH），复制并执行以下命令：

```bash
# 更新系统并安装 Python3 和 Git
apt update && apt install python3 python3-pip python3-venv git -y
```

### 2️⃣ 第二步：获取代码
```bash
# 进入 /opt 目录
cd /opt

# 拉取代码（替换为你的仓库地址）
git clone <你的仓库地址> dingyue_TG

# 进入项目目录
cd dingyue_TG
```

### 3️⃣ 第三步：安装依赖（使用虚拟环境）
```bash
# 创建虚拟环境
python3 -m venv venv

# 激活环境并安装依赖
./venv/bin/pip install -r requirements.txt
```

### 4️⃣ 第四步：配置 Bot Token
创建 `.env` 配置文件：
```bash
# 使用 nano 编辑器创建文件
nano .env
```
**在编辑器中粘贴以下内容（修改为你的 Token）：**
```ini
TELEGRAM_BOT_TOKEN=你的机器人Token
# 海外服务器不需要 PROXY_PORT，直接留空或删除即可
```
*(按 `Ctrl+O` 回车保存，按 `Ctrl+X` 退出)*

### 5️⃣ 第五步：设置后台运行（Systemd）
创建服务文件，让机器人开机自启、崩溃重启：

```bash
cat > /etc/systemd/system/dingyue-bot.service <<EOF
[Unit]
Description=Telegram Subscription Parser Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/dingyue_TG
ExecStart=/opt/dingyue_TG/venv/bin/python /opt/dingyue_TG/bot_manual.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
```

### 6️⃣ 第六步：启动机器人
```bash
# 重载配置
systemctl daemon-reload

# 启动服务
systemctl start dingyue-bot

# 设置开机自启
systemctl enable dingyue-bot

# 查看运行状态（看到绿色 active (running) 即成功）
systemctl status dingyue-bot
```

---

### 🛠️ 常用维护命令

- **查看日志**: `journalctl -u dingyue-bot -f`
- **停止机器人**: `systemctl stop dingyue-bot`
- **重启机器人**: `systemctl restart dingyue-bot`
- **更新代码**:
  ```bash
  cd /opt/dingyue_TG
  git pull
  systemctl restart dingyue-bot
  ```

## 📄 许可证

MIT License
