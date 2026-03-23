# 🤖 Gipson_check

> 一个给授权用户使用的 Telegram 订阅工具机器人。  
> 主要提供 3 类能力：`订阅检测`、`TXT / YAML 转换`、`到期与流量自动预警`。  
> `Owner` 在此基础上额外拥有用户管理和全局查看能力。

---

## ✨ 核心功能

| 功能 | 说明 |
|------|------|
| 📥 订阅检测 | 发送订阅链接即可检测是否可用，并读取剩余流量、到期时间、节点数量 |
| 🔄 格式转换 | 支持 TXT ↔ Clash YAML，适合把节点文本快速转换为可直接导入的配置 |
| 🔔 自动预警 | 定时巡检订阅，提醒即将过期或剩余流量不足的订阅 |
| ⚡ 深度检测 | 可选使用 Mihomo 内核做更深度的节点连通性检测 |
| 🛡️ 权限分级 | Owner 可授权用户使用机器人，并查看全局订阅与链接 |

---

## 🔔 预警规则

- 到期时间在 3 天内时，会触发到期预警
- 剩余流量低于总量的 10%，或绝对值低于 5 GB 时，会触发流量预警
- `/check` 中的“需关注”结果与自动预警使用同一套标准

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
nohup python3 main.py > bot.log 2>&1 &

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
- `/check` - 手动检测我的全部订阅。
- `/list` - 查看我的订阅列表，并可直接重新检测、添加标签或删除。
- `/stats` - 查看我的订阅统计；Owner 额外可看到系统资源占用。
- `/deepcheck` - **回复一个 TXT / YAML 文件使用**。进行更深度的节点连通性检测。
- `/to_yaml` / `/to_txt` - **回复一个文件使用**。实现配置格式互相转换。
- 发送订阅链接 - 自动解析、保存并展示检测结果。
- 上传 TXT / YAML 文件 - 自动识别内容并分析，或配合命令完成格式转换。

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
