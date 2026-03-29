"""Formatting helpers shared by renderers and legacy modules."""
from __future__ import annotations


from datetime import datetime


def bytes_to_gb(bytes_value):
    if bytes_value is None:
        return 0
    return bytes_value / (1024**3)


def format_traffic(bytes_value):
    if bytes_value is None or bytes_value == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    size = float(bytes_value)
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    return f"{size:.2f} {units[unit_index]}"


def create_progress_bar(percent, length=10):
    if percent < 0:
        percent = 0
    elif percent > 100:
        percent = 100
    filled_length = int(length * percent / 100)
    if percent > 0 and filled_length == 0:
        filled_length = 1
    bar = "■" * filled_length + "□" * (length - filled_length)
    return f"[{bar}]"


def get_country_flag(country_name):
    flags = {
        "香港": "🇭🇰",
        "台湾": "🇹🇼",
        "日本": "🇯🇵",
        "美国": "🇺🇸",
        "新加坡": "🇸🇬",
        "韩国": "🇰🇷",
        "英国": "🇬🇧",
        "德国": "🇩🇪",
        "法国": "🇫🇷",
        "加拿大": "🇨🇦",
        "澳大利亚": "🇦🇺",
        "俄罗斯": "🇷🇺",
        "印度": "🇮🇳",
        "荷兰": "🇳🇱",
        "土耳其": "🇹🇷",
        "巴西": "🇧🇷",
        "越南": "🇻🇳",
        "泰国": "🇹🇭",
        "菲律宾": "🇵🇭",
        "马来西亚": "🇲🇾",
        "印尼": "🇮🇩",
        "阿根廷": "🇦🇷",
        "墨西哥": "🇲🇽",
        "其他": "🌐",
    }
    return flags.get(country_name, "🏳️")


def format_remaining_time(expire_time_str, *, include_seconds: bool = True):
    try:
        expire_date = datetime.strptime(expire_time_str, "%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        if expire_date < now:
            return "已过期"
        delta = expire_date - now
        days = delta.days
        seconds = delta.seconds
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        sec = seconds % 60
        if not include_seconds:
            if days > 0:
                return f"{days}天{hours}时"
            if hours > 0:
                return f"{hours}时{minutes}分"
            if minutes > 0:
                return f"{minutes}分"
            return "不足1分"
        return f"{days}天{hours}时{minutes}分{sec}秒"
    except Exception:
        return ""
