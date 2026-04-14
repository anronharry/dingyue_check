"""Telegram-facing message formatters."""
from __future__ import annotations

import html
from datetime import datetime

from shared.format_helpers import (
    create_progress_bar,
    format_remaining_time,
    format_traffic,
    get_country_flag,
)

MAX_TELEGRAM_TEXT = 3900


def _format_skipped_protocols(quick_check: dict) -> str:
    skipped_protocols = quick_check.get("skipped_protocols") or {}
    if not skipped_protocols:
        return ""
    parts = [f"{html.escape(protocol.upper())} {count}" for protocol, count in sorted(skipped_protocols.items())]
    return "；跳过协议：" + " / ".join(parts)


def _format_quick_check(info: dict, *, compact: bool = False) -> str:
    quick_check = info.get("quick_check") or {}
    if not quick_check:
        return ""

    tested = int(quick_check.get("tested") or 0)
    alive = int(quick_check.get("alive") or 0)
    dead = int(quick_check.get("dead") or 0)
    skipped = int(quick_check.get("skipped") or 0)
    sampled = bool(quick_check.get("sampled"))
    skipped_detail = _format_skipped_protocols(quick_check)

    suffix = "（仅抽样）" if sampled else ""
    if compact:
        summary = f"存活：{alive}/{tested}" if tested else "存活：0/0"
        if skipped:
            summary += f" | 跳过 {skipped}"
        return f"<b>快速检测：</b> {summary}{suffix}{skipped_detail}"

    parts = [f"已测 {tested}", f"存活 {alive}", f"失败 {dead}"]
    if skipped:
        parts.append(f"跳过 {skipped}")
    return f"<b>快速检测：</b> {' | '.join(parts)}{suffix}{skipped_detail}"


def _quick_check_metrics(info: dict) -> dict | None:
    quick_check = info.get("quick_check") or {}
    if not quick_check:
        return None
    tested = int(quick_check.get("tested") or 0)
    alive = int(quick_check.get("alive") or 0)
    dead = int(quick_check.get("dead") or 0)
    skipped = int(quick_check.get("skipped") or 0)
    sampled = bool(quick_check.get("sampled"))
    rate = (alive / tested * 100.0) if tested > 0 else 0.0
    return {
        "tested": tested,
        "alive": alive,
        "dead": dead,
        "skipped": skipped,
        "sampled": sampled,
        "rate": rate,
    }


def _quick_check_badge(metrics: dict) -> str:
    tested = int(metrics.get("tested") or 0)
    rate = float(metrics.get("rate") or 0.0)
    if tested <= 0:
        return "⚪️ 无样本"
    if rate >= 90:
        return "🟢 优秀"
    if rate >= 70:
        return "🟡 良好"
    if rate >= 40:
        return "🟠 偏低"
    return "🔴 较差"


def _format_quick_check_highlight(info: dict) -> list[str]:
    metrics = _quick_check_metrics(info)
    if not metrics:
        return []
    sampled_suffix = "（仅抽样）" if metrics["sampled"] else ""
    badge = _quick_check_badge(metrics)
    return [
        "<b>🚀 快速检测</b>",
        f"<b>结果：</b> {badge} | ✅ <b>{metrics['alive']}/{metrics['tested']}</b> 存活 | ❌ {metrics['dead']} | ⏭ {metrics['skipped']}{sampled_suffix}",
        f"<b>存活率：</b> {create_progress_bar(metrics['rate'], length=10)} {metrics['rate']:.1f}%",
    ]

def _render_latency_top(info: dict) -> list[str]:
    quick_check = info.get("quick_check") or {}
    latency_top = quick_check.get("latency_top") or []
    if not latency_top:
        return []
    lines = ["<b>测速 Top（延迟）</b>"]
    for index, item in enumerate(latency_top[:5], start=1):
        name = html.escape(str(item.get("name") or f"node-{index}"))
        protocol = html.escape(str(item.get("type") or "unknown").upper())
        latency = float(item.get("latency") or 0.0)
        lines.append(f"{index}. [{protocol}] {name} - <code>{latency:.0f}ms</code>")
    return lines


def _build_protocol_summary(info: dict, *, top_n: int = 4) -> str:
    stats = info.get("node_stats") or {}
    protocols = stats.get("protocols") or {}
    if not protocols:
        return ""
    parts = [
        f"{html.escape(str(protocol).upper())} {count}"
        for protocol, count in sorted(protocols.items(), key=lambda item: item[1], reverse=True)[:top_n]
    ]
    return " / ".join(parts)


def _build_country_summary(info: dict, *, top_n: int = 4) -> str:
    stats = info.get("node_stats") or {}
    countries = stats.get("countries") or {}
    if not countries:
        return ""
    parts = [
        f"{get_country_flag(country)}{html.escape(country)} {count}"
        for country, count in sorted(countries.items(), key=lambda item: item[1], reverse=True)[:top_n]
    ]
    return " / ".join(parts)


def _render_node_lines(info: dict, *, max_items: int, char_budget: int) -> tuple[list[str], int]:
    nodes = info.get("_normalized_nodes") or info.get("_raw_nodes") or []
    if not nodes:
        return [], 0

    lines = []
    remaining_budget = char_budget
    for index, node in enumerate(nodes, start=1):
        if len(lines) >= max_items:
            break
        protocol = str(node.get("protocol") or node.get("type") or "unknown").upper()
        name = str(node.get("name") or f"node-{index}")
        line = f"{index}. [{html.escape(protocol)}] {html.escape(name)}"
        if len(line) + 1 > remaining_budget:
            break
        lines.append(line)
        remaining_budget -= len(line) + 1

    hidden_count = max(0, len(nodes) - len(lines))
    return lines, hidden_count


def _status_text(info: dict) -> str:
    expire_time = str(info.get("expire_time") or "").strip()
    if expire_time:
        try:
            if datetime.strptime(expire_time, "%Y-%m-%d %H:%M:%S") < datetime.now():
                return "已过期"
        except Exception:
            pass

    total = info.get("total")
    remaining = info.get("remaining")
    if total is not None and remaining is not None:
        try:
            if float(total) > 0 and float(remaining) <= 0:
                return "流量耗尽"
        except Exception:
            pass

    node_count = int(info.get("node_count") or 0)
    if node_count > 0:
        return "可用"
    parse_notes = set(info.get("_parse_notes") or [])
    if "unrecognized-content" in parse_notes:
        return "无法识别订阅内容"
    return "异常"


def _format_usage(info: dict) -> tuple[str, str, str]:
    used_value = info.get("used") if "used" in info else None
    total_value = info.get("total") if "total" in info else None
    remaining_value = info.get("remaining") if "remaining" in info else None
    used = format_traffic(used_value) if used_value is not None else "未知"
    total = format_traffic(total_value) if total_value is not None else "未知"
    remaining = format_traffic(remaining_value) if remaining_value is not None else "未知"
    return used, total, remaining


def _build_details(info: dict, *, node_limit: int, node_char_budget: int) -> str:
    lines = []
    node_lines, hidden_count = _render_node_lines(info, max_items=node_limit, char_budget=node_char_budget)
    if node_lines:
        lines.append(f"<b>节点列表（共 {info.get('node_count') or len(node_lines)} 个）</b>")
        lines.extend(node_lines)
        if hidden_count:
            lines.append(f"... 其余 {hidden_count} 个节点已折叠")

    quick_check_text = _format_quick_check(info)
    if quick_check_text:
        lines.append(quick_check_text)
    lines.extend(_render_latency_top(info))

    if not lines:
        return ""
    return "<blockquote expandable>\n" + "\n".join(lines) + "\n</blockquote>"


def format_subscription_info(info, url=None):
    """Format subscription details as summary + native Telegram expandable details."""
    used, total, remaining = _format_usage(info)
    expire_time = info.get("expire_time") or "未知"

    header_lines = [f"<b>机场名称：</b> {html.escape(str(info.get('name') or '未知机场'))}"]
    if url:
        header_lines.extend(["<b>订阅链接：</b>", f"<code>{html.escape(url)}</code>"])

    summary_lines = []
    summary_lines.extend(
        [
        f"<b>已用 / 总量：</b> {used} / {total}",
        f"<b>剩余流量：</b> {remaining}",
        f"<b>到期时间：</b> {html.escape(str(expire_time))}",
        ]
    )

    if info.get("usage_percent") is not None:
        percent = float(info["usage_percent"])
        summary_lines.append(f"<b>使用进度：</b> {create_progress_bar(percent, length=8)} {percent:.1f}%")

    summary_lines.extend(_format_quick_check_highlight(info))

    remain_text = format_remaining_time(info.get("expire_time", ""), include_seconds=False) if info.get("expire_time") else ""
    if remain_text:
        summary_lines.append(f"<b>剩余时间：</b> {html.escape(remain_text)}")
    traffic_warning = str(info.get("_traffic_warning") or "").strip()
    if traffic_warning:
        summary_lines.append("<b>提示：</b> 无流量信息")

    summary_block = "<blockquote>\n" + "\n".join(summary_lines) + "\n</blockquote>"
    details = _build_details(info, node_limit=100, node_char_budget=1800)
    message = "\n".join(header_lines) + "\n\n" + summary_block + ("\n\n" + details if details else "")

    if len(message) > MAX_TELEGRAM_TEXT:
        details = _build_details(info, node_limit=40, node_char_budget=1000)
        message = "\n".join(header_lines) + "\n\n" + summary_block + ("\n\n" + details if details else "")
    if len(message) > MAX_TELEGRAM_TEXT:
        details = _build_details(info, node_limit=20, node_char_budget=650)
        message = "\n".join(header_lines) + "\n\n" + summary_block + ("\n\n" + details if details else "")

    return message[:MAX_TELEGRAM_TEXT]


def format_subscription_compact(info, url=None):
    """Keep compact formatter for compatibility in non-primary flows."""
    del url
    lines = []
    if info.get("name"):
        lines.append(f"<b>名称：</b> {html.escape(str(info['name']))}")
    used, total, remaining = _format_usage(info)
    lines.append(f"<b>已用 / 总量：</b> {used} / {total}")
    lines.append(f"<b>剩余：</b> {remaining}")
    if info.get("expire_time"):
        lines.append(f"<b>到期：</b> {html.escape(str(info['expire_time']))}")
    if info.get("node_count") is not None:
        lines.append(f"<b>节点数：</b> {int(info.get('node_count') or 0)}")

    quick_check_text = _format_quick_check(info, compact=True)
    if quick_check_text:
        lines.append(quick_check_text)

    cache_remaining = info.get("_cache_remaining_text")
    cache_expires_at = info.get("_cache_expires_at")
    last_exported_at = info.get("_cache_last_exported_at")
    if cache_remaining:
        lines.append(f"<b>缓存有效：</b> {html.escape(str(cache_remaining))}")
    elif cache_expires_at:
        lines.append(f"<b>缓存截止：</b> {html.escape(str(cache_expires_at))}")
    if last_exported_at:
        lines.append(f"<b>最近导出：</b> {html.escape(str(last_exported_at))}")
    return "\n".join(lines)


def format_node_analysis_compact(info, url=None):
    """Format compact node-analysis details."""
    del url
    lines = ["<b>节点摘要</b>"]
    if info.get("name"):
        lines.append(f"<b>名称：</b> {html.escape(str(info['name']))}")
    if info.get("node_count") is not None:
        lines.append(f"<b>节点数：</b> {int(info.get('node_count') or 0)}")

    quick_check_text = _format_quick_check(info, compact=True)
    if quick_check_text:
        lines.append(quick_check_text)

    stats = info.get("node_stats") or {}
    countries = stats.get("countries") or {}
    if countries:
        top_countries = sorted(countries.items(), key=lambda item: item[1], reverse=True)[:3]
        country_text = " / ".join(f"{html.escape(str(country))} {count}" for country, count in top_countries)
        lines.append(f"<b>地区：</b> {country_text}")

    protocols = stats.get("protocols") or {}
    if protocols:
        top_protocols = sorted(protocols.items(), key=lambda item: item[1], reverse=True)[:3]
        protocol_text = " / ".join(f"{html.escape(str(protocol).upper())} {count}" for protocol, count in top_protocols)
        lines.append(f"<b>协议：</b> {protocol_text}")

    lines.append("<b>说明：</b> 纯节点列表，不含订阅流量和到期信息")
    return "\n".join(lines)

