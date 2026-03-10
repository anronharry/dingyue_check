# 🤖 Telegram 机场订阅管理机器人

> 自动解析机场订阅链接，提供流量监控、节点测速、可视化报告、定时告警等功能。  
> 支持按服务器内存规格灵活裁剪功能，256MB 至 1GB VPS 均可稳定运行。

---

## ✨ 功能一览

| 功能 | 说明 |
|------|------|
| 📥 订阅解析 | 支持 Base64 编码节点列表 / Clash YAML 格式，自动提取流量、到期、机场名 |
| 🌍 IP 地理查询 | 真实 IP 定位节点所在国家、城市、ISP（可选） |
| 📊 可视化报告 | 生成流量甜甜圈图、地区分布图、协议占比饼图（需 matplotlib） |
| ⚡ 节点测速 | TCP 并发测速，输出存活率和延迟 Top 5 |
| 🔔 定时监控 | 每天 12:00 / 20:00 自动巡检，流量告急或即将到期时推送 Telegram 告警 |
| 📁 文件解析 | 直接上传 `.txt` / `.yaml` 文件自动解析节点 |
| 🏷️ 标签管理 | 为订阅打标签、按标签分组查看 |
| 📤 导入导出 | JSON 格式批量备份与恢复所有订阅 |
| 🛡️ 白名单鉴权 | 仅授权用户可使用，未授权请求静默忽略 |

---

## 📁 项目结构

```
dingyue_TG/
├── bot_async.py          # 主入口：命令路由、消息处理、按钮回调
├── config.py             # 功能开关配置（按服务器档位裁剪功能）
├── core/
│   ├── parser.py         # 订阅下载与解析引擎
│   ├── storage_enhanced.py  # JSON 本地持久化（含标签）
│   ├── file_handler.py   # 文件上传解析
│   ├── geo_service.py    # IP 地理位置查询
│   └── node_extractor.py # 从节点配置提取 IP
├── features/
│   ├── visualizer.py     # 可视化图表生成（懒加载）
│   ├── latency_tester.py # TCP 并发测速
│   └── monitor.py        # 后台定时监控与告警
├── utils/
│   ├── utils.py          # 流量格式化、URL 验证等工具函数
│   └── retry_utils.py    # HTTP 请求重试装饰器
├── tests/                # 单元测试（36 个用例）
├── data/                 # 订阅数据（自动创建，不进版本库）
├── .env                  # 本地配置（不进版本库）
├── .env.example          # 配置模板
└── requirements.txt      # 项目依赖
```

---

## 🚀 快速部署

### 0. 环境准备 (非常重要)
在极简的云服务器（如 Debian/Ubuntu 系统）上，可能缺失基础工具，请先执行：
```bash
# 1. 更新软件包列表
apt update

# 2. 安装 Git 和 Python3 基础环境
apt install -y git python3 python3-pip python3-venv
```

*(CentOS/AlmaLinux 用户请使用 `yum install git python3`)*

### 1. 克隆项目
```bash
git clone https://github.com/anronharry/dingyue_check.git
cd dingyue_check
```

### 2. 配置环境变量
```bash
cp .env.example .env
# 编辑 .env，填入 Bot Token 和白名单用户 ID
```

### 3. 配置服务器档位（一次填写，脚本自动处理）

在 `.env` 中加一行：

```env
SERVER_PROFILE=256mb   # 256MB 服务器：仅装核心依赖（推荐）
# SERVER_PROFILE=512mb # 512MB 服务器
# SERVER_PROFILE=1gb   # 1GB 服务器：安装完整依赖含图表库
```

### 4. 启动（脚本自动按档位安装依赖）

**Linux（推荐）**：
```bash
bash start.sh
# 或后台运行：
nohup python3 bot_async.py &
```

**Windows**：
```bat
start.bat
```

---

## ⚙️ 功能开关配置

### 方式一：修改 `config.py`（改代码）

```python
# 取消注释对应行，只保留一行
SERVER_PROFILE = "256mb"   # 极简：关闭图表、测速、GEO查询
# SERVER_PROFILE = "512mb" # 标准：开测速和监控，关图表
# SERVER_PROFILE = "1gb"   # 完整：全部开启（默认）
```

### 方式二：在 `.env` 配置（不改代码，推荐）

```env
SERVER_PROFILE=256mb       # 快速切换档位

# 或精细控制每项：
ENABLE_VISUALIZER=false
ENABLE_LATENCY_TESTER=true
ENABLE_MONITOR=true
ENABLE_GEO_LOOKUP=false
```

### 各档位功能对照

| 功能 | 256MB | 512MB | 1GB |
|------|:-----:|:-----:|:---:|
| 📊 可视化图表 | ❌ | ❌ | ✅ |
| ⚡ 节点测速   | ❌ | ✅ | ✅ |
| 🔔 定时监控   | ✅ | ✅ | ✅ |
| 🌍 真实IP查询 | ❌ | ✅ | ✅ |

---

## 🤖 Bot 命令

| 命令 | 功能 |
|------|------|
| `/start` | 欢迎页 |
| `/help` | 帮助说明 |
| `/list` | 查看所有订阅（按标签分组） |
| `/check` | 批量重新检测所有订阅 |
| `/stats` | 统计汇总（总流量、过期数量） |
| `/export` | 导出所有订阅为 JSON |
| `/import` | 从 JSON 文件批量导入 |
| `/delete` | 删除指定订阅 |
| 直接发链接 | 解析单个或多个订阅链接 |
| 直接发文件 | 解析 `.txt` / `.yaml` 节点文件 |

---

## 🔑 `.env` 必填项

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
ALLOWED_USER_IDS=123456789,987654321
```

> 获取 Bot Token：向 [@BotFather](https://t.me/BotFather) 发送 `/newbot`  
> 获取你的用户 ID：向 [@userinfobot](https://t.me/userinfobot) 发送任意消息

---

## 🧪 开发与测试

```bash
# 运行全部测试
pytest tests/

# 语法检查
python -m py_compile bot_async.py config.py
```
