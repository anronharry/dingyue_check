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


def format_subscription_info(info, url=None):
    """Format subscription details as Telegram HTML."""
    message = "<b>🚀 订阅检测结果</b>\n\n"

    if info.get("name"):
        name = html.escape(info["name"])
        message += f"<b>订阅名称：</b> {name}\n"

    if any(key in info for key in ["total", "used", "remaining"]):
        used = format_traffic(info.get("used", 0))
        total = format_traffic(info.get("total", 0))
        remaining = format_traffic(info.get("remaining", 0))
        message += f"<b>流量详情：</b> {used} / {total}\n"

        if info.get("usage_percent") is not None:
            percent = info["usage_percent"]
            bar = create_progress_bar(percent, length=10)
            message += f"<b>使用进度：</b> {bar} {percent:.1f}%\n"
            if percent >= 100:
                message += "<b>预警状态：</b> ❌ 流量已完全耗尽\n"
            elif percent >= 90:
                message += "<b>预警状态：</b> ⚠️ 流量即将耗尽\n"

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
                message += "<b>预警状态：</b> ❌ 订阅已过期\n"
            elif "天" in remaining_time:
                try:
                    days_left = int(remaining_time.split("天")[0])
                    if days_left < 3:
                        message += "<b>预警状态：</b> ⚠️ 订阅距离到期不足 3 天\n"
                except Exception:
                    pass

    message += "\n" + "—" * 20 + "\n\n"

    if info.get("node_stats"):
        stats = info["node_stats"]
        if stats.get("locations"):
            locations = stats["locations"]
            country_groups = defaultdict(list)
            for loc in locations:
                country_groups[loc["country"]].append(loc)

            message += "<b>🌍 节点地理位置（真实 IP）:</b>\n"
            for country, locs in sorted(country_groups.items(), key=lambda x: len(x[1]), reverse=True):
                flag = locs[0]["flag"] if locs[0]["flag"] != "🌐" else get_country_flag(country)
                message += f"\n{flag} <b>{country}</b> ({len(locs)}个):\n"
                for loc in locs[:3]:
                    city = loc["city"] if loc["city"] != "未知" else ""
                    isp = loc["isp"] if loc["isp"] != "未知" else ""
                    detail = f"{city} - {isp}" if city and isp else (city or isp or "详情未知")
                    message += f"  • {html.escape(loc['name'][:20])}... ({detail})\n"
                if len(locs) > 3:
                    message += f"  ... 还有 {len(locs) - 3} 个节点\n"
            message += "\n"
        elif stats.get("countries"):
            message += "<b>🌍 节点区域分布：</b>\n"
            for country, count in sorted(stats["countries"].items(), key=lambda x: x[1], reverse=True):
                message += f"{get_country_flag(country)} {html.escape(country)}: {count}\n"
            message += "\n"

        if stats.get("protocols"):
            message += "<b>🔐 协议分布：</b>\n"
            for protocol, count in sorted(stats["protocols"].items(), key=lambda x: x[1], reverse=True):
                message += f"{protocol.upper()}: {count}\n"

    if info.get("node_count") is not None:
        message += f"\n<b>📍 节点总数：</b> {info['node_count']}\n"

    if url:
        message += f"\n<b>📋 订阅链接（点击复制）：</b>\n<code>{url}</code>"

    return message
