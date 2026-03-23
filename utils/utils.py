"""
工具函数模块
提供 URL 验证、输入类型检测等辅助功能。
展示格式化逻辑已迁移到 renderers 层，这里保留兼容导出。
"""


from __future__ import annotations
import re
from urllib.parse import urlparse
from typing import Literal

from renderers.formatters import format_subscription_info
from shared.format_helpers import (
    bytes_to_gb,
    create_progress_bar,
    format_remaining_time,
    format_traffic,
    get_country_flag,
)


def is_valid_url(url):
    """验证 URL 是否有效。"""
    try:
        result = urlparse(url)
        return result.scheme in ("http", "https") and bool(result.netloc)
    except Exception:
        return False


class InputDetector:
    """智能输入类型检测器。"""

    @staticmethod
    def detect_message_type(update) -> Literal["file", "url", "node_text", "unknown"]:
        if update.message.document:
            return "file"
        if update.message.text:
            text = update.message.text.strip()
            if InputDetector.is_subscription_url(text):
                return "url"
            if InputDetector.is_node_text(text):
                return "node_text"
        return "unknown"

    @staticmethod
    def is_subscription_url(text: str) -> bool:
        if not text.startswith(("http://", "https://")):
            return False
        url_pattern = r"^https?://[^\s]+$"
        lines = text.split("\n")
        return all(re.match(url_pattern, line.strip()) for line in lines if line.strip())

    @staticmethod
    def is_node_text(text: str) -> bool:
        protocols = [
            "vmess://",
            "vless://",
            "ss://",
            "ssr://",
            "trojan://",
            "hysteria://",
            "hysteria2://",
        ]
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if not lines:
            return False
        node_count = sum(1 for line in lines if any(line.startswith(p) for p in protocols))
        return node_count >= len(lines) * 0.5

    @staticmethod
    def detect_file_type(filename: str) -> Literal["txt", "yaml", "json", "unknown"]:
        name = filename.lower()
        if name.endswith(".txt"):
            return "txt"
        if name.endswith((".yaml", ".yml")):
            return "yaml"
        if name.endswith(".json"):
            return "json"
        return "unknown"
