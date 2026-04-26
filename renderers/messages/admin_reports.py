"""Admin/report message renderers."""
from __future__ import annotations

import html
from datetime import datetime

from core.models import BatchCheckResult, SubscriptionEntity


def _fmt_expire(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _fmt_remaining(value, *, format_traffic) -> str:
    if value is None:
        return "未知"
    return format_traffic(value)


def render_subscription_check_report(*, batch: BatchCheckResult, format_traffic) -> str:
    lines = [
        "<b>订阅检测结果</b>",
        "",
        f"总计: {batch.total}",
        f"正常: {len(batch.active)}",
        f"需关注: {len(batch.warning)}",
        f"失效: {len(batch.failed)}",
        "--------------------",
    ]
    if batch.warning:
        lines.append("")
        lines.append("<b>需关注订阅</b>")
        for item in batch.warning:
            lines.append(f"<b>{html.escape(item.name)}</b>")
            lines.append(f"剩余: {_fmt_remaining(item.remaining_bytes, format_traffic=format_traffic)} | 到期: {_fmt_expire(item.expire_date)}")
            lines.append(f"<code>{html.escape(item.url)}</code>")
            lines.append("")
    if batch.failed:
        lines.append("<b>失效订阅</b>")
        for item in batch.failed:
            lines.append(f"<b>{html.escape(item.name)}</b>")
            lines.append(f"<code>{html.escape(item.url)}</code>")
            lines.append(f"原因: {html.escape((item.error or '未知')[:120])}")
            lines.append("")
    if not batch.warning and not batch.failed:
        lines.append("")
        lines.append("全部订阅状态正常。")
    lines.append("")
    lines.append("可使用 /list 查看当前剩余订阅。")
    return "\n".join(lines).strip()


def render_checkall_report(*, batch: BatchCheckResult, viewer_uid: int, format_user_identity) -> str:
    others_success = [row for row in batch.success if row.owner_uid != viewer_uid]
    others_failed = [row for row in batch.failed if row.owner_uid != viewer_uid]
    others_total = len(others_success) + len(others_failed)
    lines = [
        "<b>全局检测结果</b>",
        "",
        f"总计: {others_total}",
        f"正常: {len(others_success)}",
        f"失效: {len(others_failed)}",
        "--------------------",
    ]
    if others_success:
        lines.append("")
        lines.append("<b>正常订阅</b>")
        for item in sorted(others_success, key=lambda row: (row.owner_uid or 0, row.name)):
            lines.append(f"<b>{html.escape(item.name)}</b>")
            lines.append(f"用户: {format_user_identity(item.owner_uid or 0)}")
            lines.append(f"<code>{html.escape(item.url)}</code>")
            lines.append("")
    if others_failed:
        lines.append("<b>失效订阅</b>")
        for item in sorted(others_failed, key=lambda row: (row.owner_uid or 0, row.name)):
            lines.append(f"<b>{html.escape(item.name)}</b>")
            lines.append(f"用户: {format_user_identity(item.owner_uid or 0)}")
            lines.append(f"原因: {html.escape((item.error or '未知')[:120])}")
            lines.append("")
    if not others_success and not others_failed:
        lines.append("")
        lines.append("当前没有其他用户的订阅变化。")
    return "\n".join(lines).strip()


def render_global_list(data: dict) -> str:
    rows = data.get("rows", [])
    if not rows:
        return "当前除了管理员外暂无其他用户订阅"
    lines = [
        "<b>全局订阅概览</b>",
        f"用户数: <b>{data.get('total_users', 0)}</b> | 订阅数: <b>{data.get('total_subs', 0)}</b>",
        f"异常订阅: <b>{data.get('expired', 0)}</b> | 有效缓存: <b>{data.get('valid_cache', 0)}</b>",
        "",
    ]
    for row in rows:
        lines.append(f"<b>{row['user_text']}</b> | {row['count']} 条订阅")
        for sub in row.get("subs", []):
            lines.append(
                f"- <b>{html.escape(sub['name'])}</b> | 剩余 {sub['remaining']} | 到期 {html.escape(sub['expire'])} | {sub['cache']}"
            )
        if row.get("hidden_subs", 0):
            lines.append(f"- 其余 {row['hidden_subs']} 条已折叠")
        lines.append("")
    if data.get("hidden_users", 0):
        lines.append(f"- 其余 {data['hidden_users']} 位用户已折叠")
    return "\n".join(lines).strip()


def render_user_list(data: dict) -> str:
    users = data.get("users", [])
    if not users:
        return "当前没有授权用户。"
    lines = [
        "<b>授权用户名单</b>",
        f"公开访问模式: <b>{data.get('public_mode', '关闭')}</b>",
        "",
    ]
    for user in users:
        suffix = " (管理员)" if user.get("is_owner") else ""
        lines.append(f"- {user['identity']}{suffix}")
        lines.append(f"  最后活跃: {user['last_seen']} | 来源: {html.escape(user['source'])}")
    return "\n".join(lines)


def render_usage_audit_summary(data: dict) -> str:
    lines = [
        "<b>使用审计（今日汇总）</b>",
        f"范围: <b>{html.escape(data.get('title', '其他用户'))}</b>",
        f"检查次数: <b>{data.get('check_count', 0)}</b>",
        f"涉及用户: <b>{data.get('user_count', 0)}</b>",
        f"涉及链接: <b>{data.get('url_count', 0)}</b>",
        "",
        f"总览: 其他用户 {data.get('others_total', 0)} | 管理员 {data.get('owner_total', 0)} | 全部 {data.get('all_total', 0)}",
    ]
    top_users = data.get("top_users", [])
    if top_users:
        lines.append("")
        lines.append("<b>Top 用户</b>")
        for idx, row in enumerate(top_users, start=1):
            lines.append(f"{idx}. {row['identity']} | 检查 {row['checks']} 次 | 链接 {row['urls']} 条")
    return "\n".join(lines).strip()


def render_recent_users_summary(data: dict) -> str:
    lines = [
        "<b>最近活跃用户（Top 汇总）</b>",
        f"范围: {data.get('scope_title', '非管理员用户')}",
        f"24小时活跃: <b>{data.get('active_24h', 0)}</b> | 已授权: <b>{data.get('authorized_count', 0)}</b>",
        "",
    ]
    for idx, row in enumerate(data.get("rows", []), start=1):
        lines.append(f"{idx}. {row['identity']} | 最后活跃: {row['last_seen']} | 入口: {html.escape(row['source'])}")
    if not data.get("rows"):
        lines.append("暂无最近活跃用户记录。")
    return "\n".join(lines).strip()


def render_recent_exports_summary(data: dict) -> str:
    lines = [
        "<b>最近导出记录（Top 汇总）</b>",
        f"范围: {data.get('scope_title', '非管理员用户')}",
        f"24小时导出: <b>{data.get('exports_24h', 0)}</b> | YAML {data.get('yaml_count', 0)} | TXT {data.get('txt_count', 0)}",
        "",
    ]
    for idx, row in enumerate(data.get("rows", []), start=1):
        lines.append(
            f"{idx}. {row['identity']} | 时间: {row['ts']} | 格式: {row['fmt']} | 目标: <code>{html.escape(row['target'])}</code>"
        )
    if not data.get("rows"):
        lines.append("暂无最近导出记录。")
    return "\n".join(lines).strip()


def render_owner_panel_text(data: dict, *, total_users: int, daily_users: int) -> str:
    lines = [
        "<b>管理员控制台</b>",
        f"订阅总数: <b>{data.get('total_subs', 0)}</b> | 异常订阅: <b>{data.get('expired_subs', 0)}</b>",
        f"授权用户: <b>{data.get('authorized_users', 0)}</b> | 全员可用: <b>{data.get('public_mode', '关闭')}</b>",
        f"24小时活跃用户: <b>{data.get('active_24h', 0)}</b> | 最近活跃记录: <b>{data.get('recent_profiles', 0)}</b>",
        f"缓存条目: <b>{data.get('cache_total', 0)}</b> | 有效缓存: <b>{data.get('cache_valid', 0)}</b>",
        f"24小时导出: <b>{data.get('exports_24h', 0)}</b> | 最近导出记录: <b>{data.get('recent_exports', 0)}</b>",
        "",
        f"👤 使用用户: <b>{total_users}</b> | 🕒 24 小时内: <b>{daily_users}</b>",
    ]
    return "\n".join(lines)


def render_owner_panel_section_text(section: str, data: dict) -> str:
    if section == "overview":
        return "\n".join(
            [
                "<b>管理员控制台 / 总览</b>",
                f"订阅总数: <b>{data.get('total_subs', 0)}</b>",
                f"异常订阅: <b>{data.get('expired_subs', 0)}</b>",
                f"有效缓存: <b>{data.get('cache_valid', 0)}</b> / {data.get('cache_total', 0)}",
                "",
                "这里集中展示整体运行健康状态。",
            ]
        )
    if section == "users":
        return "\n".join(
            [
                "<b>管理员控制台 / 用户</b>",
                f"授权用户: <b>{data.get('authorized_users', 0)}</b>",
                f"24小时活跃: <b>{data.get('active_24h', 0)}</b>",
                "",
                "这里集中查看活跃用户和授权名单。",
            ]
        )
    if section == "maintenance":
        return "\n".join(
            [
                "<b>管理员控制台 / 维护</b>",
                f"公开访问: <b>{data.get('public_mode', '关闭')}</b>",
                "",
                "低频维护操作已收纳在下方子页面。",
                "需要执行时建议使用命令。",
            ]
        )
    if section == "maint_backup":
        return "\n".join(
            [
                "<b>管理员控制台 / 备份迁移</b>",
                "",
                "常用命令：",
                "<code>/backup</code> 生成完整备份 ZIP",
                "<code>/restore</code> 从 ZIP 恢复完整状态",
                "<code>/export</code> 导出订阅 JSON",
                "<code>/import</code> 导入订阅 JSON",
            ]
        )
    if section == "maint_access":
        return "\n".join(
            [
                "<b>管理员控制台 / 权限开关</b>",
                f"当前公开访问: <b>{data.get('public_mode', '关闭')}</b>",
                "",
                "常用命令：",
                "<code>/adduser &lt;id&gt;</code> 授权用户",
                "<code>/deluser &lt;id&gt;</code> 取消授权",
                "<code>/allowall</code> 开启公开访问",
                "<code>/denyall</code> 恢复授权模式",
            ]
        )
    if section == "maint_ops":
        return "\n".join(
            [
                "<b>管理员控制台 / 维护命令</b>",
                "",
                "常用操作：",
                "<code>/broadcast 内容</code> 广播通知",
                "<code>/checkall</code> 全局检测订阅",
                "<code>/refresh_menu</code> 刷新命令菜单",
                "<code>/ownerpanel</code> 重新打开控制台",
            ]
        )
    return "<b>管理员控制台</b>"
