"""Subscription-focused Web Admin API handlers."""

from __future__ import annotations

import asyncio

from aiohttp import web

from web.admin.users_api import _parse_limit, _parse_positive_int
from web.constants import RUNTIME_KEY


async def _subscriptions_global(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    max_users, err = _parse_positive_int(request, "max_users", 8, 1, 200)
    if err is not None:
        return err
    max_subs_per_user, err = _parse_positive_int(request, "max_subs_per_user", 4, 1, 100)
    if err is not None:
        return err
    try:
        data = await asyncio.to_thread(
            runtime.admin_service.get_globallist_data,
            max_users=max_users,
            max_subs_per_user=max_subs_per_user,
        )
        return web.json_response({"ok": True, "data": data})
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def _subscriptions_available(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    page, err = _parse_positive_int(request, "page", 1, 1, 10000)
    if err is not None:
        return err
    limit, err = _parse_limit(request, default=20, minimum=1, maximum=200)
    if err is not None:
        return err
    try:
        data = await asyncio.to_thread(
            runtime.admin_service.get_available_subscriptions_data, page=page, limit=limit
        )
        return web.json_response({"ok": True, "data": data})
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)
