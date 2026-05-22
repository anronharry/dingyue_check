"""Subscription response and payload detection helpers."""

from __future__ import annotations

import base64
import binascii
import math
import re
from collections.abc import Callable
from typing import Literal


DIRECT_PROTOCOL_PATTERN = re.compile(
    r"(?im)^\s*(vmess|vless|trojan|ss|ssr|hysteria|hysteria2|hy2|tuic|wireguard)://"
)
BASE64_MIN_LENGTH = 24
BASE64_NOISE_LIMIT = 0.08
PSEUDO_HTML_ENTROPY_LIMIT = 4.25
ContentKind = Literal["direct-protocol", "yaml", "base64", "unknown"]
YamlDetector = Callable[[str], bool]


def normalize_subscription_text(content: str) -> str:
    if not content:
        return ""
    normalized = content.replace("\ufeff", "").replace("\x00", "")
    return normalized.strip()


def contains_direct_protocol(content: str) -> bool:
    if not content:
        return False
    return bool(DIRECT_PROTOCOL_PATTERN.search(content))


def detect_subscription_content(content: str, yaml_detector: YamlDetector) -> ContentKind:
    normalized = normalize_subscription_text(content)
    if not normalized:
        return "unknown"
    if contains_direct_protocol(normalized):
        return "direct-protocol"
    if yaml_detector(normalized):
        return "yaml"
    if try_decode_subscription_base64(normalized, yaml_detector=yaml_detector) is not None:
        return "base64"
    return "unknown"


def looks_like_subscription_response_text(content: str, yaml_detector: YamlDetector) -> bool:
    return detect_subscription_content(content, yaml_detector) != "unknown"


def is_pseudo_200_response(content: str, headers: dict[str, str]) -> bool:
    content_lower = content.lower()
    content_type = headers.get("content-type", "").lower()
    if "text/html" in content_type and any(
        word in content_lower
        for word in ["error", "forbidden", "blocked", "firewall", "拦截", "未找到"]
    ):
        return True
    if 0 < len(content) < 50 and any(
        word in content_lower for word in ["forbidden", "not found", "error"]
    ):
        return True
    return _looks_like_low_entropy_html(content, content_lower)


def try_decode_subscription_base64(content: str, *, yaml_detector: YamlDetector) -> str | None:
    candidate = sanitize_base64_candidate(content)
    if not is_probable_base64(candidate):
        return None
    for decoder in (_decode_base64_standard, _decode_base64_urlsafe):
        decoded = decoder(candidate)
        if decoded and looks_like_subscription_payload(decoded, yaml_detector):
            return normalize_subscription_text(decoded)
    return None


def sanitize_base64_candidate(content: str) -> str:
    if not content:
        return ""
    compact = re.sub(r"\s+", "", content.replace("\ufeff", "").replace("\x00", ""))
    if not compact:
        return ""
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=_-")
    filtered = "".join(ch for ch in compact if ch in allowed)
    if not filtered:
        return ""
    noise_ratio = 1.0 - (len(filtered) / len(compact))
    if noise_ratio > BASE64_NOISE_LIMIT:
        return ""
    return filtered


def is_probable_base64(candidate: str) -> bool:
    if not candidate or len(candidate) < BASE64_MIN_LENGTH:
        return False
    if contains_direct_protocol(candidate):
        return False
    if not re.fullmatch(r"[A-Za-z0-9+/=_-]+", candidate):
        return False
    return _can_decode_base64(candidate)


def looks_like_subscription_payload(content: str, yaml_detector: YamlDetector) -> bool:
    normalized = normalize_subscription_text(content)
    if not normalized:
        return False
    if contains_direct_protocol(normalized):
        return True
    return yaml_detector(normalized)


def shannon_entropy(data: str) -> float:
    if not data:
        return 0
    entropy = 0.0
    for char in set(data):
        probability = float(data.count(char)) / len(data)
        if probability > 0:
            entropy += -probability * math.log(probability, 2)
    return entropy


def _looks_like_low_entropy_html(content: str, content_lower: str) -> bool:
    if len(content) <= 100:
        return False
    if shannon_entropy(content) >= PSEUDO_HTML_ENTROPY_LIMIT:
        return False
    return bool(re.search(r"<(html|head|body|script|div|a)", content_lower))


def _can_decode_base64(candidate: str) -> bool:
    padded = _pad_base64(candidate)
    try:
        base64.b64decode(padded, validate=True)
        return True
    except (ValueError, binascii.Error):
        normalized = padded.replace("-", "+").replace("_", "/")
        try:
            base64.b64decode(normalized, validate=True)
            return True
        except (ValueError, binascii.Error):
            return False


def _decode_base64_standard(candidate: str) -> str | None:
    try:
        decoded = base64.b64decode(_pad_base64(candidate), validate=True)
    except (ValueError, binascii.Error):
        return None
    return decoded.decode("utf-8-sig", errors="ignore")


def _decode_base64_urlsafe(candidate: str) -> str | None:
    normalized = candidate.replace("-", "+").replace("_", "/")
    try:
        decoded = base64.b64decode(_pad_base64(normalized), validate=True)
    except (ValueError, binascii.Error):
        return None
    return decoded.decode("utf-8-sig", errors="ignore")


def _pad_base64(candidate: str) -> str:
    return candidate + ("=" * ((4 - len(candidate) % 4) % 4))


__all__ = [
    "ContentKind",
    "contains_direct_protocol",
    "detect_subscription_content",
    "is_probable_base64",
    "is_pseudo_200_response",
    "looks_like_subscription_payload",
    "looks_like_subscription_response_text",
    "normalize_subscription_text",
    "sanitize_base64_candidate",
    "shannon_entropy",
    "try_decode_subscription_base64",
]
