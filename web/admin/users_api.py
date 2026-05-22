"""User-focused Web Admin API handlers."""

from __future__ import annotations

import asyncio

from aiohttp import web

from web.constants import RUNTIME_KEY


def _json_error(message: str, *, status: int = 400) -> web.Response:
    return web.json_response({"ok": False, "error": message}, status=status)


def _json_exception(code: str, exc: Exception, *, status: int = 500) -> web.Response:
    return web.json_response(
        {"ok": False, "error": {"code": code, "message": str(exc)}},
        status=status,
    )


def _parse_scope(request: web.Request) -> tuple[bool, web.Response | None]:
    scope = request.query.get("scope", "others").strip().lower()
    if scope not in {"others", "all"}:
        return False, _json_error("invalid_scope", status=400)
    return scope == "all", None


def _parse_limit(
    request: web.Request,
    *,
    default: int = 10,
    minimum: int = 1,
    maximum: int = 100,
) -> tuple[int, web.Response | None]:
    raw = request.query.get("limit", str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        return 0, _json_error("invalid_limit", status=400)
    if value < minimum or value > maximum:
        return 0, _json_error("limit_out_of_range", status=400)
    return value, None


def _parse_positive_int(
    request: web.Request,
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> tuple[int, web.Response | None]:
    raw = request.query.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        return 0, _json_error(f"invalid_{name}", status=400)
    if value < minimum or value > maximum:
        return 0, _json_error(f"{name}_out_of_range", status=400)
    return value, None


async def _recent_users(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    include_owner, err = _parse_scope(request)
    if err is not None:
        return err
    limit, err = _parse_limit(request, default=10)
    if err is not None:
        return err
    try:
        data = await asyncio.to_thread(
            runtime.admin_service.get_recent_users_summary,
            include_owner=include_owner,
            limit=limit,
        )
        return web.json_response({"ok": True, "data": data})
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def _authorized_users(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    page, err = _parse_positive_int(request, "page", 1, 1, 10000)
    if err is not None:
        return err
    limit, err = _parse_limit(request, default=10, minimum=1, maximum=100)
    if err is not None:
        return err
    try:
        data = await asyncio.to_thread(
            runtime.admin_service.get_user_list_data, page=page, limit=limit
        )
        return web.json_response({"ok": True, "data": data})
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def _recent_exports(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    include_owner, err = _parse_scope(request)
    if err is not None:
        return err
    page, err = _parse_positive_int(request, "page", 1, 1, 10000)
    if err is not None:
        return err
    limit, err = _parse_limit(request, default=10)
    if err is not None:
        return err
    try:
        data = await asyncio.to_thread(
            runtime.admin_service.get_recent_exports_summary,
            include_owner=include_owner,
            page=page,
            limit=limit,
        )
        return web.json_response({"ok": True, "data": data})
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def _set_user_access(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    try:
        payload = await request.json()
    except Exception:
        return _json_error("invalid_payload", status=400)
    raw_uid = str(payload.get("uid", "")).strip()
    enabled = bool(payload.get("enabled"))
    if not raw_uid:
        return _json_error("uid_required", status=400)
    try:
        uid = int(raw_uid)
    except ValueError:
        return _json_error("invalid_uid", status=400)
    if uid <= 0:
        return _json_error("invalid_uid", status=400)
    try:
        if enabled:
            changed = await asyncio.to_thread(runtime.user_manager.add_user, uid)
        else:
            changed = await asyncio.to_thread(runtime.user_manager.remove_user, uid)
        current_enabled = await asyncio.to_thread(runtime.access_service.is_authorized_uid, uid)
        return web.json_response(
            {"ok": True, "data": {"uid": uid, "enabled": current_enabled, "changed": bool(changed)}}
        )
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)
