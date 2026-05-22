"""Subscription downloading helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import aiohttp

from utils.retry_utils import async_retry_on_failure


DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_CONNECTOR_LIMIT = 10
HTTP_ERROR_STATUS = 400
TRAFFIC_WARNING_MISSING = "订阅响应缺少可解析流量信息。"
TRAFFIC_WARNING_PROBED = (
    "机场未返回 subscription-userinfo，已轮询多个客户端 UA 仍无法补齐流量信息。"
)
DEFAULT_UA_POOL = (
    "ClashforWindows/0.20.39",
    "ClashForAndroid/2.5.12",
    "Stash/1.0",
    "QuantumultX",
    "Surge/5.0.0",
    "sing-box 1.10.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
)


@dataclass(frozen=True)
class DownloaderConfig:
    proxy_url: str | None = None
    verify_ssl: bool = True
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    connector_limit: int = DEFAULT_CONNECTOR_LIMIT


@dataclass(frozen=True)
class ResponsePayload:
    text: str
    headers: dict[str, str]


LooksLikeSubscription = Callable[[str], bool]


class SubscriptionDownloader:
    def __init__(self, *, session=None, config: DownloaderConfig | None = None):
        self._session = session
        self._config = config or DownloaderConfig()

    async def download(
        self, url: str, looks_like_subscription: LooksLikeSubscription
    ) -> ResponsePayload:
        session_to_use, close_session = self._resolve_session()
        try:
            return await self._fetch_with_retries(url, session_to_use, looks_like_subscription)
        finally:
            if close_session:
                await session_to_use.close()

    def _resolve_session(self):
        if self._session is not None:
            return self._session, False
        connector = aiohttp.TCPConnector(limit=self._config.connector_limit)
        return aiohttp.ClientSession(connector=connector), True

    async def _request_once(self, session, url: str, ua: str) -> tuple[int, str, dict[str, str]]:
        request_kwargs = {
            "headers": {"User-Agent": ua, "Accept": "*/*"},
            "proxy": self._config.proxy_url,
            "timeout": aiohttp.ClientTimeout(total=self._config.timeout_seconds),
        }
        if not self._config.verify_ssl:
            request_kwargs["ssl"] = False
        async with session.get(url, **request_kwargs) as response:
            body = await response.read()
            text = decode_response_body(body, response.charset)
            lowered_headers = {key.lower(): value for key, value in response.headers.items()}
            return response.status, text, lowered_headers

    async def _fetch_with_retries(
        self, url: str, session, looks_like_subscription: LooksLikeSubscription
    ) -> ResponsePayload:
        @async_retry_on_failure(max_retries=3, initial_delay=1.0, backoff_factor=2.0)
        async def _fetch() -> ResponsePayload:
            return await self._fetch_once(url, session, looks_like_subscription)

        return await _fetch()

    async def _fetch_once(
        self, url: str, session, looks_like_subscription: LooksLikeSubscription
    ) -> ResponsePayload:
        valid_content: ResponsePayload | None = None
        first_non_error: ResponsePayload | None = None
        first_http_status: int | None = None
        should_probe_traffic = should_probe_traffic_headers(url)

        for index, ua in enumerate(resolve_subscription_user_agents()):
            status, text, headers = await self._request_once(session, url, ua)
            first_http_status = status if first_http_status is None else first_http_status
            if status >= HTTP_ERROR_STATUS:
                if index == 0 and not should_retry_with_browser_ua(status, text):
                    break
                continue
            first_non_error = first_non_error or ResponsePayload(text, headers)
            if not looks_like_subscription(text):
                continue
            valid_content = merge_valid_payload(valid_content, text, headers)
            if has_traffic_header(valid_content.headers) or not should_probe_traffic:
                break

        return resolve_download_result(valid_content, first_non_error, first_http_status)


def resolve_subscription_user_agents() -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for ua in DEFAULT_UA_POOL:
        item = str(ua or "").strip()
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return tuple(result)


def should_retry_with_browser_ua(status: int, content: str) -> bool:
    if status == 403:
        return True
    if not content:
        return False
    content_lower = content.lower()
    waf_markers = ("safeline", "waf", "captcha", "access denied", "forbidden", "cloudflare")
    return any(marker in content_lower for marker in waf_markers)


def should_probe_traffic_headers(url: str) -> bool:
    lowered = str(url or "").lower()
    if "/api/v1/client/subscribe" in lowered:
        return True
    return "token=" in lowered and ("subscribe" in lowered or "/sub" in lowered)


def merge_subscription_headers(base: dict[str, str], extra: dict[str, str]) -> dict[str, str]:
    merged = dict(base)
    if not has_traffic_header(merged) and has_traffic_header(extra):
        merged["subscription-userinfo"] = extra["subscription-userinfo"]
    for key in profile_header_keys():
        if not merged.get(key) and extra.get(key):
            merged[key] = extra[key]
    return merged


def merge_valid_payload(
    current: ResponsePayload | None, text: str, headers: dict[str, str]
) -> ResponsePayload:
    if current is None:
        return ResponsePayload(text, dict(headers))
    merged_headers = merge_subscription_headers(current.headers, headers)
    return ResponsePayload(current.text, merged_headers)


def resolve_download_result(
    valid_content: ResponsePayload | None,
    first_non_error: ResponsePayload | None,
    first_http_status: int | None,
) -> ResponsePayload:
    if valid_content is not None:
        headers = headers_with_probe_warning(valid_content.headers)
        return ResponsePayload(valid_content.text, headers)
    if first_non_error is not None:
        headers = dict(first_non_error.headers)
        headers.setdefault("x-traffic-warning", TRAFFIC_WARNING_MISSING)
        return ResponsePayload(first_non_error.text, headers)
    raise aiohttp.ClientError(f"HTTP {first_http_status or 0}")


def headers_with_probe_warning(headers: dict[str, str]) -> dict[str, str]:
    if has_traffic_header(headers):
        return headers
    warned = dict(headers)
    warned["x-traffic-warning"] = TRAFFIC_WARNING_PROBED
    return warned


def has_traffic_header(headers: dict[str, str]) -> bool:
    return bool(str(headers.get("subscription-userinfo", "")).strip())


def profile_header_keys() -> tuple[str, ...]:
    return (
        "profile-title",
        "x-profile-title",
        "x-airport-name",
        "x-subscription-title",
        "content-disposition",
        "profile-web-page-url",
        "x-profile-web-page-url",
    )


def decode_response_body(body: bytes, charset: str | None) -> str:
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


__all__ = [
    "DEFAULT_UA_POOL",
    "DownloaderConfig",
    "ResponsePayload",
    "SubscriptionDownloader",
    "decode_response_body",
    "merge_subscription_headers",
    "resolve_subscription_user_agents",
    "should_probe_traffic_headers",
    "should_retry_with_browser_ua",
]
