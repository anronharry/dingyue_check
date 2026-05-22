"""Owner aggregate state and application lifecycle helpers."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

from aiohttp import web

from web.aggregate.state import OwnerAggregateState
from web.auth import MemoryAuthBackend, require_secret
from web.constants import (
    AGG_API_DEPS_KEY,
    AGG_PREWARM_INTERVAL_SECONDS,
    AGG_PREWARM_MAX_SECONDS,
    AGG_PREWARM_MIN_SECONDS,
    AGG_STATE_KEY,
    AGG_TASK_KEY,
    AUTH_BACKEND_KEY,
    REDIS_ALLOW_MEMORY_FALLBACK_KEY,
    RUNTIME_KEY,
)

logger = logging.getLogger(__name__)


def _aggregate_state_file() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data" / "db" / "owner_aggregate.json"


def _aggregate_node_health_state() -> OwnerAggregateState:
    secret = require_secret(os.getenv("WEB_ADMIN_TOKEN", ""), name="WEB_ADMIN_TOKEN")
    return OwnerAggregateState(_aggregate_state_file(), secret_key=secret)


def _compute_next_prewarm_sleep(*, fingerprint_changed: bool, had_error: bool) -> int:
    if had_error:
        return AGG_PREWARM_MIN_SECONDS
    if fingerprint_changed:
        return max(
            AGG_PREWARM_MIN_SECONDS, min(AGG_PREWARM_INTERVAL_SECONDS, AGG_PREWARM_MIN_SECONDS * 2)
        )
    return max(AGG_PREWARM_INTERVAL_SECONDS, AGG_PREWARM_MAX_SECONDS)


async def _aggregate_prewarm_loop(app: web.Application) -> None:
    runtime = app[RUNTIME_KEY]
    state: OwnerAggregateState = app[AGG_STATE_KEY]
    deps = app[AGG_API_DEPS_KEY]
    while True:
        sleep_seconds = AGG_PREWARM_INTERVAL_SECONDS
        try:
            token = await state.get_token()
            loop_started = time.perf_counter()
            previous_meta = await state.read_meta()
            previous_fingerprint = str(
                (previous_meta.get("build_stats", {}) or {}).get("fingerprint", "") or ""
            )
            bundle = await deps.build_bundle(runtime, state=state)
            stats = dict(bundle.get("stats", {}) or {})
            stats["fingerprint"] = await deps.compute_fingerprint(runtime)
            write_started = time.perf_counter()
            await state.write_cache(
                content=str(bundle.get("yaml", "") or ""),
                raw_content=str(bundle.get("raw", "") or ""),
                base64_content=str(bundle.get("base64", "") or ""),
                node_count=int(bundle.get("node_count", 0) or 0),
                fingerprint=str(stats.get("fingerprint", "")),
            )
            stats["timings_ms"] = dict(stats.get("timings_ms", {}) or {})
            stats["timings_ms"]["write_cache"] = deps.format_timing_ms(write_started)
            stats["timings_ms"]["prewarm_total"] = deps.format_timing_ms(loop_started)
            stats["pool_snapshot"] = deps.build_pool_snapshot(
                stats,
                await state.read_node_health(),
                stats.get("top_sources", []),
            )
            await state.write_build_stats(
                stats, snapshot=dict(stats.get("pool_snapshot", {}) or {})
            )
            sleep_seconds = _compute_next_prewarm_sleep(
                fingerprint_changed=str(stats.get("fingerprint", "")) != previous_fingerprint,
                had_error=False,
            )
            logger.info(
                "owner aggregate cache refreshed token=%s nodes=%s",
                token[:8],
                int(bundle.get("node_count", 0) or 0),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await state.write_error(message=str(exc))
            logger.warning("owner aggregate prewarm failed: %s", exc)
            sleep_seconds = _compute_next_prewarm_sleep(fingerprint_changed=False, had_error=True)
        await asyncio.sleep(sleep_seconds)


async def _start_background_tasks(app: web.Application) -> None:
    app[AGG_TASK_KEY] = asyncio.create_task(_aggregate_prewarm_loop(app))


async def _validate_auth_backend(app: web.Application) -> None:
    backend = app[AUTH_BACKEND_KEY]
    validate = getattr(backend, "validate_connection", None)
    if validate is None:
        return
    try:
        result = validate()
        if hasattr(result, "__await__"):
            await result
    except Exception as exc:
        if app.get(REDIS_ALLOW_MEMORY_FALLBACK_KEY, False):
            logger.error("Redis unreachable; explicitly falling back to memory. reason=%s", exc)
            app[AUTH_BACKEND_KEY] = MemoryAuthBackend()
            return
        raise RuntimeError(
            "WEB_ADMIN_REDIS_URL is configured, but Redis auth backend is unreachable. "
            "Fix WEB_ADMIN_REDIS_URL or explicitly set "
            "WEB_ADMIN_REDIS_ALLOW_MEMORY_FALLBACK=true."
        ) from exc


async def _close_auth_backend(app: web.Application) -> None:
    task = app.get(AGG_TASK_KEY)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    backend = app[AUTH_BACKEND_KEY]
    close = getattr(backend, "close", None)
    if close is not None:
        result = close()
        if hasattr(result, "__await__"):
            await result
