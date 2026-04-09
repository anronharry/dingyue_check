"""Telegram-facing message formatters."""
from __future__ import annotations

import html

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
    node_count = int(info.get("node_count") or 0)
    if node_count > 0:
        return "可用"
    parse_notes = set(info.get("_parse_notes") or [])
    if "unrecognized-content" in parse_notes:
        return "无法识别订阅内容"
    return "异常"


def _format_usage(info: dict) -> tuple[str, str, str]:
    used = format_traffic(info.get("used", 0)) if info.get("used") is not None else "未知"
    total = format_traffic(info.get("total", 0)) if info.get("total") is not None else "未知"
    remaining = format_traffic(info.get("remaining", 0)) if info.get("remaining") is not None else "未知"
    return used, total, remaining


def _build_details(info: dict, url: str | None, *, node_limit: int, node_char_budget: int, include_url: bool) -> str:
    lines = []
    node_lines, hidden_count = _render_node_lines(info, max_items=node_limit, char_budget=node_char_budget)
    if node_lines:
        lines.append(f"<b>节点列表（共 {info.get('node_count') or len(node_lines)} 个）</b>")
        lines.extend(node_lines)
        if hidden_count:
            lines.append(f"... 其余 {hidden_count} 个节点已折叠")

    stats = info.get("node_stats") or {}
    protocols = stats.get("protocols") or {}
    if protocols:
        protocol_text = " / ".join(
            f"{html.escape(str(protocol).upper())} {count}"
            for protocol, count in sorted(protocols.items(), key=lambda item: item[1], reverse=True)[:5]
        )
        lines.append(f"<b>协议分布：</b> {protocol_text}")

    countries = stats.get("countries") or {}
    if countries:
        country_text = " / ".join(
            f"{get_country_flag(country)}{html.escape(country)} {count}"
            for country, count in sorted(countries.items(), key=lambda item: item[1], reverse=True)[:5]
        )
        lines.append(f"<b>地区分布：</b> {country_text}")

    quick_check_text = _format_quick_check(info)
    if quick_check_text:
        lines.append(quick_check_text)

    parse_notes = info.get("_parse_notes") or []
    content_format = info.get("_content_format")
    note_parts = []
    if content_format:
        note_parts.append(f"格式={html.escape(str(content_format))}")
    if parse_notes:
        note_parts.append("流程=" + html.escape(",".join(str(item) for item in parse_notes[:6])))
    if note_parts:
        lines.append(f"<b>解析备注：</b> {' | '.join(note_parts)}")

    if include_url and url:
        lines.append("<b>原始订阅链接：</b>")
        lines.append(f"<code>{html.escape(url)}</code>")

    if not lines:
        return ""
    return "<tg-spoiler>\n" + "\n".join(lines) + "\n</tg-spoiler>"


def format_subscription_info(info, url=None):
    """Format subscription details as summary + native Telegram expandable details."""
    used, total, remaining = _format_usage(info)
    expire_time = info.get("expire_time") or "未知"
    node_count = int(info.get("node_count") or 0)

    summary_lines = [
        "<b>订阅摘要</b>",
        f"<b>机场名称：</b> {html.escape(str(info.get('name') or '未知机场'))}",
        f"<b>订阅状态：</b> {_status_text(info)}",
        f"<b>已用 / 总量：</b> {used} / {total}",
        f"<b>剩余流量：</b> {remaining}",
        f"<b>到期时间：</b> {html.escape(str(expire_time))}",
        f"<b>节点总数：</b> {node_count}",
    ]

    if info.get("usage_percent") is not None:
        percent = float(info["usage_percent"])
        summary_lines.append(f"<b>使用进度：</b> {create_progress_bar(percent, length=8)} {percent:.1f}%")

    remain_text = format_remaining_time(info.get("expire_time", ""), include_seconds=False) if info.get("expire_time") else ""
    if remain_text:
        summary_lines.append(f"<b>剩余时间：</b> {html.escape(remain_text)}")

    details = _build_details(info, url, node_limit=100, node_char_budget=1800, include_url=True)
    message = "\n".join(summary_lines) + ("\n\n" + details if details else "")

    if len(message) > MAX_TELEGRAM_TEXT:
        details = _build_details(info, url, node_limit=40, node_char_budget=1000, include_url=True)
        message = "\n".join(summary_lines) + ("\n\n" + details if details else "")
    if len(message) > MAX_TELEGRAM_TEXT:
        details = _build_details(info, url, node_limit=20, node_char_budget=650, include_url=False)
        message = "\n".join(summary_lines) + ("\n\n" + details if details else "")

    return message[:MAX_TELEGRAM_TEXT]


def format_subscription_compact(info, url=None):
    """Keep compact formatter for compatibility in non-primary flows."""
    del url
    lines = ["<b>订阅摘要</b>"]
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
