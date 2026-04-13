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
    def _code_to_flag(alpha2: str) -> str:
        if len(alpha2) != 2 or not alpha2.isascii() or not alpha2.isalpha():
            return "🏳️"
        return "".join(chr(ord(ch) + 127397) for ch in alpha2.upper())

    if country_name is None:
        return "🏳️"
    text = str(country_name).strip()
    if not text:
        return "🏳️"

    # Direct ISO-3166 alpha-2 code (e.g. US/CN/JP).
    if len(text) == 2 and text.isascii() and text.isalpha():
        return _code_to_flag(text)

    normalized = text.lower().replace(" ", "").replace("-", "").replace("_", "").replace(".", "")
    aliases = {
        "香港": "HK",
        "hongkong": "HK",
        "hongkongsar": "HK",
        "hk": "HK",
        "taiwan": "TW",
        "台湾": "TW",
        "japan": "JP",
        "日本": "JP",
        "unitedstates": "US",
        "unitedstatesofamerica": "US",
        "usa": "US",
        "us": "US",
        "america": "US",
        "美国": "US",
        "singapore": "SG",
        "新加坡": "SG",
        "southkorea": "KR",
        "republicofkorea": "KR",
        "korea": "KR",
        "韩国": "KR",
        "china": "CN",
        "中国": "CN",
        "uk": "GB",
        "unitedkingdom": "GB",
        "britain": "GB",
        "greatbritain": "GB",
        "england": "GB",
        "英国": "GB",
        "germany": "DE",
        "德国": "DE",
        "france": "FR",
        "法国": "FR",
        "canada": "CA",
        "加拿大": "CA",
        "australia": "AU",
        "澳大利亚": "AU",
        "russia": "RU",
        "俄罗斯": "RU",
        "india": "IN",
        "印度": "IN",
        "netherlands": "NL",
        "荷兰": "NL",
        "turkey": "TR",
        "turkiye": "TR",
        "土耳其": "TR",
        "brazil": "BR",
        "巴西": "BR",
        "vietnam": "VN",
        "越南": "VN",
        "thailand": "TH",
        "泰国": "TH",
        "philippines": "PH",
        "菲律宾": "PH",
        "malaysia": "MY",
        "马来西亚": "MY",
        "indonesia": "ID",
        "印尼": "ID",
        "argentina": "AR",
        "阿根廷": "AR",
        "mexico": "MX",
        "墨西哥": "MX",
    }
    if normalized in {"其他", "其它", "other", "others", "unknown", "未知", "global"}:
        return "🌐"
    code = aliases.get(normalized)
    return _code_to_flag(code) if code else "🏳️"


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
