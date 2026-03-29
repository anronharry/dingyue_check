# Telegram 订阅检测机器人

一个适合部署在 VPS 上的 Telegram 订阅工具机器人。

它可以帮你：

- 检测订阅链接是否有效
- 显示剩余流量、到期时间、节点数量
- 转换 `TXT` 和 `YAML` 节点文件
- 缓存导出结果 48 小时，避免次数限制链接失效
- 提供 Owner 授权、使用审计、备份恢复等管理能力

## 适合什么场景

- 自己日常检测订阅
- 给朋友或小群体共用一个订阅机器人
- 想要一个带缓存导出和备份迁移能力的长期 Bot
- 想在 Telegram 里直接完成节点检测、转换和导入前准备

## 亮点

- 订阅结果先详细展示，约 20 秒后自动精简
- 导出 `YAML` / `TXT` 按钮有即时反馈，不会像“没按到”
- 解析结果缓存 48 小时，适合有访问次数限制的订阅
- Owner 可分页查看最近谁在使用、谁在导出
- 支持 `/backup` 和 `/restore`，迁移服务器更省事

---

## 3 分钟快速部署

### 1. 获取必要信息

你需要：

- `Bot Token`
- 你的 Telegram 数字 ID，也就是 `OWNER_ID`

获取方式：

- `Bot Token`：找 [@BotFather](https://t.me/BotFather) 创建机器人
- `OWNER_ID`：找 [@userinfobot](https://t.me/userinfobot) 发送任意消息

### 2. 克隆项目

```bash
git clone https://github.com/anronharry/dingyue_check.git
cd dingyue_check
```

### 3. 配置 `.env`

```bash
cp .env.example .env
```

至少填写：

```env
TELEGRAM_BOT_TOKEN=你的BotToken
OWNER_ID=你的Telegram数字ID
```

如果你希望一开始就让几个固定用户可用，也可以填：

```env
ALLOWED_USER_IDS=123456789,987654321
```

配置模板见：[.env.example](.env.example)

### 4. 启动

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

---

## 实际使用效果

### 示例 1：用户直接发送订阅链接

```text
用户：
https://example.com/sub?token=abc

机器人：
先返回详细信息：
- 名称
- 剩余流量
- 到期时间
- 节点数量
- 导出按钮

约 20 秒后：
自动精简成短摘要，只保留最关键的信息
```

### 示例 2：用户点击导出 YAML

```text
用户：
点击「导出 YAML」

机器人：
先提示“正在准备 YAML...”
然后发送 YAML 文件
```

### 示例 3：Owner 查看最近谁在使用

```text
Owner：
/ownerpanel

机器人：
显示控制台按钮：
- 使用审计
- 最近活跃用户
- 最近导出记录
- 全局订阅概览
```

---

## 普通用户怎么用

最常用的有 3 种方式：

### 1. 直接发送订阅链接

机器人会自动：

- 检测可用性
- 读取剩余流量
- 读取到期时间
- 统计节点数量
- 缓存导出内容 48 小时

### 2. 上传 `TXT` / `YAML` 文件

机器人会自动判断它是：

- 订阅链接列表
- 还是节点配置文件

然后执行对应处理。

### 3. 直接发送节点文本

例如：

- `vmess://...`
- `ss://...`
- `trojan://...`

机器人会自动分析节点内容。

---

## 命令一览

### 普通用户命令

| 命令 | 作用 |
|---|---|
| `/start` | 开始使用 |
| `/help` | 查看帮助 |
| `/check` | 检查自己的全部订阅 |
| `/check <标签>` | 检查指定标签下的订阅 |
| `/list` | 查看自己的订阅列表 |
| `/stats` | 查看统计信息 |
| `/delete` | 删除订阅 |
| `/to_yaml` | 把 TXT 转成 YAML |
| `/to_txt` | 把 YAML 转成 TXT |
| `/deepcheck` | 深度检测节点 |

### Owner 命令

| 命令 | 作用 |
|---|---|
| `/adduser <ID>` | 授权用户 |
| `/deluser <ID>` | 取消授权 |
| `/listusers` | 查看授权名单 |
| `/allowall` | 开启全员可用 |
| `/denyall` | 关闭全员可用 |
| `/ownerpanel` | 打开 Owner 控制台 |
| `/usageaudit` | 查看使用审计 |
| `/recentusers` | 查看最近活跃用户 |
| `/recentexports` | 查看最近导出记录 |
| `/globallist` | 查看全局订阅概览 |
| `/checkall` | 检查所有用户订阅 |
| `/broadcast <内容>` | 广播通知 |
| `/export` | 导出订阅数据 |
| `/import` | 导入订阅数据 |
| `/backup` | 生成完整备份 |
| `/restore` | 恢复完整备份 |

---

## 为什么这个项目对“有次数限制的订阅”更友好

很多订阅链接只能访问几次，用户当下检测完，如果晚点再去代理工具里导入，链接可能已经失效。

这个项目的处理方式是：

- 检测成功后先缓存结果
- 缓存默认保留 48 小时
- 用户可在缓存期内再次导出 `YAML` / `TXT`
- 用户也可以手动删除缓存

这样用户不需要反复重新请求原始订阅链接。

---

## Owner 功能

Owner 除了正常使用外，还能做这些事：

- 管理授权用户
- 切换全员可用模式
- 查看最近谁在用机器人
- 查看最近谁导出了缓存
- 查看其他用户的全局订阅概览
- 导出备份并恢复到新服务器

如果你经常要看管理信息，建议直接用：

```text
/ownerpanel
```

它是 Owner 的集中入口。

---

## 备份与迁移

如果服务器到期或需要迁移，推荐流程：

1. 在旧服务器使用 `/backup`
2. 保存机器人发出的 ZIP 备份
3. 在新服务器部署同版本项目
4. 启动机器人
5. 使用 `/restore`
6. 上传这个 ZIP 备份

这样可以尽量保留：

- 用户授权信息
- 订阅数据
- 缓存索引
- 其他运行状态

---

## 常见问题

### 1. 机器人没反应

先检查：

- `.env` 里的 `TELEGRAM_BOT_TOKEN` 是否正确
- `OWNER_ID` 是否正确
- 服务器是否能访问 Telegram

### 2. 为什么没有 20 秒后自动精简

常见原因：

- Job Queue 没正常工作
- 消息已经被删除或不可编辑
- 当前路径没有进入自动收缩逻辑

维护者可以看日志里是否出现：

```text
Auto-collapse edit_text failed
```

### 3. 导出按钮点了没反应

优先检查：

- 缓存是否过期
- 是否点得太快，触发了短时间防抖
- 机器人是否有发送文件权限

### 4. 新服务器部署后数据没了

如果你有 `/backup` 导出的 ZIP，就用 `/restore` 恢复。

如果没有备份，只能按全新实例重新开始。

---

## 更新项目

Linux 环境可直接运行：

```bash
chmod +x update_bot.sh
./update_bot.sh
```

这个脚本会自动：

- 拉取最新代码
- 安装依赖
- 执行编译检查
- 运行测试
- 重新启动机器人

脚本位置：[update_bot.sh](update_bot.sh)

---

## 给维护者看的部分

普通使用者可以跳过这一节。

### 项目结构

- [app](app)：应用装配、运行时依赖
- [handlers](handlers)：命令、消息、回调入口
- [services](services)：缓存、审计、备份、转换等业务逻辑
- [renderers](renderers)：消息格式化与键盘
- [core](core)：底层解析、存储、文件处理
- [tests](tests)：测试

### 自检命令

修改代码后，至少执行：

```bash
python -m compileall app core handlers jobs renderers services shared bot_async.py main.py
python -m unittest discover -s tests
```

如果改动涉及应用装配或命令注册，再执行：

```bash
python scripts/smoke_assembly.py
python -m unittest tests.test_smoke_assembly
```

### 依赖文件

项目当前使用一份统一的运行依赖清单：

- [requirements.txt](requirements.txt)

安装和启动时按这份依赖文件执行即可。

### 本地维护文档

如果你是项目拥有者，也可以在本地额外维护一份私有说明文档，例如 `LOCAL_OWNER_GUIDE.md`。

这类文档建议不要提交到 GitHub，只用于记录本地维护、迁移流程和自检要求。
