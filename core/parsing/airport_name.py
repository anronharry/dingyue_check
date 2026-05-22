"""Airport/subscription name detection helpers."""

from __future__ import annotations

import base64
import ipaddress
import re
from collections import Counter
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, unquote, unquote_plus, urlparse

import yaml  # type: ignore[import-untyped]


UNKNOWN_AIRPORT = "未知机场"
COMMON_TLDS = {
    "com",
    "net",
    "org",
    "me",
    "io",
    "cc",
    "top",
    "xyz",
    "shop",
    "info",
    "site",
    "link",
    "cloud",
    "vip",
    "best",
}
IGNORED_DOMAIN_PARTS = {"www", "api", "sub", "cdn"}
BAD_KEYWORDS = {
    "过期",
    "到期",
    "流量",
    "剩余",
    "GB",
    "TB",
    "官网",
    "地址",
    "通知",
    "维护",
    "重置",
    "套餐",
    "客服",
    "注册",
    "节点",
    "测速",
    "client",
    "subscribe",
    "api",
    "sub",
    "chatgpt",
    "openai",
    "claude",
    "gemini",
    "deepseek",
}
TRASH_NAMES = {
    "api",
    "sub",
    "subscribe",
    "subscription",
    "client",
    "config",
    "profile",
    "default",
    "clash",
    "mihomo",
    "v1",
    "v2",
    "v3",
    "chatgpt",
    "gpt",
    "gpt4",
    "gpt-4",
    "openai",
    "claude",
    "gemini",
    "deepseek",
}
KNOWN_AIRPORT_ALIAS = {
    "alberhong": ("alberhong", "alberta", "bobbi", "ndjp"),
    "wcloud": ("wcloud", "w-cloud"),
    "nexitally": ("nexitally", "nex"),
    "mojie": ("mojie", "魔戒"),
    "bianyuan": ("边缘", "bianyuan"),
    "jichang": ("机场", "airportsub"),
}
HEADER_NAME_KEYS = (
    "profile-title",
    "x-profile-title",
    "x-airport-name",
    "x-profile-name",
    "subscription-title",
    "x-subscription-title",
    "profile-name",
    "x-profile",
    "title",
)
QUERY_NAME_KEYS = (
    "name",
    "title",
    "profile",
    "profile_name",
    "subscription_name",
    "provider",
    "provider_name",
    "airport",
    "airport_name",
    "tag",
)
NODE_BRAND_STOP_WORDS = {
    "hk",
    "jp",
    "sg",
    "us",
    "tw",
    "kr",
    "vip",
    "net",
    "node",
    "trojan",
    "vmess",
    "vless",
    "ss",
    "ssr",
    "chatgpt",
    "gpt",
    "openai",
    "claude",
    "gemini",
    "deepseek",
}

NormalizeText = Callable[[str], str]


def extract_airport_name(
    nodes: list[dict[str, Any]],
    url: str,
    *,
    headers: dict[str, Any] | None = None,
    content: str | None = None,
    normalize_text: NormalizeText,
) -> str:
    candidates: list[tuple[int, str]] = []
    _add_header_candidates(candidates, headers or {})
    _add_content_candidates(candidates, content, normalize_text)
    _add_node_candidates(candidates, nodes)
    _add_url_candidates(candidates, url)
    return _best_candidate(candidates)


def header_name_candidates(headers: dict[str, Any]) -> list[str]:
    candidates = []
    for key in HEADER_NAME_KEYS:
        value = headers.get(key)
        if value and str(value).strip():
            candidates.append(str(value).strip())
    return candidates


def content_name_candidates(content: str, normalize_text: NormalizeText) -> list[tuple[str, int]]:
    normalized = normalize_text(content)
    if not normalized:
        return []
    candidates = _comment_name_candidates(normalized)
    candidates.extend(_yaml_name_candidates(normalized))
    return candidates


def query_name_candidates(query: str) -> list[str]:
    if not query:
        return []
    values: list[str] = []
    params = parse_qs(query, keep_blank_values=False)
    for key in QUERY_NAME_KEYS:
        values.extend(str(item).strip() for item in params.get(key, []) if str(item).strip())
    return values


def normalize_airport_candidate(value: str) -> str:
    text = str(value or "").strip().strip('"').strip("'")
    if not text:
        return ""
    for _ in range(2):
        text = unquote_plus(text).strip()
    text = text.replace("\ufeff", "").replace("\x00", "")
    text = re.sub(r"^[\[\(（【<\s]+|[\]\)）】>\s]+$", "", text)
    text = re.sub(r"\.(yaml|yml|txt|conf)$", "", text, flags=re.IGNORECASE).strip()
    return re.sub(r"\s{2,}", " ", text)


def extract_name_from_content_disposition(content_disposition: str) -> str | None:
    match_star = re.search(r"filename\*\s*=\s*([^;]+)", content_disposition, re.IGNORECASE)
    if match_star:
        decoded = _decode_content_disposition_name(match_star.group(1))
        if decoded:
            return decoded
    match_plain = re.search(
        r"filename=['\"]?(.+?)['\"]?(?:;|$)", content_disposition, re.IGNORECASE
    )
    if not match_plain:
        return None
    name = _strip_config_suffix(unquote(match_plain.group(1)).strip())
    return name or None


def extract_brand_from_nodes(nodes: list[dict[str, Any]]) -> str | None:
    counter: Counter[str] = Counter()
    casing: dict[str, str] = {}
    for node in nodes:
        name = str(node.get("name") or "")
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", name):
            key = token.lower()
            if key in NODE_BRAND_STOP_WORDS or re.fullmatch(r"[a-z]{1,2}\d*", key):
                continue
            counter[key] += 1
            casing.setdefault(key, token)
    if not counter:
        return None
    candidate, hits = counter.most_common(1)[0]
    if hits < max(3, int(len(nodes) * 0.2)):
        return None
    return casing.get(candidate, candidate)


def decode_profile_title(raw_title: str) -> str:
    decoded = normalize_airport_candidate(raw_title)
    if not decoded:
        return ""
    b64_candidate = decoded.split(":", 1)[1].strip() if _has_base64_prefix(decoded) else decoded
    for candidate in (decoded, b64_candidate):
        maybe = try_decode_small_base64_text(candidate)
        if maybe:
            return maybe
    return decoded


def try_decode_small_base64_text(candidate: str) -> str | None:
    if not candidate or len(candidate) < 4 or not re.fullmatch(r"[A-Za-z0-9+/=_-]+", candidate):
        return None
    padded = _pad_base64(candidate.replace("-", "+").replace("_", "/"))
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        decoded = _decode_small_text(padded, encoding)
        if decoded:
            return decoded
    return None


def _add_candidate(candidates: list[tuple[int, str]], value: str | None, score: int) -> None:
    if value is None:
        return
    normalized = normalize_airport_candidate(value)
    if normalized and not _is_trash(normalized):
        candidates.append((score, normalized))


def _add_header_candidates(candidates: list[tuple[int, str]], headers: dict[str, Any]) -> None:
    for raw_title in header_name_candidates(headers):
        _add_candidate(candidates, decode_profile_title(raw_title), 120)
    content_disposition = str(headers.get("content-disposition", "") or "")
    _add_candidate(candidates, extract_name_from_content_disposition(content_disposition), 112)
    _add_profile_web_candidate(candidates, headers)


def _add_profile_web_candidate(candidates: list[tuple[int, str]], headers: dict[str, Any]) -> None:
    profile_web = headers.get("profile-web-page-url") or headers.get("x-profile-web-page-url")
    if not profile_web:
        return
    web_host = urlparse(str(profile_web)).netloc.split(":")[0].strip()
    parts = _domain_name_parts(web_host)
    if parts:
        _add_candidate(candidates, parts[-1], 90)


def _add_content_candidates(
    candidates: list[tuple[int, str]], content: str | None, normalize_text: NormalizeText
) -> None:
    if not content:
        return
    for name_candidate, score in content_name_candidates(content, normalize_text):
        _add_candidate(candidates, name_candidate, score)


def _add_node_candidates(candidates: list[tuple[int, str]], nodes: list[dict[str, Any]]) -> None:
    if not nodes:
        return
    _add_candidate(candidates, extract_brand_from_nodes(nodes), 85)
    prefixes = _node_prefixes(nodes)
    if prefixes:
        most_common = Counter(prefixes).most_common(1)
        if most_common and most_common[0][1] >= (len(nodes) * 0.35):
            _add_candidate(candidates, most_common[0][0], 65)


def _add_url_candidates(candidates: list[tuple[int, str]], url: str) -> None:
    parsed = urlparse(url)
    lower_url = url.lower()
    for airport_name, aliases in KNOWN_AIRPORT_ALIAS.items():
        if any(alias in lower_url for alias in aliases):
            _add_candidate(candidates, airport_name, 80)
    for query_name in query_name_candidates(parsed.query):
        _add_candidate(candidates, query_name, 84)
    _add_path_candidates(candidates, parsed.path)
    _add_domain_candidates(candidates, parsed.netloc.split(":")[0])


def _is_trash(value: str) -> bool:
    cleaned = normalize_airport_candidate(value)
    lowered = cleaned.lower()
    if not cleaned or len(cleaned) < 2 or cleaned.isdigit() or len(cleaned) > 40:
        return True
    if lowered in TRASH_NAMES:
        return True
    if re.fullmatch(r"v\d+(\.\d+){0,2}", lowered) or re.fullmatch(r"[a-z]{1,2}\d{0,2}", lowered):
        return True
    if re.fullmatch(r"[a-f0-9]{8,}", lowered):
        return True
    return any(keyword.lower() in lowered for keyword in BAD_KEYWORDS)


def _best_candidate(candidates: list[tuple[int, str]]) -> str:
    if not candidates:
        return UNKNOWN_AIRPORT
    score_map: dict[str, dict[str, int]] = {}
    for score, name in candidates:
        entry = score_map.setdefault(name, {"total": 0, "max": 0, "hits": 0})
        entry["total"] += int(score)
        entry["max"] = max(entry["max"], int(score))
        entry["hits"] += 1
    best_name, _stats = max(
        score_map.items(),
        key=lambda item: (item[1]["total"], item[1]["max"], item[1]["hits"], len(item[0])),
    )
    return best_name


def _comment_name_candidates(normalized: str) -> list[tuple[str, int]]:
    candidates: list[tuple[str, int]] = []
    for line in normalized.splitlines()[:40]:
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith(("#", "//", ";")):
            break
        body = stripped.lstrip("#/; ").strip()
        match = re.search(
            r"(profile[-_ ]?title|airport[-_ ]?name|subscription[-_ ]?name|name)\s*[:=]\s*(.+)$",
            body,
            re.IGNORECASE,
        )
        if match:
            candidates.append((match.group(2).strip(), 105))
        elif len(body) >= 2:
            candidates.append((body, 68))
    return candidates


def _yaml_name_candidates(normalized: str) -> list[tuple[str, int]]:
    if "proxies:" not in normalized[:8000] and "proxy-providers:" not in normalized[:8000]:
        return []
    config = _load_small_yaml(normalized)
    if not isinstance(config, dict):
        return []
    candidates = _top_level_yaml_names(config)
    candidates.extend(_provider_yaml_names(config))
    return candidates


def _load_small_yaml(normalized: str) -> Any:
    yaml_content = normalized
    if len(yaml_content) > 256 * 1024:
        truncate_idx = yaml_content.rfind("\n", 0, 256 * 1024)
        yaml_content = yaml_content[: truncate_idx if truncate_idx != -1 else 256 * 1024]
    try:
        return yaml.safe_load(yaml_content)
    except Exception:
        return None


def _top_level_yaml_names(config: dict[str, Any]) -> list[tuple[str, int]]:
    candidates: list[tuple[str, int]] = []
    for key in ("name", "profile-title", "title", "subscription-name", "provider", "provider-name"):
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append((value.strip(), 110))
    return candidates


def _provider_yaml_names(config: dict[str, Any]) -> list[tuple[str, int]]:
    providers = config.get("proxy-providers")
    if not isinstance(providers, dict) or not (1 <= len(providers) <= 3):
        return []
    return [
        (name.strip(), 88) for name in providers.keys() if isinstance(name, str) and name.strip()
    ]


def _decode_content_disposition_name(raw_value: str) -> str:
    raw = raw_value.strip().strip('"').strip("'")
    encoded = raw.split("''", 1)[1] if "''" in raw else raw
    return _strip_config_suffix(unquote(encoded).strip())


def _strip_config_suffix(value: str) -> str:
    return re.sub(r"\.(yaml|yml|txt|conf)$", "", value, flags=re.IGNORECASE).strip()


def _domain_name_parts(domain: str) -> list[str]:
    return [
        part
        for part in domain.split(".")
        if part and part.lower() not in COMMON_TLDS and part.lower() not in IGNORED_DOMAIN_PARTS
    ]


def _node_prefixes(nodes: list[dict[str, Any]]) -> list[str]:
    prefixes: list[str] = []
    for node in nodes:
        match = re.match(r"^([^| \-，,.]+)", str(node.get("name", "")))
        if match:
            prefix = match.group(1).strip()
            if len(prefix) >= 3:
                prefixes.append(prefix)
    return prefixes


def _add_path_candidates(candidates: list[tuple[int, str]], path: str) -> None:
    parts = [part for part in path.split("/") if part]
    for index, part in enumerate(reversed(parts)):
        clean = _strip_config_suffix(part)
        _add_candidate(candidates, clean, max(45 - index, 30))


def _add_domain_candidates(candidates: list[tuple[int, str]], domain: str) -> None:
    try:
        ipaddress.ip_address(domain)
        _add_candidate(candidates, domain, 25)
    except ValueError:
        pass
    domain_parts = _domain_name_parts(domain)
    if domain_parts:
        _add_candidate(candidates, domain_parts[-1], 35)


def _has_base64_prefix(value: str) -> bool:
    return ":" in value and value.split(":", 1)[0].lower() in {"base64", "b64"}


def _decode_small_text(padded: str, encoding: str) -> str | None:
    try:
        decoded = base64.b64decode(padded).decode(encoding, errors="ignore").strip()
    except Exception:
        return None
    if not decoded:
        return None
    printable_ratio = sum(ch.isprintable() for ch in decoded) / max(1, len(decoded))
    if printable_ratio < 0.9:
        return None
    return decoded.strip().strip('"').strip("'")


def _pad_base64(candidate: str) -> str:
    return candidate + ("=" * ((4 - len(candidate) % 4) % 4))


__all__ = [
    "content_name_candidates",
    "decode_profile_title",
    "extract_airport_name",
    "extract_brand_from_nodes",
    "extract_name_from_content_disposition",
    "header_name_candidates",
    "normalize_airport_candidate",
    "query_name_candidates",
    "try_decode_small_base64_text",
]
