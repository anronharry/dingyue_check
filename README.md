# Telegram Subscription Bot

一个适合部署在云服务器上的 Telegram 订阅检测与转换机器人。  
核心目标是把「订阅可用性检查、流量到期查看、节点文件转换、缓存导出、基础运维」统一在 TG 内完成。

## 1. 功能概览

- 检测订阅链接并显示流量、到期时间、节点数量
- 支持 `TXT` / `YAML` 节点文件分析与互转
- 支持导出缓存（48 小时有效）
- 支持节点快速连通性检查
- 支持 Owner 管理功能：授权、审计、广播、全局巡检
- 支持 `/backup` 与 `/restore` 进行状态迁移
- 内置测试用例，支持 `pytest`

## 2. 环境要求

- Linux 云服务器（推荐 Ubuntu 22.04+）
- Python 3.10+
- Git
- 一个 Telegram Bot Token（来自 `@BotFather`）
- Owner 的 Telegram 用户 ID（可通过 `@userinfobot` 获取）

## 3. 首次部署（云服务器）

### 3.1 克隆项目

```bash
git clone https://github.com/anronharry/dingyue_check.git
cd dingyue_check
```

### 3.2 配置环境变量

```bash
cp .env.example .env
```

至少填写：

```env
TELEGRAM_BOT_TOKEN=你的Token
OWNER_ID=你的Telegram数字ID
APP_RUN_MODE=legacy_polling
ENABLE_WEB_ADMIN=false
WEB_ADMIN_HOST=127.0.0.1
WEB_ADMIN_PORT=8080
WEB_ADMIN_TOKEN=请设置一个高强度随机字符串
WEB_ADMIN_PUBLIC_URL=http://127.0.0.1:8080/admin
WEB_ADMIN_USERNAME=admin
WEB_ADMIN_SESSION_TTL_SECONDS=28800
WEB_ADMIN_ALLOW_HEADER_TOKEN=false
WEB_ADMIN_COOKIE_SECURE=true
WEB_ADMIN_TRUST_PROXY=false
WEB_ADMIN_LOGIN_WINDOW_SECONDS=600
WEB_ADMIN_LOGIN_MAX_ATTEMPTS=10
WEB_ADMIN_REDIS_URL=
```

说明：
- `WEB_ADMIN_TOKEN` 作为登录口令使用，不要设置弱口令。
- `WEB_ADMIN_USERNAME` 默认为 `admin`，建议在生产环境改名。
- `WEB_ADMIN_ALLOW_HEADER_TOKEN=false` 为默认更安全配置（仅网页登录）；若有脚本访问需求再设为 `true`。
- `WEB_ADMIN_COOKIE_SECURE=true` 为默认更安全配置（仅 HTTPS 发送 Cookie）；仅在纯 HTTP 临时环境下再手动设为 `false`。
- `WEB_ADMIN_TRUST_PROXY=true` 时会使用 `X-Forwarded-For` 作为限流来源 IP（仅在可信反向代理后开启）。
- `WEB_ADMIN_LOGIN_WINDOW_SECONDS` + `WEB_ADMIN_LOGIN_MAX_ATTEMPTS` 控制登录限流窗口与次数。
- `WEB_ADMIN_REDIS_URL` 配置后将使用 Redis 保存会话与登录限流状态（多实例/重启更稳）；留空则使用内存后端。
- 启动时会输出 Web 安全姿态告警（例如 `cookie_secure` 与 `http://` 地址冲突）。
- `GET /healthz` 会返回当前 Web 安全关键配置，便于巡检。

### 3.3 启动（推荐用脚本）

```bash
chmod +x start.sh
bash start.sh
```

`start.sh` 会自动检查 Python、创建虚拟环境、安装依赖并启动。

## 4. 云服务器更新（重点）

项目提供了自动更新脚本：`update_bot.sh`。

### 4.1 一键更新命令

```bash
cd /你的项目目录/dingyue_check
chmod +x update_bot.sh
bash update_bot.sh
```

### 4.2 `update_bot.sh` 会做什么

脚本按顺序执行：

1. 进入项目目录
2. 激活 `venv` 或 `.venv`（如果存在）
3. 检查 `.env` 是否存在，并读取 Web 相关关键配置
4. 停止旧进程（匹配 `python3 main.py`）
5. `git pull --ff-only` 拉最新代码
6. 安装依赖：`pip install -r requirements.txt`（失败会中断，不再吞错误）
7. 编译检查：`python3 -m compileall app core handlers renderers services shared tests web bot_async.py main.py`
8. 跑测试：优先 `pytest -q`，若环境未安装 pytest 则自动回退 `unittest discover`
9. Web 配置预检查与告警：
   - `ENABLE_WEB_ADMIN=true` 但 `APP_RUN_MODE!=unified_async` 会告警
   - 配置 `WEB_ADMIN_REDIS_URL` 但缺少 `redis.asyncio` 依赖会告警（运行时回退内存后端）
10. 后台重启：`nohup python3 main.py > bot.log 2>&1 &`
11. 输出最近日志并做关键词告警扫描

### 4.3 更新后如何确认成功

```bash
ps -ef | grep "python3 main.py" | grep -v grep
tail -n 100 bot.log
```

如果看到进程在、日志没有持续报错，通常表示更新成功。

### 4.4 常见问题排查

- `Permission denied`：先执行 `chmod +x update_bot.sh`
- `fatal: could not read Username`：服务器未配置 GitHub 凭据（PAT 或 SSH Key）
- 测试失败导致中断：先本地修复后再部署
- `ENABLE_WEB_ADMIN=true` 但 Web 没启动：检查 `.env` 是否设置 `APP_RUN_MODE=unified_async`
- 配置了 `WEB_ADMIN_REDIS_URL` 但 healthz 显示 `auth_backend=memory`：确认已安装 `redis` 包且 Redis 地址可达
- 启动失败：查看 `bot.log` 最后一百行

## 5. 推荐生产部署方式（systemd）

如果你长期运行在云端，建议改用 `systemd` 托管，而不是纯 `nohup`。

示例服务文件 `/etc/systemd/system/dingyue-bot.service`：

```ini
[Unit]
Description=Telegram Subscription Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/dingyue_check
ExecStart=/opt/dingyue_check/.venv/bin/python /opt/dingyue_check/main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

启用与启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable dingyue-bot
sudo systemctl start dingyue-bot
sudo systemctl status dingyue-bot
```

查看日志：

```bash
sudo journalctl -u dingyue-bot -f
```

> 如果你采用 `systemd`，建议把 `update_bot.sh` 调整为“只更新代码与依赖，不再 `nohup` 启动”，然后改为 `systemctl restart dingyue-bot`。

### 5.1 Web 控制台与端口开放（手机访问）

1. 启用统一事件循环模式并开启 Web：
```env
APP_RUN_MODE=unified_async
ENABLE_WEB_ADMIN=true
WEB_ADMIN_HOST=0.0.0.0
WEB_ADMIN_PORT=8080
WEB_ADMIN_PUBLIC_URL=http://<你的服务器公网IP>:8080/admin
```
2. 云服务器安全组放行 `WEB_ADMIN_PORT`（例如 8080/TCP），来源建议限制为你的管理 IP 段。
3. 服务器防火墙放行端口（Ubuntu `ufw` 示例）：
```bash
sudo ufw allow 8080/tcp
sudo ufw status
```
4. 手机浏览器访问 `WEB_ADMIN_PUBLIC_URL`，输入 `WEB_ADMIN_USERNAME + WEB_ADMIN_TOKEN` 登录。
5. 生产建议：
   - 优先走 Nginx/Caddy 反代并启用 HTTPS。
   - 将后台入口再加一层 IP 白名单。
   - HTTPS 部署时设置 `WEB_ADMIN_COOKIE_SECURE=true`。
   - 使用反代（Nginx/Caddy）时再设置 `WEB_ADMIN_TRUST_PROXY=true`。
   - 若不需要脚本访问 API，设置 `WEB_ADMIN_ALLOW_HEADER_TOKEN=false`。

## 6. 常用命令

### 普通用户

- `/start`：欢迎信息
- `/help`：帮助信息
- `/check`：检测自己的订阅
- `/check <tag>`：按标签检测
- `/list`：查看订阅列表
- `/stats`：查看统计
- `/delete`：删除订阅
- `/to_yaml`：TXT 转 YAML
- `/to_txt`：YAML 转 TXT

### Owner

- `/adduser <id>`：授权用户
- `/deluser <id>`：取消授权
- `/listusers`：授权列表
- `/allowall` / `/denyall`：全员模式开关
- `/ownerpanel`：已迁移到 Web（返回迁移提示）
- `/usageaudit`：已迁移到 Web（返回迁移提示）
- `/recentusers`：已迁移到 Web（返回迁移提示）
- `/recentexports`：已迁移到 Web（返回迁移提示）
- `/globallist`：已迁移到 Web（返回迁移提示）
- `/checkall`：全局巡检
- `/broadcast <content>`：广播通知
- `/export` / `/import`：导入导出订阅数据
- `/backup` / `/restore`：备份恢复

## 7. 测试与质量检查

```bash
pytest -q
python -m compileall app core handlers renderers services shared tests
```

## 8. 项目结构

```text
app/         应用装配与运行时
core/        解析、存储、文件处理等核心能力
handlers/    Telegram 命令、消息、回调入口
renderers/   文本格式化与按钮构建
services/    业务服务层（审计、备份、缓存等）
shared/      公共工具
tests/       自动化测试
scripts/     辅助脚本
```

## 9. 安全建议

- 不要提交 `.env`、`data/`、日志、缓存文件
- 不要在 Issue 中贴 Token、订阅原始链接、带敏感参数的导出文件
- 生产环境建议开启最小权限与防火墙策略
- 建议定期执行 `/backup` 并异地保存

## 10. 贡献与开源规范

- 贡献指南：[CONTRIBUTING.md](CONTRIBUTING.md)
- 安全策略：[SECURITY.md](SECURITY.md)

## 11. Recent UX & Admin Updates

- Web admin is now available with a lightweight `aiohttp` server and native static page.
- Web admin now includes a dedicated login page (`/admin/login`) and cookie session auth.
- New startup mode switch:
  - `APP_RUN_MODE=legacy_polling` (default, old behavior)
  - `APP_RUN_MODE=unified_async` (Bot + Web in one event loop)
- Web admin API supports cookie session, and can optionally accept `X-Admin-Token` when `WEB_ADMIN_ALLOW_HEADER_TOKEN=true`:
  - `/api/v1/system/overview`
  - `/api/v1/users/recent`
  - `/api/v1/exports/recent`
  - `/api/v1/audit/summary`
  - `/api/v1/subscriptions/global`
- Owner read-style commands are soft-deprecated in Telegram and now return a Web migration notice:
  - `/ownerpanel`, `/usageaudit`, `/recentusers`, `/recentexports`, `/globallist`
- Migration notice URL is controlled by `WEB_ADMIN_PUBLIC_URL`.

## 12. License

MIT License，见 [LICENSE](LICENSE)。
