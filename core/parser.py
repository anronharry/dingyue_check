"""Subscription parsing utilities."""

from __future__ import annotations

import asyncio
import copy
import re
import time
from urllib.parse import unquote

import aiohttp
from core.parsing import airport_name
from core.parsing import content_detector
from core.parsing import downloader
from core.parsing import node_parser
from core.parsing.downloader import DownloaderConfig, SubscriptionDownloader
from core.parsing.downloader import DownloaderConfig, SubscriptionDownloader
from core.parsing import downloader
from core.parsing.node_stats import analyze_nodes, match_country_by_keyword
from core.parsing.traffic import parse_traffic_info


class SubscriptionParser:
    """Download and parse subscription payloads."""

    DIRECT_PROTOCOL_PATTERN = re.compile(
        r"(?im)^\s*(vmess|vless|trojan|ss|ssr|hysteria|hysteria2|hy2|tuic|wireguard)://"
    )
    DEFAULT_UA_POOL = downloader.DEFAULT_UA_POOL

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
        self._downloader = SubscriptionDownloader(
            session=session,
            config=DownloaderConfig(proxy_url=self.proxy_url, verify_ssl=self.verify_ssl),
        )
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
            nodes, content_format, normalized_nodes, normalized_content, parse_notes = (
                self._parse_nodes(response_text)
            )
            airport_name = self._extract_airport_name(
                nodes, url, response_headers, normalized_content
            )
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
        payload = await self._downloader.download(url, self._looks_like_subscription_response_text)
        return payload.text, payload.headers

    @staticmethod
    def _should_retry_with_browser_ua(status: int, content: str) -> bool:
        return downloader.should_retry_with_browser_ua(status, content)

    @classmethod
    def _resolve_subscription_user_agents(cls) -> tuple[str, ...]:
        return downloader.resolve_subscription_user_agents()

    @staticmethod
    def _should_probe_traffic_headers(url: str) -> bool:
        return downloader.should_probe_traffic_headers(url)

    @staticmethod
    def _merge_subscription_headers(base: dict[str, str], extra: dict[str, str]) -> dict[str, str]:
        return downloader.merge_subscription_headers(base, extra)

    def _looks_like_subscription_response_text(self, content: str) -> bool:
        return content_detector.looks_like_subscription_response_text(content, self._has_yaml_nodes)

    def _shannon_entropy(self, data: str) -> float:
        return content_detector.shannon_entropy(data)

    def _is_pseudo_200_response(self, content: str, headers: dict) -> bool:
        return content_detector.is_pseudo_200_response(content, headers)

    def _parse_traffic_info(self, headers):
        return parse_traffic_info(headers)

    def _parse_nodes(self, content):
        parsed = node_parser.parse_nodes(
            content,
            normalize_text=self._normalize_subscription_text,
            contains_protocol=self._contains_direct_protocol,
            decode_base64=self._try_decode_subscription_base64,
        )
        return parsed.as_tuple()

    @staticmethod
    def _normalize_subscription_text(content: str) -> str:
        return content_detector.normalize_subscription_text(content)

    @classmethod
    def _contains_direct_protocol(cls, content: str) -> bool:
        return content_detector.contains_direct_protocol(content)

    def _try_decode_subscription_base64(self, content: str) -> str | None:
        return content_detector.try_decode_subscription_base64(
            content, yaml_detector=self._has_yaml_nodes
        )

    @staticmethod
    def _sanitize_base64_candidate(content: str) -> str:
        return content_detector.sanitize_base64_candidate(content)

    def _is_probable_base64(self, candidate: str) -> bool:
        return content_detector.is_probable_base64(candidate)

    @staticmethod
    def _decode_base64_standard(candidate: str) -> str | None:
        return content_detector._decode_base64_standard(candidate)

    @staticmethod
    def _decode_base64_urlsafe(candidate: str) -> str | None:
        return content_detector._decode_base64_urlsafe(candidate)

    def _looks_like_subscription_payload(self, content: str) -> bool:
        return content_detector.looks_like_subscription_payload(content, self._has_yaml_nodes)

    def _has_yaml_nodes(self, content: str) -> bool:
        return self._parse_yaml_nodes(content, max_nodes=1) is not None

    @staticmethod
    def _decode_response_body(body: bytes, charset: str | None) -> str:
        return downloader.decode_response_body(body, charset)

    @staticmethod
    def _parse_yaml_nodes(content: str, *, max_nodes: int) -> list[dict] | None:
        return node_parser.parse_yaml_nodes(content, max_nodes=max_nodes)

    @staticmethod
    def _parse_yaml_nodes_preserve_fields(content: str, *, max_nodes: int) -> list[dict] | None:
        return node_parser.parse_yaml_nodes_preserve_fields(content, max_nodes=max_nodes)

    def _parse_node_line(self, line):
        return node_parser.parse_node_line(line)

    def _extract_node_name(self, line, protocol):
        return node_parser.extract_node_name(line, protocol)

    def _extract_airport_name(self, nodes, url, headers=None, content=None):
        return airport_name.extract_airport_name(
            nodes,
            url,
            headers=headers,
            content=content,
            normalize_text=self._normalize_subscription_text,
        )

    @staticmethod
    def _header_name_candidates(headers: dict) -> list[str]:
        return airport_name.header_name_candidates(headers)

    def _content_name_candidates(self, content: str) -> list[tuple[str, int]]:
        return airport_name.content_name_candidates(content, self._normalize_subscription_text)

    @staticmethod
    def _query_name_candidates(query: str) -> list[str]:
        return airport_name.query_name_candidates(query)

    @staticmethod
    def _normalize_airport_candidate(value: str) -> str:
        return airport_name.normalize_airport_candidate(value)

    @staticmethod
    def _extract_name_from_content_disposition(content_disposition: str) -> str | None:
        return airport_name.extract_name_from_content_disposition(content_disposition)

    @staticmethod
    def _extract_brand_from_nodes(nodes: list[dict]) -> str | None:
        return airport_name.extract_brand_from_nodes(nodes)

    def _decode_profile_title(self, raw_title: str) -> str:
        return airport_name.decode_profile_title(raw_title)

    @staticmethod
    def _try_decode_small_base64_text(candidate: str) -> str | None:
        return airport_name.try_decode_small_base64_text(candidate)

    async def _analyze_nodes(self, nodes):
        return await analyze_nodes(nodes)

    def _match_country_by_keyword(self, node_name: str) -> str:
        return match_country_by_keyword(node_name)
