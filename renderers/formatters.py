"""Telegram-facing message formatters."""
from __future__ import annotations

import html
from collections import defaultdict

from shared.format_helpers import (
    create_progress_bar,
    format_remaining_time,
    format_traffic,
    get_country_flag,
)


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

    suffix = "（仅抽样检测）" if sampled else ""
    if compact:
        summary = f"存活：{alive}/{tested}" if tested else "存活：0/0"
        if skipped:
            summary += f" | 跳过 {skipped}"
        return f"<b>快速检测：</b> {summary}{suffix}{skipped_detail}"

    parts = [f"已测 {tested}", f"存活 {alive}", f"失败 {dead}"]
    if skipped:
        parts.append(f"跳过 {skipped}")
    return f"<b>快速检测：</b> {' | '.join(parts)}{suffix}{skipped_detail}"


def _render_node_list(info: dict, *, max_items: int = 80, char_budget: int = 2200) -> str:
    nodes = info.get("_normalized_nodes") or info.get("_raw_nodes") or []
    if not nodes:
        return ""

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

    if not lines:
        return ""

    hidden_count = max(0, len(nodes) - len(lines))
    message = "<b>节点列表（共 {} 个）</b>\n{}".format(
        info.get("node_count") or len(nodes),
        "\n".join(lines),
    )
    if hidden_count:
        message += f"\n... 其余 {hidden_count} 个节点已折叠"
    return message


def format_subscription_info(info, url=None):
    """Format verbose subscription details as Telegram HTML."""
    message = "<b>订阅检测结果</b>\n\n"
    if info.get("name"):
        message += f"<b>订阅名称：</b> {html.escape(info['name'])}\n"

    if any(key in info for key in ["total", "used", "remaining"]):
        used = format_traffic(info.get("used", 0))
        total = format_traffic(info.get("total", 0))
        remaining = format_traffic(info.get("remaining", 0))
        message += f"<b>流量详情：</b> {used} / {total}\n"
        if info.get("usage_percent") is not None:
            percent = info["usage_percent"]
            message += f"<b>使用进度：</b> {create_progress_bar(percent, length=10)} {percent:.1f}%\n"
            if percent >= 100:
                message += "<b>预警状态：</b> 流量已耗尽\n"
            elif percent >= 90:
                message += "<b>预警状态：</b> 流量即将耗尽\n"
        if info.get("remaining") is not None:
            message += f"<b>剩余流量：</b> {remaining}\n"
    else:
        message += "<b>流量信息：</b> 无\n"

    if info.get("expire_time"):
        message += f"<b>到期时间：</b> {info['expire_time']}\n"
        remaining_time = format_remaining_time(info["expire_time"])
        if remaining_time:
            message += f"<b>剩余时间：</b> {remaining_time}\n"
            if remaining_time == "已过期":
                message += "<b>预警状态：</b> 订阅已过期\n"
            elif "天" in remaining_time:
                try:
                    days_left = int(remaining_time.split("天", 1)[0])
                    if days_left < 3:
                        message += "<b>预警状态：</b> 距离到期不足 3 天\n"
                except Exception:
                    pass

    quick_check_text = _format_quick_check(info)
    if quick_check_text:
        message += f"{quick_check_text}\n"

    message += "\n--------------------\n\n"

    if info.get("node_stats"):
        stats = info["node_stats"]
        if stats.get("locations"):
            country_groups = defaultdict(list)
            for location in stats["locations"]:
                country_groups[location["country"]].append(location)
            message += "<b>节点地理位置（真实 IP）</b>\n"
            for country, locations in sorted(country_groups.items(), key=lambda item: len(item[1]), reverse=True):
                flag = locations[0]["flag"] if locations[0]["flag"] != "未知" else get_country_flag(country)
                message += f"\n{flag} <b>{html.escape(country)}</b> ({len(locations)}个):\n"
                for location in locations[:3]:
                    city = location["city"] if location["city"] != "未知" else ""
                    isp = location["isp"] if location["isp"] != "未知" else ""
                    detail = f"{city} - {isp}" if city and isp else (city or isp or "详情未知")
                    message += f"  - {html.escape(location['name'][:20])}... ({html.escape(detail)})\n"
                if len(locations) > 3:
                    message += f"  ... 还有 {len(locations) - 3} 个节点\n"
            message += "\n"
        elif stats.get("countries"):
            message += "<b>节点区域分布</b>\n"
            for country, count in sorted(stats["countries"].items(), key=lambda item: item[1], reverse=True):
                message += f"{get_country_flag(country)} {html.escape(country)}: {count}\n"
            message += "\n"

        if stats.get("protocols"):
            message += "<b>协议分布</b>\n"
            for protocol, count in sorted(stats["protocols"].items(), key=lambda item: item[1], reverse=True):
                message += f"{html.escape(protocol.upper())}: {count}\n"

    if info.get("node_count") is not None:
        message += f"\n<b>节点总数：</b> {info['node_count']}\n"

    node_list_text = _render_node_list(info)
    if node_list_text:
        message += f"\n{node_list_text}\n"

    if url:
        message += f"\n<b>订阅链接（点击复制）：</b>\n<code>{html.escape(url)}</code>"
    return message


def format_subscription_compact(info, url=None):
    """Format compact subscription details for delayed message collapse."""
    del url
    message = "<b>订阅摘要</b>\n\n"
    if info.get("name"):
        message += f"<b>名称：</b> {html.escape(info['name'])}\n"
    if info.get("remaining") is not None:
        message += f"<b>剩余：</b> {format_traffic(info.get('remaining', 0))}\n"
    if info.get("expire_time"):
        message += f"<b>到期：</b> {info['expire_time']}\n"
        remaining_time = format_remaining_time(info["expire_time"], include_seconds=False)
        if remaining_time:
            message += f"<b>剩余时间：</b> {remaining_time}\n"
    if info.get("node_count") is not None:
        message += f"<b>节点数：</b> {info['node_count']}\n"

    quick_check_text = _format_quick_check(info, compact=True)
    if quick_check_text:
        message += f"{quick_check_text}\n"

    tags = info.get("tags") or []
    if tags:
        message += f"<b>标签：</b> {html.escape(', '.join(tags[:5]))}\n"

    cache_remaining = info.get("_cache_remaining_text")
    cache_expires_at = info.get("_cache_expires_at")
    last_exported_at = info.get("_cache_last_exported_at")
    if cache_remaining:
        message += f"<b>缓存有效：</b> {cache_remaining}\n"
    elif cache_expires_at:
        message += f"<b>缓存截止：</b> {cache_expires_at}\n"
    if last_exported_at:
        message += f"<b>最近导出：</b> {last_exported_at}\n"
    return message.strip()


def format_node_analysis_compact(info, url=None):
    """Format compact node-analysis details for delayed message collapse."""
    del url
    message = "<b>节点摘要</b>\n\n"
    if info.get("name"):
        message += f"<b>名称：</b> {html.escape(info['name'])}\n"
    if info.get("node_count") is not None:
        message += f"<b>节点数：</b> {info['node_count']}\n"

    quick_check_text = _format_quick_check(info, compact=True)
    if quick_check_text:
        message += f"{quick_check_text}\n"

    stats = info.get("node_stats") or {}
    countries = stats.get("countries") or {}
    if countries:
        top_countries = sorted(countries.items(), key=lambda item: item[1], reverse=True)[:3]
        country_text = " / ".join(f"{html.escape(country)} {count}" for country, count in top_countries)
        message += f"<b>地区：</b> {country_text}\n"

    protocols = stats.get("protocols") or {}
    if protocols:
        top_protocols = sorted(protocols.items(), key=lambda item: item[1], reverse=True)[:3]
        protocol_text = " / ".join(f"{html.escape(protocol.upper())} {count}" for protocol, count in top_protocols)
        message += f"<b>协议：</b> {protocol_text}\n"

    message += "<b>说明：</b> 纯节点列表，不含订阅流量和到期信息"
    return message.strip()
