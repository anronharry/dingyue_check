# Telegram Web Console Refactoring Guide - Phase 2 (Hardening)

## 1. 核心目标 (Core Vision)
将当前的“原型级”架构（基于 JSON 文件和基础访问控制）彻底升级为“生产级”系统。重点在于**数据可靠性、API 安全性以及专业的可观测性**。

---

## 2. 核心架构约束 (Architectural Constraints)
> [!CAUTION]
> **严禁引入重量级前端框架**：必须坚持原生 JS + Vanilla CSS，确保极致的加载速度。
> **严禁在业务逻辑中直接编写 SQL**：必须保持 `Service` 与 `Repository` 层级的分离。
> **严格遵循统一异步原则**：禁止引入任何可能阻塞 `asyncio` 事件循环的同步 IO。

---

## 3. 详细任务说明 (Task Specifications)

### 任务 A: 持久化层蜕变 (SQLite 迁移)
**目标**：废弃 `JsonFileStorage`，全面转向 `SQLite`。
*   **技术要求**：
    *   必须使用 `aiosqlite` 库。
    *   实现 **Repository 模式**：定义统一的接口（如 `ISubscriptionRepository`），将 SQL 语句完全封闭在实现层。
    *   **自动迁移逻辑**：在启动时检查是否存在 `subscriptions.json`，若存在则自动读取并批量插入 SQLite，随后将其重命名为 `.bak`。
*   **验收标准**：
    *   更新单行数据（如 Last Seen）不应触发全量数据库写回。
    *   在 10,000 条记录规模下，关键词搜索延迟应小于 10ms。

### 任务 B: 安全防御墙 (Security Hardening)
**目标**：防止针对 API 的蛮力破解与非授权访问。
*   **技术要求**：
    *   **Rate Limiting**：在 `web/server.py` 引入基于 IP 的限流中间件。
        *   登录接口 (`/api/login`)：强制执行 5 次/10分钟的严格惩罚机制。
        *   普通 API：限流 20 次/秒，防止恶意脚本扫描。
    *   **Session 安全**：实施更严格的 Cookie 属性（SameSite=Lax, HttpOnly=True）。
*   **验收标准**：
    *   使用自动化脚本快速请求，系统能准确返回 429 Too Many Requests 且不影响正常用户请求。

### 任务 C: 深度可观测性 (Observability)
**目标**：让管理员对系统运行状态有“上帝视角”。
*   **技术要求**：
    *   **Metrics API**：新增 `/api/monitor/metrics` 接口。
    *   **指标追踪**：需统计以下数据：
        *   各订阅供应商（Domain）的检查成功率与 p95 延迟。
        *   当前挂载的任务队列（Task Queue）深度。
        *   平均每分钟处理的订阅量。
    *   **前端展示**：在 Dashboard 中增加一个“运行质量”卡片，使用动画进度条或微型趋势图展示。
*   **验收标准**：
    *   数据每 30 秒更新一次，无内存泄漏。

### 任务 D: 极致用户体验 (UX Polish)
**目标**：消除加载时的“跳跃感”，达到旗舰级 App 的交互质感。
*   **技术要求**：
    *   **Skeleton Screens (骨架屏)**：为所有主要卡片（统计、列表、日志）设计对应的 CSS 骨架占位图。在 `fetch` 挂起期间，系统不应显示“加载中”文本，而是显示带有 Shimmer 扫光效果的骨架。
    *   **Micro-interactions**：标签页切换增加横向或收缩式淡入淡出（Opacity + Transform）过渡动画。
    *   **Toast 消息系统**：废弃简单的文本状态栏，实现可堆叠、带图标（Success/Warn/Error）的弹出式消息通知。
*   **验收标准**：
    *   网络延迟下，用户感知到的界面布局稳定，无非预期的跳变。

### 任务 E: 全局资源聚合面板 (Global Node Discovery)
**目标**：作为 Owner，从“多用户孤岛数据”中聚合全局可用资源。
*   **技术要求**：
    *   **跨用户聚合**：扫描所有已授权用户的订阅记录，提取 `ProxyNode` 列表。
    *   **自动清洗**：必须自动过滤 `expire_date` 已过期或剩余流量为 0 的节点。
    *   **去重索引**：基于 `Server + Port + Type` 实现节点去重，并标注“热度”（被多少用户共同引用）。
    *   **Owner 特供**：此面板仅对管理员可见，支持一键导出全局可用节点。
*   **验证标准**：
    *   面板内容仅包含当前有效、可连接的节点资源。

### 任务 F: 生产力效率工具 (Efficiency Engine)
**目标**：让运维操作达到“秒级”吞吐。
*   **技术要求**：
    *   **Command Palette (Ctrl+K)**：仿照 Raycast/Spotlight 实现全局指令面板。支持快捷跳转 Tab、全局搜索 UID、一键触发全量体检、快速导出备份。
    *   **批量操作逻辑**：在所有数据表格前端引入 Checkbox 选择器，支持批量删除用户、批量重测订阅。
    *   **快捷键支持**：如 `j/k` 切换列表、`r` 刷新当前面板、`ESC` 快速关闭 Modal。

### 任务 G: 数据可视化看板 (Usage Insights)
**目标**：将冰冷的数字转化为直观的趋势判断。
*   **技术要求**：
    *   **趋势微图 (Sparklines)**：在 Metrics 卡片中引入轻量级 SVG 趋势图，展示过去 24 小时的检查量、导出量变动。
    *   **性能热图**：展示各订阅商（Domain）的检查成功率阶梯，一眼识别垃圾节点商。
    *   **系统负载动态**：将 CPU/Memory 状态曲线化，而非简单的实时数值。
*   **验收标准**：
    *   图表加载不影响主页面初次渲染性能。

---

## 4. 给后续模型的特别提示 (Special Instructions for Successor Models)
1.  **代码风格**：必须保持严格的中文注释。
2.  **错误处理**：任何 API 失败必须返回统一的 `{"ok": false, "error": "MSG"}` 格式，且前端必须有 Toast 给用户反馈。
3.  **无损修改**：在进行 SQLite 迁移时，不得更改任何现有的 Web 控制台 URL 路由，确保前端无需大规模重写。
