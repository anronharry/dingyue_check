"""Subscription parsing utilities."""
from __future__ import annotations

import asyncio
import base64
import binascii
import copy
import math
import re
import time
from collections import Counter
from datetime import datetime
from urllib.parse import unquote, urlparse

import aiohttp
import yaml

from core import node_extractor as ip_extractor
from core.file_handler import FileHandler


class SubscriptionParser:
    """Download and parse subscription payloads."""

    DIRECT_PROTOCOL_PATTERN = re.compile(
        r"(?im)^\s*(vmess|vless|trojan|ss|ssr|hysteria|hysteria2|hy2|tuic|wireguard)://"
    )

    def __init__(
        self,
        proxy_port=7890,
        use_proxy=False,
        session=None,
        verify_ssl: bool = True,
        *,
        max_parse_concurrency: int = 24,
        success_cache_ttl_seconds: int = 12,
        success_cache_max_size: int = 512,
    ):
        self.proxy_port = proxy_port
        self.use_proxy = use_proxy
        self.proxy_url = f"http://127.0.0.1:{proxy_port}" if use_proxy else None
        self.session = session
        self.verify_ssl = bool(verify_ssl)
        self._parse_semaphore = asyncio.Semaphore(max(1, int(max_parse_concurrency)))
        self._inflight_lock = asyncio.Lock()
        self._inflight_tasks: dict[str, asyncio.Future] = {}
        self._success_cache: dict[str, tuple[float, dict]] = {}
        self._success_cache_ttl_seconds = max(0, int(success_cache_ttl_seconds))
        self._success_cache_max_size = max(8, int(success_cache_max_size))

    async def parse(self, url, *, force_refresh: bool = False):
        cache_key = str(url).strip()
        if not force_refresh:
            cached = self._get_cached_result(cache_key)
            if cached is not None:
                return cached

        is_owner = False
        async with self._inflight_lock:
            shared_task = self._inflight_tasks.get(cache_key)
            if shared_task is None:
                shared_task = asyncio.create_task(self._parse_with_semaphore(url, cache_key))
                self._inflight_tasks[cache_key] = shared_task
                is_owner = True

        try:
            result = await shared_task
            return copy.deepcopy(result)
        finally:
            if is_owner:
                async with self._inflight_lock:
                    if self._inflight_tasks.get(cache_key) is shared_task:
                        self._inflight_tasks.pop(cache_key, None)

    async def _parse_with_semaphore(self, url: str, cache_key: str) -> dict:
        async with self._parse_semaphore:
            result = await self._parse_impl(url)
        self._set_cached_result(cache_key, result)
        return result

    def _get_cached_result(self, cache_key: str) -> dict | None:
        if not cache_key or self._success_cache_ttl_seconds <= 0:
            return None
        cached = self._success_cache.get(cache_key)
        if not cached:
            return None
        ts, result = cached
        if (time.time() - ts) > self._success_cache_ttl_seconds:
            self._success_cache.pop(cache_key, None)
            return None
        return copy.deepcopy(result)

    def _set_cached_result(self, cache_key: str, result: dict) -> None:
        if not cache_key or self._success_cache_ttl_seconds <= 0:
            return
        self._success_cache[cache_key] = (time.time(), copy.deepcopy(result))
        if len(self._success_cache) > self._success_cache_max_size:
            oldest_key = next(iter(self._success_cache.keys()))
            self._success_cache.pop(oldest_key, None)

    async def _parse_impl(self, url):
        try:
            response_text, response_headers = await self._download_subscription(url)
            if self._is_pseudo_200_response(response_text, response_headers):
                raise Exception("检测到伪装响应页面，判定为无效订阅")

            traffic_info = self._parse_traffic_info(response_headers)
            nodes, content_format, normalized_nodes, normalized_content, parse_notes = self._parse_nodes(response_text)
            airport_name = self._extract_airport_name(nodes, url, response_headers, response_text)
            node_stats = await self._analyze_nodes(nodes)
            if not nodes:
                raise Exception("未解析到任何有效节点")

            return {
                "name": airport_name,
                "node_count": len(nodes),
                "node_stats": node_stats,
                "_raw_nodes": nodes,
                "_normalized_nodes": normalized_nodes,
                "_raw_content": normalized_content,
                "_content_format": content_format,
                "_parse_notes": parse_notes,
                **traffic_info,
            }
        except aiohttp.ClientError as exc:
            raise Exception(f"下载订阅失败: {exc}")
        except Exception as exc:
            raise Exception(f"解析订阅失败: {exc}")

    async def _download_subscription(self, url):
        from utils.retry_utils import async_retry_on_failure

        headers = {
            "User-Agent": "Clash-verge/1.3.8",
            "Accept": "*/*",
        }
        session_to_use = self.session
        close_session = False
        if session_to_use is None:
            session_to_use = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=10))
            close_session = True

        @async_retry_on_failure(max_retries=3, initial_delay=1.0, backoff_factor=2.0)
        async def _fetch():
            request_kwargs = {
                "headers": headers,
                "proxy": self.proxy_url,
                "timeout": aiohttp.ClientTimeout(total=30),
            }
            if not self.verify_ssl:
                request_kwargs["ssl"] = False

            async with session_to_use.get(url, **request_kwargs) as response:
                response.raise_for_status()
                body = await response.read()
                text = self._decode_response_body(body, response.charset)
                return text, {k.lower(): v for k, v in response.headers.items()}

        try:
            return await _fetch()
        finally:
            if close_session:
                await session_to_use.close()

    def _shannon_entropy(self, data: str) -> float:
        if not data:
            return 0
        entropy = 0.0
        for char in set(data):
            probability = float(data.count(char)) / len(data)
            if probability > 0:
                entropy += -probability * math.log(probability, 2)
        return entropy

    def _is_pseudo_200_response(self, content: str, headers: dict) -> bool:
        content_lower = content.lower()
        content_type = headers.get("content-type", "").lower()
        if "text/html" in content_type and any(
            word in content_lower for word in ["error", "forbidden", "blocked", "firewall", "拦截", "未找到"]
        ):
            return True
        if 0 < len(content) < 50 and any(word in content_lower for word in ["forbidden", "not found", "error"]):
            return True
        if len(content) > 100 and self._shannon_entropy(content) < 4.25 and re.search(r"<(html|head|body|script|div|a)", content_lower):
            return True
        return False

    def _parse_traffic_info(self, headers):
        traffic_info = {}
        userinfo = headers.get("subscription-userinfo", "")
        if not userinfo:
            return traffic_info

        for part in userinfo.split(";"):
            part = part.strip()
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key in {"upload", "download", "total"}:
                traffic_info[key] = int(value)
            elif key == "expire":
                try:
                    traffic_info["expire_time"] = datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass

        if "upload" in traffic_info and "download" in traffic_info:
            traffic_info["used"] = traffic_info["upload"] + traffic_info["download"]
        if "total" in traffic_info and "used" in traffic_info:
            traffic_info["remaining"] = traffic_info["total"] - traffic_info["used"]
            if traffic_info["total"] > 0:
                traffic_info["usage_percent"] = (traffic_info["used"] / traffic_info["total"]) * 100
        return traffic_info

    def _parse_nodes(self, content):
        max_nodes = 300
        parse_notes: list[str] = []
        normalized_original = self._normalize_subscription_text(content)

        yaml_nodes = self._parse_yaml_nodes(normalized_original, max_nodes=max_nodes)
        if yaml_nodes is not None:
            parse_notes.append("direct-yaml")
            return yaml_nodes, "yaml", list(yaml_nodes), normalized_original, parse_notes

        if self._contains_direct_protocol(normalized_original):
            parse_notes.append("direct-protocol")
            nodes = FileHandler.parse_txt_file(normalized_original.encode("utf-8"))[:max_nodes]
            return nodes, "text", list(nodes), normalized_original, parse_notes

        decoded_content = self._try_decode_subscription_base64(normalized_original)
        if decoded_content:
            parse_notes.append("base64-decoded")
            yaml_nodes = self._parse_yaml_nodes(decoded_content, max_nodes=max_nodes)
            if yaml_nodes is not None:
                parse_notes.append("decoded-yaml")
                return yaml_nodes, "yaml", list(yaml_nodes), decoded_content, parse_notes

            nodes = FileHandler.parse_txt_file(decoded_content.encode("utf-8"))[:max_nodes]
            return nodes, "text", list(nodes), decoded_content, parse_notes

        parse_notes.append("unrecognized-content")
        nodes = FileHandler.parse_txt_file(normalized_original.encode("utf-8"))[:max_nodes]
        return nodes, "text", list(nodes), normalized_original, parse_notes

    @staticmethod
    def _normalize_subscription_text(content: str) -> str:
        if not content:
            return ""
        normalized = content.replace("\ufeff", "").replace("\x00", "")
        return normalized.strip()

    @classmethod
    def _contains_direct_protocol(cls, content: str) -> bool:
        if not content:
            return False
        return bool(cls.DIRECT_PROTOCOL_PATTERN.search(content))

    def _try_decode_subscription_base64(self, content: str) -> str | None:
        candidate = self._sanitize_base64_candidate(content)
        if not self._is_probable_base64(candidate):
            return None

        for decoder in (self._decode_base64_standard, self._decode_base64_urlsafe):
            decoded = decoder(candidate)
            if decoded and self._looks_like_subscription_payload(decoded):
                return self._normalize_subscription_text(decoded)
        return None

    @staticmethod
    def _sanitize_base64_candidate(content: str) -> str:
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
        if noise_ratio > 0.08:
            return ""
        return filtered

    def _is_probable_base64(self, candidate: str) -> bool:
        if not candidate or len(candidate) < 24:
            return False
        if self._contains_direct_protocol(candidate):
            return False
        if not re.fullmatch(r"[A-Za-z0-9+/=_-]+", candidate):
            return False

        padded = candidate + ("=" * ((4 - len(candidate) % 4) % 4))
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

    @staticmethod
    def _decode_base64_standard(candidate: str) -> str | None:
        padded = candidate + ("=" * ((4 - len(candidate) % 4) % 4))
        try:
            decoded = base64.b64decode(padded, validate=True)
        except (ValueError, binascii.Error):
            return None
        return decoded.decode("utf-8-sig", errors="ignore")

    @staticmethod
    def _decode_base64_urlsafe(candidate: str) -> str | None:
        normalized = candidate.replace("-", "+").replace("_", "/")
        padded = normalized + ("=" * ((4 - len(normalized) % 4) % 4))
        try:
            decoded = base64.b64decode(padded, validate=True)
        except (ValueError, binascii.Error):
            return None
        return decoded.decode("utf-8-sig", errors="ignore")

    def _looks_like_subscription_payload(self, content: str) -> bool:
        if not content:
            return False
        normalized = self._normalize_subscription_text(content)
        if not normalized:
            return False
        if self._contains_direct_protocol(normalized):
            return True
        if self._parse_yaml_nodes(normalized, max_nodes=1) is not None:
            return True
        return False

    @staticmethod
    def _decode_response_body(body: bytes, charset: str | None) -> str:
        candidates = []
        if charset:
            candidates.append(charset)
        candidates.extend(["utf-8", "utf-8-sig", "gb18030"])
        for encoding in candidates:
            try:
                return body.decode(encoding)
            except Exception:
                continue
        return body.decode("utf-8", errors="ignore")

    @staticmethod
    def _parse_yaml_nodes(content: str, *, max_nodes: int) -> list[dict] | None:
        if not (content.strip().startswith("#") or "proxies:" in content[:5000] or "proxy-groups:" in content[:5000]):
            return None

        yaml_content = content
        if len(yaml_content) > 300 * 1024:
            truncate_idx = yaml_content.rfind("\n", 0, 300 * 1024)
            yaml_content = yaml_content[: truncate_idx if truncate_idx != -1 else 300 * 1024]

        try:
            config = yaml.safe_load(yaml_content)
        except Exception:
            return None

        if not isinstance(config, dict) or "proxies" not in config:
            return None

        nodes = []
        for proxy in config["proxies"]:
            if len(nodes) >= max_nodes:
                break
            if isinstance(proxy, dict):
                nodes.append(
                    {
                        "name": proxy.get("name", "未命名节点"),
                        "protocol": proxy.get("type", "unknown").lower(),
                        "server": proxy.get("server", ""),
                        "port": proxy.get("port", 0),
                    }
                )
        return nodes

    def _parse_node_line(self, line):
        protocols = [
            "vmess://",
            "vless://",
            "ss://",
            "ssr://",
            "trojan://",
            "hysteria://",
            "hysteria2://",
            "hy2://",
            "tuic://",
            "wireguard://",
        ]
        for protocol in protocols:
            if line.startswith(protocol):
                return {"protocol": protocol.replace("://", ""), "name": self._extract_node_name(line, protocol), "raw": line}
        return None

    def _extract_node_name(self, line, protocol):
        if "#" in line:
            name = line.split("#", 1)[1]
            try:
                return unquote(name).strip()
            except Exception:
                return name.strip()
        if protocol == "vmess://":
            try:
                import json

                encoded = line.replace("vmess://", "")
                if len(encoded) % 4:
                    encoded += "=" * (4 - len(encoded) % 4)
                decoded = base64.b64decode(encoded).decode("utf-8")
                config = json.loads(decoded)
                if "ps" in config:
                    return config["ps"]
            except Exception:
                pass
        return "未命名节点"

    def _extract_airport_name(self, nodes, url, headers=None, content=None):
        bad_keywords = [
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
        ]
        common_tlds = ["com", "net", "org", "me", "io", "cc", "top", "xyz", "shop", "info", "site", "link", "cloud", "vip", "best"]

        def is_trash(value):
            if not value or len(value) < 2 or value.isdigit() or len(value) > 30:
                return True
            return any(keyword in value for keyword in bad_keywords)

        if headers:
            raw_title = headers.get("profile-title") or headers.get("x-airport-name") or headers.get("x-profile-name")
            if raw_title:
                title = unquote(raw_title).strip().strip('"').strip("'").strip()
                if not is_trash(title):
                    return title
            content_disposition = headers.get("content-disposition", "")
            if "filename" in content_disposition:
                match = re.search(r"filename=['\"]?(.+?)['\"]?(?:;|$)", content_disposition, re.IGNORECASE)
                if match:
                    name = re.sub(r"\.(yaml|yml|txt|conf)$", "", unquote(match.group(1)), flags=re.IGNORECASE)
                    if not is_trash(name):
                        return name

        if content:
            first_line = content[:500].split("\n", 1)[0].strip()
            if first_line.startswith(("#", "//")):
                comment_title = first_line.lstrip("#/ ").strip()
                if comment_title and not is_trash(comment_title):
                    return comment_title

        if nodes:
            prefixes = []
            for node in nodes:
                match = re.match(r"^([^| \-，,.]+)", node.get("name", ""))
                if match:
                    prefix = match.group(1).strip()
                    if len(prefix) >= 3:
                        prefixes.append(prefix)
            if prefixes:
                most_common = Counter(prefixes).most_common(1)
                if most_common and most_common[0][1] >= (len(nodes) * 0.3):
                    return most_common[0][0]

        parsed = urlparse(url)
        for part in reversed([part for part in parsed.path.split("/") if part]):
            clean = re.sub(r"\.(yaml|yml|txt|conf)$", "", part, flags=re.IGNORECASE)
            if not is_trash(clean):
                return clean

        domain = parsed.netloc.split(":")[0]
        domain_parts = [part for part in domain.split(".") if part.lower() not in common_tlds and part.lower() not in ["api", "sub", "www", "cdn"]]
        if domain_parts and not is_trash(domain_parts[-1]):
            return domain_parts[-1]

        return "未知机场"

    async def _analyze_nodes(self, nodes):
        import asyncio
        import config
        from core.geo_service import GeoLocationService

        protocols = [node.get("protocol", "unknown") for node in nodes]
        protocol_stats = dict(Counter(protocols))
        if not config.ENABLE_GEO_LOOKUP:
            countries = [self._match_country_by_keyword(node.get("name", "")) for node in nodes]
            return {"protocols": protocol_stats, "countries": dict(Counter(countries)), "locations": []}

        geo_client = GeoLocationService()
        node_ip_pairs = []
        for node in nodes:
            ip = ip_extractor.NodeIPExtractor.extract_ip(node)
            node_ip_pairs.append((node, ip if ip and ip_extractor.NodeIPExtractor.is_valid_ip(ip) else None))

        geo_nodes = [(node, ip) for node, ip in node_ip_pairs if ip is not None][: config.MAX_GEO_QUERIES]
        geo_results = {}
        if geo_nodes:
            unique_ips = list({ip for _, ip in geo_nodes})
            results = await asyncio.gather(*[geo_client.get_location(ip) for ip in unique_ips], return_exceptions=True)
            for ip, result in zip(unique_ips, results):
                geo_results[ip] = None if isinstance(result, Exception) else result

        countries = []
        locations_detail = []
        country_detail_count = Counter()
        geo_query_used = 0
        for node, ip in node_ip_pairs:
            country = None
            detail_obj = None
            if ip and geo_query_used < config.MAX_GEO_QUERIES:
                geo_query_used += 1
                location = geo_results.get(ip)
                if location:
                    country = location["country"]
                    countries.append(country)
                    if country_detail_count[country] < 3:
                        detail_obj = {
                            "name": node.get("name", "未知"),
                            "country": country,
                            "city": location["city"],
                            "isp": location["isp"],
                            "country_code": location["country_code"],
                            "flag": geo_client.get_country_flag(location["country_code"]),
                        }
            if not country:
                country = self._match_country_by_keyword(node.get("name", ""))
                countries.append(country)
                if country_detail_count[country] < 3:
                    detail_obj = {
                        "name": node.get("name", "未知"),
                        "country": country,
                        "city": "未知",
                        "isp": "未知",
                        "country_code": "",
                        "flag": "🌐",
                    }
            if detail_obj:
                locations_detail.append(detail_obj)
                country_detail_count[country] += 1
        return {"protocols": protocol_stats, "countries": dict(Counter(countries)), "locations": locations_detail}

    def _match_country_by_keyword(self, node_name: str) -> str:
        country_keywords = {
            "香港": ["香港", "HK", "Hong Kong", "Hongkong"],
            "台湾": ["台湾", "TW", "Taiwan"],
            "日本": ["日本", "JP", "Japan"],
            "美国": ["美国", "US", "USA", "America"],
            "新加坡": ["新加坡", "SG", "Singapore"],
            "韩国": ["韩国", "KR", "Korea"],
        }
        for country, keywords in country_keywords.items():
            if any(keyword in node_name for keyword in keywords):
                return country
        return "其他"
