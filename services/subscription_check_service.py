"""Unified subscription check service.

This service centralizes parser invocation + persistence side effects so
handlers can focus on interaction flow.
"""
from __future__ import annotations

import asyncio
import time
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import dataclass


@dataclass
class SubscriptionProcessError(Exception):
    code: str
    user_message: str
    raw_message: str = ""

    def __str__(self) -> str:
        return self.user_message


class SubscriptionCheckService:
    def __init__(
        self,
        *,
        get_parser,
        get_storage,
        logger,
        export_cache_service=None,
        global_concurrency: int = 20,
        user_concurrency: int = 6,
        retry_attempts: int = 2,
        retry_backoff_seconds: float = 0.35,
        slow_threshold_seconds: float = 8.0,
        stats_report_every: int = 50,
    ):
        self.get_parser = get_parser
        self.get_storage = get_storage
        self.logger = logger
        self.export_cache_service = export_cache_service
        self.global_concurrency = max(1, int(global_concurrency))
        self.user_concurrency = max(1, int(user_concurrency))
        self.retry_attempts = max(1, int(retry_attempts))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))
        self.slow_threshold_seconds = max(0.01, float(slow_threshold_seconds))
        self.stats_report_every = max(1, int(stats_report_every))
        self._global_semaphore = asyncio.Semaphore(self.global_concurrency)
        self._user_lock = asyncio.Lock()
        self._user_semaphores: dict[int, asyncio.Semaphore] = {}
        self._obs_lock = asyncio.Lock()
        self._stats = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "retried": 0,
            "slow": 0,
            "latency_ms_sum": 0.0,
            "latency_ms_max": 0.0,
            "error_codes": Counter(),
        }

    async def _get_user_semaphore(self, owner_uid: int) -> asyncio.Semaphore:
        async with self._user_lock:
            semaphore = self._user_semaphores.get(owner_uid)
            if semaphore is None:
                semaphore = asyncio.Semaphore(self.user_concurrency)
                self._user_semaphores[owner_uid] = semaphore
            return semaphore

    @asynccontextmanager
    async def _acquire_limits(self, owner_uid: int):
        user_semaphore = await self._get_user_semaphore(owner_uid)
        async with self._global_semaphore:
            async with user_semaphore:
                yield

    async def parse_and_store(self, *, url: str, owner_uid: int) -> dict:
        start = time.perf_counter()
        retries_used = 0
        try:
            async with self._acquire_limits(owner_uid):
                result, retries_used = await self._parse_with_retry(url=url)

            store = self.get_storage()
            store.add_or_update(url, result, user_id=owner_uid)
            if self.export_cache_service:
                self.export_cache_service.save_subscription_cache(owner_uid=owner_uid, source=url, result=result)
        except Exception as exc:
            err = self._normalize_error(exc)
            duration_ms = (time.perf_counter() - start) * 1000.0
            await self._observe(
                url=url,
                owner_uid=owner_uid,
                success=False,
                error_code=err.code,
                duration_ms=duration_ms,
                retries_used=retries_used,
            )
            raise err

        duration_ms = (time.perf_counter() - start) * 1000.0
        await self._observe(
            url=url,
            owner_uid=owner_uid,
            success=True,
            error_code="success",
            duration_ms=duration_ms,
            retries_used=retries_used,
        )
        return result

    async def parse_subscription_urls(self, *, subscription_urls: list[str], owner_uid: int) -> list[dict]:
        store = self.get_storage()
        semaphore = asyncio.Semaphore(min(self.global_concurrency, max(1, self.user_concurrency * 2)))

        async def _parse_one(index: int, url: str) -> dict:
            async with semaphore:
                try:
                    result = await self.parse_and_store(url=url, owner_uid=owner_uid)
                    return {"index": index, "url": url, "data": result, "status": "success"}
                except Exception as exc:
                    err = self._normalize_error(exc)
                    self.logger.error(
                        "Subscription parse failed %s [%s]: %s",
                        url,
                        err.code,
                        err.raw_message or str(exc),
                    )
                    return {
                        "index": index,
                        "url": url,
                        "error": err.user_message,
                        "error_code": err.code,
                        "status": "failed",
                    }

        store.begin_batch()
        try:
            return await asyncio.gather(*[_parse_one(index, url) for index, url in enumerate(subscription_urls, 1)])
        finally:
            store.end_batch(save=True)

    async def _parse_with_retry(self, *, url: str) -> tuple[dict, int]:
        last_exc: Exception | None = None
        retries_used = 0
        for attempt in range(1, self.retry_attempts + 1):
            try:
                parser_instance = await self.get_parser()
                return await parser_instance.parse(url), retries_used
            except Exception as exc:
                normalized = self._normalize_error(exc)
                last_exc = normalized
                is_last = attempt >= self.retry_attempts
                if is_last or not self._is_retryable_code(normalized.code):
                    raise normalized
                retries_used += 1
                delay = self.retry_backoff_seconds * attempt
                self.logger.warning(
                    "Subscription parse retry %s/%s for %s, code=%s, delay=%.2fs",
                    attempt,
                    self.retry_attempts,
                    url,
                    normalized.code,
                    delay,
                )
                await asyncio.sleep(delay)
        if last_exc:
            raise last_exc
        raise SubscriptionProcessError(code="unknown_error", user_message="订阅解析失败，请稍后重试。")

    async def _observe(
        self,
        *,
        url: str,
        owner_uid: int,
        success: bool,
        error_code: str,
        duration_ms: float,
        retries_used: int,
    ) -> None:
        is_slow = duration_ms >= (self.slow_threshold_seconds * 1000.0)
        async with self._obs_lock:
            stats = self._stats
            stats["total"] += 1
            stats["latency_ms_sum"] += duration_ms
            stats["latency_ms_max"] = max(float(stats["latency_ms_max"]), duration_ms)
            stats["retried"] += max(0, int(retries_used))
            if success:
                stats["success"] += 1
            else:
                stats["failed"] += 1
                stats["error_codes"][error_code] += 1
            if is_slow:
                stats["slow"] += 1

            total = int(stats["total"])
            success_count = int(stats["success"])
            failed_count = int(stats["failed"])
            retried_count = int(stats["retried"])
            slow_count = int(stats["slow"])
            avg_ms = float(stats["latency_ms_sum"]) / max(1, total)
            max_ms = float(stats["latency_ms_max"])

        if is_slow:
            self.logger.warning(
                "Slow subscription parse: uid=%s url=%s cost=%.0fms retries=%s code=%s",
                owner_uid,
                url,
                duration_ms,
                retries_used,
                error_code,
            )
        if total % self.stats_report_every == 0:
            self.logger.info(
                "Subscription parse stats: total=%s success=%s failed=%s retried=%s slow=%s avg=%.0fms max=%.0fms",
                total,
                success_count,
                failed_count,
                retried_count,
                slow_count,
                avg_ms,
                max_ms,
            )

    async def get_observability_snapshot(self) -> dict:
        async with self._obs_lock:
            stats = self._stats
            total = int(stats["total"])
            return {
                "total": total,
                "success": int(stats["success"]),
                "failed": int(stats["failed"]),
                "retried": int(stats["retried"]),
                "slow": int(stats["slow"]),
                "avg_latency_ms": (float(stats["latency_ms_sum"]) / max(1, total)),
                "max_latency_ms": float(stats["latency_ms_max"]),
                "error_codes": dict(stats["error_codes"]),
            }

    @staticmethod
    def _is_retryable_code(code: str) -> bool:
        return code in {"network_error", "timeout", "upstream_error"}

    @staticmethod
    def _normalize_error(exc: Exception) -> SubscriptionProcessError:
        if isinstance(exc, SubscriptionProcessError):
            return exc

        raw = str(exc or "").strip()
        lowered = raw.lower()

        if any(token in lowered for token in ("timeout", "timed out", "超时")):
            return SubscriptionProcessError("timeout", "订阅请求超时，请稍后重试。", raw)
        if any(token in lowered for token in ("ssl", "certificate", "证书")):
            return SubscriptionProcessError("ssl_error", "SSL 证书校验失败，请检查订阅地址或稍后重试。", raw)
        if any(token in lowered for token in ("403", "401", "forbidden", "unauthorized", "权限")):
            return SubscriptionProcessError("auth_error", "订阅链接无权限或已失效，请更新后重试。", raw)
        if any(token in lowered for token in ("404", "not found")):
            return SubscriptionProcessError("not_found", "订阅链接不存在，请确认地址是否正确。", raw)
        if any(token in lowered for token in ("502", "503", "504", "bad gateway", "service unavailable")):
            return SubscriptionProcessError("upstream_error", "上游服务暂时不可用，请稍后重试。", raw)
        if any(token in lowered for token in ("下载订阅失败", "connection", "connector", "dns", "network", "连接")):
            return SubscriptionProcessError("network_error", "网络连接异常，请稍后重试。", raw)
        if any(token in lowered for token in ("无法识别订阅内容", "未解析到任何有效节点", "unrecognized-content")):
            return SubscriptionProcessError("invalid_content", "无法识别订阅内容，请确认链接是否为有效订阅。", raw)

        return SubscriptionProcessError("unknown_error", "订阅解析失败，请稍后重试。", raw)
