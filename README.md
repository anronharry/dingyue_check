# dingyue-check

[![CI](https://github.com/anronharry/dingyue_check/actions/workflows/ci.yml/badge.svg)](https://github.com/anronharry/dingyue_check/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/anronharry/dingyue_check)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)

`dingyue-check` 是一个自托管 Telegram 订阅检查与节点转换工具，包含可选 Web Admin，用于管理用户、订阅、审计、导出和 Owner 聚合订阅。

## Features

- 检查订阅链接，展示流量、到期时间和节点数量。
- 解析并转换 `TXT` / `YAML` 节点文件。
- 执行节点连通性检查和 Owner 全局巡检。
- 管理授权用户、审计记录、广播通知、备份与恢复。
- 提供可选 Web Admin 和 Owner 聚合订阅入口。

## Quick Start

准备：Python 3.10-3.12、Git、Telegram Bot Token、Owner 的 Telegram 数字用户 ID。

```bash
git clone https://github.com/anronharry/dingyue_check.git
cd dingyue_check
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Windows PowerShell 使用：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 `.env`，至少填写：

```env
TELEGRAM_BOT_TOKEN=你的Token
OWNER_ID=你的Telegram数字ID
```

启动：

```bash
python main.py
```

也可以运行 `bash start.sh`，脚本会创建虚拟环境、安装依赖并启动。启动后在 Telegram 中向 Bot 发送 `/start` 或 `/help` 验证。

## Configuration

完整配置以 [.env.example](.env.example) 为准。生产环境不要提交 `.env`，也不要在 Issue 中粘贴真实 Token、订阅链接或导出数据。

| Name | Required | Default | Notes |
| ---- | -------- | ------- | ----- |
| `TELEGRAM_BOT_TOKEN` | Yes | empty | Bot Token，来自 `@BotFather`。 |
| `OWNER_ID` | Yes | `0` | Owner 的 Telegram 数字用户 ID。 |
| `ALLOWED_USER_IDS` | No | empty | 逗号分隔的静态授权用户 ID。 |
| `APP_RUN_MODE` | No | `legacy_polling` | Web Admin 建议使用 `unified_async`。 |
| `ENABLE_WEB_ADMIN` | No | `false` | 是否启用 Web Admin。 |
| `WEB_ADMIN_TOKEN` | Web enabled | empty | Web 登录口令和签名密钥。 |
| `WEB_ADMIN_PUBLIC_URL` | No | empty | Bot 消息中展示的 Web Admin 地址。 |
| `WEB_ADMIN_REDIS_URL` | No | empty | 为空使用内存会话；配置后 Redis 不可用会启动失败。 |

布尔配置只接受 `1/0`、`true/false`、`yes/no`、`on/off`。用户显式配置非法值时会启动失败。

## Web Admin

Web Admin 默认关闭。启用时建议：

```env
APP_RUN_MODE=unified_async
ENABLE_WEB_ADMIN=true
WEB_ADMIN_HOST=127.0.0.1
WEB_ADMIN_PORT=8080
WEB_ADMIN_PUBLIC_URL=https://example.com/admin
WEB_ADMIN_TOKEN=请设置高强度随机字符串
```

不要把 Web Admin 直接公开到公网，除非同时具备 HTTPS、强口令和来源 IP 限制。配置 `WEB_ADMIN_REDIS_URL` 后，Redis 依赖缺失、URL 错误或连接失败会启动失败；只有显式设置 `WEB_ADMIN_REDIS_ALLOW_MEMORY_FALLBACK=true` 才允许回退内存。

## Common Commands

- `/check`：检测自己的订阅。
- `/check <tag>`：按标签检测。
- `/list`：查看订阅列表。
- `/stats`：查看统计。
- `/delete`：删除订阅。
- `/to_yaml`、`/to_txt`：节点文件格式转换。
- `/checkall`、`/broadcast`、`/backup`、`/restore`：Owner 运维命令。

## Deployment

首次部署或小规模自托管可以直接使用：

```bash
chmod +x start.sh
bash start.sh
```

更新已有部署：

```bash
chmod +x update_bot.sh
bash update_bot.sh
```

长期运行建议使用 systemd，`ExecStart` 指向项目虚拟环境里的 `python main.py`。`update_bot.sh` 会执行依赖安装、编译检查、测试、Web 配置预检查并重启进程。

## Development

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements-dev.txt
python -m compileall app core handlers renderers services shared tests web main.py
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

## Troubleshooting

- 启动时报 Token 或 Owner 问题：确认已经复制 `.env.example` 为 `.env`，并填写真实 `TELEGRAM_BOT_TOKEN` 和数字 `OWNER_ID`。
- 配置 Redis 后启动失败：修正 `WEB_ADMIN_REDIS_URL`、安装 Redis 依赖并确认 Redis 可连接。
- JSON 状态文件损坏后启动失败：根据错误里的文件路径修复或从备份恢复，程序不会静默覆盖已有状态。

## Security

不要提交 `.env`、`data/`、日志、缓存文件、真实 Token 或真实订阅链接。安全问题处理方式见 [SECURITY.md](SECURITY.md)。贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## License

MIT License，见 [LICENSE](LICENSE)。
