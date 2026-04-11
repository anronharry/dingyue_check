# Web 控制台重构执行指南（修订版）

> 目标：把 Owner 运维型复杂展示从 Telegram 迁移到内置 `aiohttp` Web 控制台，保留 Bot 核心订阅检测能力稳定运行。

## 0. 适用范围与当前基线

本指南适用于当前仓库状态（已存在 owner 面板收敛与兼容开关，但尚未落地 `web/` 服务模块）。

已确认事实：
- 目前入口仍是 `application.run_polling()`（阻塞模式）。
- 当前仍保留 `usageaudit/recentusers/recentexports/globallist` 相关命令与回调链路。
- `services/admin_service.py` 已提供大量结构化 dict 数据，可直接复用给 Web API。
- 项目已依赖 `aiohttp`，无需引入 FastAPI/Flask/Django。

## 1. 设计原则（必须遵守）

1. KISS：只用 `aiohttp.web` + 原生 `HTML/CSS/JS`，不引入前端构建链。
2. 先并行、后切流：先让 Web 与 Bot 同时可用，再逐步下线 Telegram 报表入口。
3. 服务层复用：Web 只消费 runtime/service，不直接耦合 Telegram handlers。
4. 可回滚：每阶段都要有明确回退开关。
5. 不影响 `/check` 主链路：解析/检测功能不在本次重构范围。

## 2. 分阶段实施计划

### Phase A：落地 Web 服务骨架（不动现有 TG 功能）

新增目录：

```text
web/
  __init__.py
  server.py
  static/
    index.html
```

`web/server.py` 最小职责：
- 构建 `aiohttp.web.Application()`。
- 注册静态资源路由（`/admin` 或 `/admin/`）。
- 注册 API 路由（`/api/v1/...`）。
- 增加认证中间件（详见第 3 节）。

验收标准：
- 启动后可访问 `GET /admin`。
- 未认证访问 API 返回 401/403。
- 认证后可拿到 JSON。

回滚方式：
- 通过 `ENABLE_WEB_ADMIN=false` 完全不启动 Web 组件。

### Phase B：对接 Web API（复用 AdminService）

首批 API（建议）：
1. `GET /api/v1/system/overview`
2. `GET /api/v1/users/recent`
3. `GET /api/v1/exports/recent`
4. `GET /api/v1/audit/summary`
5. `GET /api/v1/subscriptions/global`

实现要求：
- 直接复用 `runtime.admin_service` 的已有方法返回 dict。
- Web 层只做参数解析、权限校验、JSON 序列化。
- 不在 handler 层拼接 HTML 文本。

验收标准：
- API 返回结构稳定（字段固定、可预测）。
- 异常路径统一 JSON 错误格式：`{"ok": false, "error": "..."}`。

回滚方式：
- 保留原 TG 命令入口，Web 仅增量上线。

### Phase C：并发运行 Bot + Web（关键）

必须改为单事件循环协同启动，不再只依赖阻塞式 `run_polling()`。

推荐范式（核心顺序）：
1. 构建 `application = build_application(...)`
2. `await application.initialize()`
3. `await application.start()`
4. `await application.updater.start_polling(...)`
5. 启动 aiohttp：
   - `web_app = build_web_app(runtime, settings)`
   - `runner = web.AppRunner(web_app)`
   - `await runner.setup()`
   - `site = web.TCPSite(runner, host, port)`
   - `await site.start()`
6. 阻塞等待退出信号（如 `asyncio.Event().wait()`）
7. 退出时按顺序清理：
   - `await application.updater.stop()`
   - `await application.stop()`
   - `await application.shutdown()`
   - `await runner.cleanup()`

关键更正：
- 不要写 `AppRunner(site)`，正确是 `AppRunner(app)`。

验收标准：
- Bot 收消息正常。
- Web API 同时可访问。
- 关闭进程时无资源泄漏（session/runner 正常关闭）。

回滚方式：
- 保留旧 `run_polling` 路径，通过环境变量切换启动模式：
  - `APP_RUN_MODE=legacy_polling|unified_async`

### Phase D：Telegram 管理报表瘦身（最后做）

目标：把“复杂报表展示”迁移到 Web，TG 只保留简入口与必要运维动作。

执行策略（分两步，避免一次性硬删）：
1. 软下线（推荐先做）
   - `usageaudit/recentusers/recentexports/globallist` 命令回复迁移提示 + Web 链接。
   - `ownerpanel` 保留为跳转入口（简短文案 + Web 地址）。
2. 硬下线（确认稳定后）
   - 再移除对应命令注册、回调分支、渲染函数。

验收标准：
- Owner 在 TG 端仍有明确入口，不会“失联”。
- Web 可覆盖原报表核心场景后，再删除旧逻辑。

回滚方式：
- `ENABLE_OWNER_LEGACY_READ_COMMANDS=true` 可快速恢复旧命令集。

## 3. 安全与配置要求

新增环境变量：
- `ENABLE_WEB_ADMIN=true|false`
- `WEB_ADMIN_HOST=127.0.0.1`
- `WEB_ADMIN_PORT=8080`
- `WEB_ADMIN_TOKEN=<strong-random-token>`

认证建议（轻量优先）：
- 对 `/admin` 与 `/api/v1/*` 统一校验 `X-Admin-Token`。
- token 缺失或不匹配时返回 401。
- 若部署到公网，必须叠加反向代理层鉴权/IP 白名单/HTTPS。

禁止事项：
- 不在前端硬编码 token。
- 不把 token 打印到日志。
- 不将 `handlers/` 作为 Web 的数据访问层。

## 4. 代码改动边界

本次允许修改：
- `bot_async.py`
- `app/bootstrap.py`（如需拆出 async 启动器）
- `app/runtime.py`（注入 Web 所需依赖）
- `handlers/commands/admin.py`（软下线文案/入口收敛）
- `handlers/callbacks/audit_actions.py`（逐步下线复杂回调）
- `renderers/messages/admin_reports.py`（删除不再使用的渲染器）
- 新增 `web/*`

本次禁止修改：
- `core/parser.py`、`core/subscription_manager.py`、`services/subscription_check_service.py` 的核心检测语义。

## 5. 测试与验收清单

每阶段至少执行：
1. 单元测试：`pytest -q`
2. 启动冒烟：Bot 可启动 + Web 可访问
3. 权限测试：未授权访问 Web API 被拒绝
4. 功能测试：
   - TG `/check` 正常
   - TG `/ownerpanel` 能引导到 Web
   - Web 概览/审计/最近活跃数据可加载
5. 稳定性测试：连续运行 15 分钟，无明显异常日志

## 6. 实施顺序（建议执行单）

1. 新建 `web/` 骨架与认证中间件。
2. 增加 `overview` + `recent users` 两个 API 与前端最小页面。
3. 完成统一事件循环并发启动（Bot + Web）。
4. 扩展剩余 API 到可替代 TG 报表。
5. TG 端先软下线旧报表命令。
6. 稳定观察后再硬删除旧回调/渲染逻辑。

## 7. 交付定义（Done）

满足以下条件才算完成：
- Owner 日常运维查看主要在 Web 完成。
- TG 端不再承载复杂报表渲染。
- Bot 核心订阅检测链路行为无回归。
- 启动、关闭、回滚路径清晰且可操作。

---

如果后续要继续演进，可在 Web 层再加分页、筛选、导出按钮，但不改变本指南的核心边界：
“Web 承载展示，Bot 承载交互与执行”。
