# 🤖 Gipson_check (订阅管理机器人 Pro)

> 自动解析机场订阅链接，提供流量监控、深度节点测活、格式转换、可视化报告、定时告警等功能。  
> **极度优化**：针对 1GB RAM VPS 深度适配，集成了内核自愈、自动清理与显式 GC 机制。

---

## ✨ 功能一览

| 功能 | 说明 |
|------|------|
| 📥 订阅解析 | 支持 Base64 编码节点列表 / Clash YAML 格式，自动检测虚假响应与节点流量 |
| 🛡️ 权限分级 | **超级所有者 (Owner)** 模式：动态管理授权名单，保护敏感操作 |
| ⚡ 深度测活 | 集成 Mihomo (ClashMeta) 内核，实现**真实外网连通性**延迟检测 (DeepCheck) |
| 🔄 格式转换 | 智能批量转换：支持 TXT ↔ Clash YAML，生成包含**专业分流规则与代理组**的即用型配置 |
| 🔔 鲁棒监控 | 每日 **12:00/20:00 UTC** 自动巡检，支持流量告警、到期推送及**磁盘自动清理** |
| 📊 统计汇总 | 全局数据概览，实时统计总流量、剩余比例及节点存活统计 |

---

## 🚀 傻瓜式新手安装指南

本指南旨在帮助**完全没有编程经验**的新手在 Linux 服务器（如 Ubuntu/Debian）上成功运行机器人。

### 第一步：准备必要信息 (ID 与 Token)
在开始之前，你需要在 Telegram 上获取两个核心参数：
1. **获取 Bot Token**：
   - 在 TG 中搜索 [@BotFather](https://t.me/BotFather)，发送 `/newbot`。
   - 按照提示输入机器人名称。
   - 成功后你会收到一段代码，例如 `12345678:ABCDefgh...`，这就是 **Token**。
2. **获取你的用户 ID (OWNER_ID)**：
   - 搜索 [@userinfobot](https://t.me/userinfobot)，发送任意消息。
   - 它会返回一串数字（如 `987654321`），这就是你的 **ID**。

---

### 第二步：一键环境部署
连接你的服务器（使用 SSH 工具，如 Termius 或 PuTTY），复制并粘贴以下命令：

```bash
# 1. 更新服务器环境
sudo apt update && sudo apt install -y git python3 python3-pip python3-venv

# 2. 克隆项目代码
git clone https://github.com/anronharry/dingyue_check.git
cd dingyue_check

# 3. 创建虚拟环境 (隔离环境，防止冲突)
python3 -m venv venv
source venv/bin/activate

# 4. 安装必备依赖
pip install --upgrade pip
pip install -r requirements.txt
```

---

### 第三步：配置机器人
你需要告诉机器人你的 Token 和 ID：

1. **创建配置文件**：
   ```bash
   cp .env.example .env
   ```
2. **编辑配置文件**：
   使用内置编辑器打开它：
   ```bash
   nano .env
   ```
   在打开的界面中修改以下两行：
   - `TELEGRAM_BOT_TOKEN=你的Token`（把刚才获取的 Token 填进去）
   - `OWNER_ID=你的ID`（把刚才获取的 ID 填进去）
   - *提示：按 `Ctrl+O` 保存，按 `Enter` 确认，按 `Ctrl+X` 退出。*

---

### 第四步：启动机器人

**Linux / macOS（推荐使用一键脚本）：**
```bash
bash start.sh
```

**Windows：**
```bat
start.bat
```

**或手动后台常驻运行（Linux）：**
```bash
# 后台常驻运行 (推荐)
nohup python3 bot_async.py > bot.log 2>&1 &

# 如果你想直接看实时日志（按 Ctrl+C 退出日志查看，不影响程序运行）：
tail -f bot.log
```

---

## 🤖 Bot 命令手册

### 👑 管理员专属 (仅 Owner 可用)
- `/adduser <ID>` - 授权其他用户使用你的机器人。
- `/deluser <ID>` - 移除某个用户的授权。
- `/listusers` - 查看当前有多少人被你授权了。
- `/import` / `/export` - 备份与恢复订阅数据库。
- `/broadcast <内容>` - 向所有授权用户发送系统公告。

### 👥 基础功能 (Owner 及授权用户)
- `/check` - 手动触发一次全量检测。
- `/list` - 以卡片形式查看所有订阅及流量状态。
- `/stats` - 查看全局统计（订阅总数、流量汇总）及系统资源占用（Owner 专属）。
- `/deepcheck` - **回复一个 TXT/YAML 文件使用**。进行真实的节点网络连接测试。
- `/to_yaml` / `/to_txt` - **回复一个文件使用**。实现配置格式互相转换。

---

## 🛡️ 鲁棒性与安全性防护
- **内核自愈**：启动测速前自动校验二进制完整性，防止残留损坏。
- **内存防护**：强制限制上传文件最大 **5MB**，防止特大 Payload 导致 OOM。
- **自动清理**：定时任务会自动删除 24 小时前的临时测速缓存，防止磁盘写满。
- **并发控制**：所有网络操作均通过 `Semaphore` 控制并发量，确保 1GB VPS 稳定。

---

## ❓ 常见问题 (FAQ)
1. **机器人没反应？**：请检查 `.env` 中的 Token 是否正确，且服务器是否可以访问 Telegram API（部分境内服务器需挂代理）。
2. **深检(DeepCheck)下载内核失败？**：由于内核在 GitHub 存储，请确保服务器网络畅通，或手动将 `mihomo` 放置在 `bin/` 目录下。
3. **如何更新代码？**：
   ```bash
   git pull
   pip install -r requirements.txt
   ```
