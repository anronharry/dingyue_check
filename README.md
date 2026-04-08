# Telegram Subscription Bot

一个适合部署在 VPS 上的 Telegram 订阅检测与转换机器人。

它的目标很明确：把“检测订阅是否可用、查看剩余流量、转换节点文件、缓存导出结果、做基础管理”这些高频动作，统一放到 Telegram 里完成。

## Features

- 检测订阅链接是否可用，并显示剩余流量、到期时间、节点数量
- 支持 `TXT` / `YAML` 节点文件分析与互转
- 解析结果支持 48 小时缓存导出，适合有访问次数限制的订阅
- 支持节点快速连通性检测
- 支持 Owner 授权、使用审计、最近导出记录、全局订阅概览
- 支持 `/backup` 与 `/restore`，便于迁移服务器
- 内置测试用例，当前可直接运行 `pytest`

## Use Cases

- 个人日常检测订阅是否过期或流量告急
- 小范围共享一个可控的订阅机器人
- 需要把节点文件快速转换为 `YAML` / `TXT`
- 想在 Telegram 内完成“检测、转换、导出、备份”一整套流程

## Quick Start

### 1. Prepare

你至少需要准备两项信息：

- `TELEGRAM_BOT_TOKEN`
- `OWNER_ID`

获取方式：

- `TELEGRAM_BOT_TOKEN`：联系 [@BotFather](https://t.me/BotFather)
- `OWNER_ID`：联系 [@userinfobot](https://t.me/userinfobot)

### 2. Clone

```bash
git clone https://github.com/<your-name>/<your-repo>.git
cd <your-repo>
```

### 3. Configure

复制环境变量模板：

```bash
cp .env.example .env
```

至少填写：

```env
TELEGRAM_BOT_TOKEN=your_bot_token
OWNER_ID=123456789
```

如果你希望一开始就允许部分用户使用，也可以设置：

```env
ALLOWED_USER_IDS=123456789,987654321
```

完整模板见 [.env.example](.env.example)。

### 4. Run

#### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
bash start.sh
```

#### Windows

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -U pip
pip install -r requirements.txt
start.bat
```

启动脚本：

- [start.sh](start.sh)
- [start.bat](start.bat)

## Common Commands

### Regular Users

| Command | Description |
|---|---|
| `/start` | 查看欢迎信息 |
| `/help` | 查看帮助 |
| `/check` | 检测自己的全部订阅 |
| `/check <tag>` | 只检测某个标签下的订阅 |
| `/list` | 查看自己的订阅列表 |
| `/stats` | 查看订阅统计 |
| `/delete` | 删除订阅 |
| `/to_yaml` | 将 TXT 节点列表转换为 YAML |
| `/to_txt` | 将 YAML 转换为 TXT |
| `/deepcheck` | 对节点文件做更深入的检测 |

### Owner

| Command | Description |
|---|---|
| `/adduser <id>` | 授权用户 |
| `/deluser <id>` | 取消授权 |
| `/listusers` | 查看授权名单 |
| `/allowall` | 开启全员可用 |
| `/denyall` | 关闭全员可用 |
| `/ownerpanel` | 打开 Owner 控制台 |
| `/usageaudit` | 查看使用审计 |
| `/recentusers` | 查看最近活跃用户 |
| `/recentexports` | 查看最近导出记录 |
| `/globallist` | 查看全局订阅概览 |
| `/checkall` | 检测所有用户的订阅 |
| `/broadcast <content>` | 广播通知 |
| `/export` | 导出订阅数据 |
| `/import` | 导入订阅数据 |
| `/backup` | 生成完整备份 |
| `/restore` | 从备份恢复 |

## Environment Variables

项目当前主要使用这些环境变量：

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | Telegram Bot Token |
| `OWNER_ID` | Yes | 拥有最高权限的 Telegram 用户 ID |
| `ALLOWED_USER_IDS` | No | 允许使用 Bot 的用户 ID 列表，逗号分隔 |
| `PROXY_PORT` | No | Telegram 或相关请求需要经过代理时使用的端口 |
| `URL_CACHE_MAX_SIZE` | No | URL 回调缓存上限 |
| `URL_CACHE_TTL_SECONDS` | No | URL 回调缓存有效期 |
| `ENABLE_LATENCY_TESTER` | No | 是否开启节点快速检测 |
| `ENABLE_MONITOR` | No | 是否开启定时监控 |
| `ENABLE_GEO_LOOKUP` | No | 是否开启地理位置查询 |

更完整的说明见 [.env.example](.env.example)。

## Testing

直接运行：

```bash
pytest -q
```

当前仓库已经补齐测试入口，默认会从 `tests/` 目录收集用例。

如果你只想做快速检查，也可以运行：

```bash
python -m compileall app core handlers renderers services shared tests
```

## Project Layout

```text
app/         应用装配、运行时依赖、生命周期管理
core/        解析、存储、文件处理、底层能力
handlers/    Telegram 命令、消息和回调入口
renderers/   消息格式化与按钮构建
services/    审计、缓存、备份、转换等业务服务
shared/      共享格式化与工具函数
tests/       自动化测试
scripts/     辅助脚本
```

## Deployment Notes

- 项目默认把运行数据放在 `data/` 下
- `data/`、`.env`、日志和缓存都不应提交到 Git
- 如果你使用云服务器部署，推荐用 `systemd`、`pm2` 或容器方式托管进程
- 如果要迁移服务器，优先使用 `/backup` 和 `/restore`

## Contributing

欢迎提交 Issue 和 Pull Request。

开始之前，建议先看：

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [SECURITY.md](SECURITY.md)

## Security

请不要在公开 Issue 中贴出：

- 真实订阅链接
- Bot Token
- `.env` 内容
- 带敏感参数的导出文件

安全报告流程见 [SECURITY.md](SECURITY.md)。

## Open Source Readiness

这个仓库现在已经具备：

- 清晰的 README
- 可直接执行的测试入口
- 环境变量模板
- 贡献与安全说明

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
