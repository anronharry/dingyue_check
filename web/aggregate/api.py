"""Public and owner-facing aggregate subscription API handlers."""

from __future__ import annotations

import hmac
import os
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Awaitable, Callable

from aiohttp import web

from web.aggregate.state import OwnerAggregateState
from web.constants import AGG_API_DEPS_KEY, AGG_STATE_KEY, RUNTIME_KEY


@dataclass(frozen=True)
class AggregateApiDeps:
    build_bundle: Callable[..., Awaitable[dict[str, Any]]]
    build_pool_snapshot: Callable[
        [dict[str, Any], dict[str, Any], list[dict[str, Any]]], dict[str, Any]
    ]
    compute_fingerprint: Callable[[Any], Awaitable[str]]
    format_timing_ms: Callable[[float], int]


def _json_error(message: str, *, status: int = 400) -> web.Response:
    return web.json_response({"ok": False, "error": message}, status=status)


def _deps(request: web.Request) -> AggregateApiDeps:
    return request.app[AGG_API_DEPS_KEY]


def _owner_audit_user(runtime: Any) -> SimpleNamespace:
    owner_id = int(runtime.admin_service.owner_id)
    return SimpleNamespace(id=owner_id, username="owner", full_name="Owner")


def _build_subscribe_url(request: web.Request, token: str) -> str:
    configured = os.getenv("WEB_ADMIN_PUBLIC_URL", "").strip()
    if configured:
        base = configured.rstrip("/")
        if base.endswith("/admin"):
            base = base[:-6]
        return f"{base}/sub/{token}"
    return f"{request.scheme}://{request.host}/sub/{token}"


def _format_urls_for_token(request: web.Request, token: str) -> dict[str, str]:
    base = _build_subscribe_url(request, token)
    return {"nodes": f"{base}/nodes", "base64": f"{base}/base64", "clash": f"{base}/clash"}


def _cache_has_format(cache: dict[str, Any] | None, format_type: str) -> bool:
    if not isinstance(cache, dict):
        return False
    if format_type == "yaml":
        return bool(cache.get("content"))
    formats = dict(cache.get("formats", {}) or {})
    return bool(formats.get(format_type))


async def _owner_aggregate_info(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    state: OwnerAggregateState = request.app[AGG_STATE_KEY]
    token = await state.get_token()
    cache = await state.read_cache()
    meta = await state.read_meta()
    history = await state.read_history()
    generated_at = int(cache.get("generated_at", 0) or 0) if cache else 0
    return web.json_response(
        {
            "ok": True,
            "data": {
                "url": _build_subscribe_url(request, token),
                "urls": _format_urls_for_token(request, token),
                "token_preview": token[:6],
                "generated_at": generated_at,
                "cache_age_seconds": max(0, int(time.time()) - generated_at) if generated_at else 0,
                "node_count": int(cache.get("node_count", 0) or 0) if cache else 0,
                "version": str(cache.get("version", "") or "") if cache else "",
                "last_error": str(meta.get("last_error", "") or ""),
                "last_error_at": int(meta.get("last_error_at", 0) or 0),
                "build_stats": dict(meta.get("build_stats", {}) or {}),
                "pool_snapshot": dict(meta.get("pool_snapshot", {}) or {}),
                "build_history": history,
                "owner_id": int(runtime.admin_service.owner_id),
            },
        }
    )


async def _owner_aggregate_rotate(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    state: OwnerAggregateState = request.app[AGG_STATE_KEY]
    old_token = await state.get_token()
    try:
        token = await state.rotate_token()
    except ValueError as exc:
        if str(exc) == "rotate_cooldown":
            return _json_error("rotate_cooldown", status=429)
        raise
    runtime.usage_audit_service.log_check(
        user=_owner_audit_user(runtime),
        urls=[f"rotate:{old_token[:8]}->{token[:8]}"],
        source="web:owner:aggregate:rotate",
    )
    return web.json_response(
        {
            "ok": True,
            "data": {
                "url": _build_subscribe_url(request, token),
                "urls": _format_urls_for_token(request, token),
                "token_preview": token[:6],
                "rotated": True,
            },
        }
    )


async def _owner_aggregate_refresh(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    state: OwnerAggregateState = request.app[AGG_STATE_KEY]
    deps = _deps(request)
    token = await state.get_token()
    refresh_started = time.perf_counter()
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
    stats["timings_ms"]["refresh_total"] = deps.format_timing_ms(refresh_started)
    stats["pool_snapshot"] = deps.build_pool_snapshot(
        stats, await state.read_node_health(), stats.get("top_sources", [])
    )
    await state.write_build_stats(stats, snapshot=dict(stats.get("pool_snapshot", {}) or {}))
    runtime.usage_audit_service.log_check(
        user=_owner_audit_user(runtime),
        urls=[f"refresh:{token[:8]} nodes={int(bundle.get('node_count', 0) or 0)}"],
        source="web:owner:aggregate:refresh",
    )
    data = {
        "url": _build_subscribe_url(request, token),
        "urls": _format_urls_for_token(request, token),
        "node_count": int(bundle.get("node_count", 0) or 0),
        "generated_at": int(time.time()),
        "build_stats": stats,
        "pool_snapshot": dict(stats.get("pool_snapshot", {}) or {}),
    }
    return web.json_response({"ok": True, "data": data})


def _public_response(
    format_type: str,
    output_text: str,
    node_count: int,
    cache_valid: bool,
    generated_at: int,
    version: str,
) -> web.Response:
    content_type = "text/yaml" if format_type == "yaml" else "text/plain"
    filename = "owner-pool.yaml" if format_type == "yaml" else "owner-pool.txt"
    resp = web.Response(text=output_text, content_type=content_type, charset="utf-8")
    resp.headers["Content-Disposition"] = f'inline; filename="{filename}"'
    resp.headers["X-Node-Count"] = str(node_count)
    resp.headers["X-Aggregate-Cache"] = "hit" if cache_valid else "miss"
    resp.headers["X-Aggregate-Cache-Age"] = str(
        max(0, int(time.time()) - generated_at) if generated_at else 0
    )
    if version:
        resp.headers["X-Config-Version"] = version
        resp.headers["ETag"] = f'W/"{version}"'
    return resp


async def _public_owner_subscription(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    state: OwnerAggregateState = request.app[AGG_STATE_KEY]
    format_type = (
        request.match_info.get("mode", "").strip().lower()
        or request.query.get("format", "yaml").strip().lower()
    )
    format_type = {"clash": "yaml", "nodes": "raw"}.get(format_type, format_type)
    if format_type not in {"yaml", "base64", "raw"}:
        return _json_error("invalid_format", status=400)
    token = request.match_info.get("token", "").strip()
    if not token or not hmac.compare_digest(token, await state.get_token()):
        raise web.HTTPNotFound()
    cache = await state.read_cache()
    formats = dict((cache or {}).get("formats", {}) or {})
    cache_valid = _cache_has_format(cache, format_type)
    if not cache_valid:
        cache = await _refresh_public_cache(request, runtime, state)
        formats = dict((cache or {}).get("formats", {}) or {})
    yaml_content = str(formats.get("yaml") or (cache or {}).get("content", ""))
    output_text = yaml_content if format_type == "yaml" else str(formats.get(format_type, "") or "")
    node_count = int((cache or {}).get("node_count", 0) or 0)
    generated_at = int((cache or {}).get("generated_at", 0) or 0)
    version = str((cache or {}).get("version", "") or "")
    return _public_response(
        format_type, output_text, node_count, cache_valid, generated_at, version
    )


async def _refresh_public_cache(
    request: web.Request, runtime: Any, state: OwnerAggregateState
) -> dict[str, Any] | None:
    deps = _deps(request)
    try:
        bundle = await deps.build_bundle(runtime, state=state)
        stats = dict(bundle.get("stats", {}) or {})
        stats["fingerprint"] = await deps.compute_fingerprint(runtime)
        await state.write_cache(
            content=str(bundle.get("yaml", "") or ""),
            raw_content=str(bundle.get("raw", "") or ""),
            base64_content=str(bundle.get("base64", "") or ""),
            node_count=int(bundle.get("node_count", 0) or 0),
            fingerprint=str(stats.get("fingerprint", "")),
        )
        await state.write_build_stats(stats, snapshot=dict(stats.get("pool_snapshot", {}) or {}))
        return await state.read_cache()
    except Exception as exc:
        await state.write_error(message=str(exc))
        raise
