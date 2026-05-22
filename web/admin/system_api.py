"""System-level Web Admin API handlers."""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any

from aiohttp import web

from web.constants import AUTH_BACKEND_KEY, RUNTIME_KEY, STARTED_AT_KEY


def _json_error(message: str, *, status: int = 400) -> web.Response:
    return web.json_response({"ok": False, "error": message}, status=status)


async def _runtime_status(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    started_at = request.app[STARTED_AT_KEY]
    now = time.time()
    return web.json_response(
        {
            "ok": True,
            "data": {
                "uptime_seconds": max(0, int(now - started_at)),
                "started_at": int(started_at),
                "run_mode": "unified_async",
                "allow_all_users": runtime.access_service.is_allow_all_users_enabled(),
                "authorized_users": len(runtime.user_manager.get_all()),
                "url_cache_entries": len(runtime.url_cache or {}),
                "parser_ready": runtime.parser is not None,
                "storage_ready": runtime.storage is not None,
                "auth_backend": getattr(request.app[AUTH_BACKEND_KEY], "name", "unknown"),
            },
        }
    )


def _extract_overview(runtime: Any) -> dict[str, Any]:
    data = runtime.admin_service.get_owner_panel_data()
    return {"ok": True, "data": data}


async def _system_overview(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    try:
        payload = await asyncio.to_thread(_extract_overview, runtime)
        return web.json_response(payload)
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def _set_public_access(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    try:
        payload = await request.json()
    except Exception:
        return _json_error("invalid_payload", status=400)
    enabled = bool(payload.get("enabled"))
    changed, saved = await asyncio.to_thread(runtime.access_service.set_allow_all_users, enabled)
    if not saved:
        return _json_error("save_failed", status=500)
    current_enabled = await asyncio.to_thread(runtime.access_service.is_allow_all_users_enabled)
    return web.json_response(
        {"ok": True, "data": {"changed": bool(changed), "enabled": bool(current_enabled)}}
    )


async def _revoke_all_sessions(request: web.Request) -> web.Response:
    backend = request.app[AUTH_BACKEND_KEY]
    clear_all = getattr(backend, "clear_all_sessions", None)
    if clear_all is None:
        return _json_error("revoke_not_supported", status=400)
    try:
        if inspect.iscoroutinefunction(clear_all):
            deleted = await clear_all()
        else:
            deleted = clear_all()
            if inspect.isawaitable(deleted):
                deleted = await deleted
        return web.json_response({"ok": True, "data": {"revoked": int(deleted or 0)}})
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)
