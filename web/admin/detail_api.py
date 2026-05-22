"""User detail Web Admin API handler."""

from __future__ import annotations

from typing import Any

from aiohttp import web

from web.admin.audit_api import _collect_check_rows_async, _format_identity
from web.admin.users_api import _json_error
from web.constants import RUNTIME_KEY


def _parse_uid(request: web.Request) -> tuple[int, web.Response | None]:
    raw_uid = request.query.get("uid", "").strip()
    if not raw_uid:
        return 0, _json_error("uid_required", status=400)
    try:
        uid = int(raw_uid)
    except ValueError:
        return 0, _json_error("invalid_uid", status=400)
    if uid <= 0:
        return 0, _json_error("invalid_uid", status=400)
    return uid, None


def _subscription_rows(subs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    sorted_subs = sorted(subs.items(), key=lambda item: item[1].get("updated_at", ""), reverse=True)
    rows = []
    for url, data in sorted_subs[:20]:
        rows.append(
            {
                "name": data.get("name", "未命名"),
                "url": url,
                "updated_at": data.get("updated_at", "-"),
                "expire_time": data.get("expire_time", "-"),
            }
        )
    return rows


def _export_rows(runtime: Any, uid: int, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in records:
        if row.get("user_id") != uid:
            continue
        urls = row.get("urls") or []
        first_url = str(urls[0] if urls else "-")
        rows.append(
            {
                "identity": _format_identity(runtime, uid),
                "ts": row.get("ts", "-"),
                "fmt": str(row.get("source", "-").split(":", 1)[-1].upper()),
                "target": first_url[:120] + ("..." if len(first_url) > 120 else ""),
            }
        )
    return rows


async def _recent_user_exports(runtime: Any, uid: int) -> list[dict[str, Any]]:
    records = await runtime.usage_audit_service.aquery_by_source_prefix(
        prefix="导出缓存:",
        limit=20,
        owner_id=runtime.admin_service.owner_id,
        include_owner=True,
    )
    return _export_rows(runtime, uid, records)


async def _build_user_detail(runtime: Any, uid: int) -> dict[str, Any]:
    profile = runtime.user_profile_service.get_profile(uid) or {}
    subs = runtime.get_storage().get_by_user(uid)
    checks_data = await _collect_check_rows_async(runtime, mode="all", limit=20, user_id=uid)
    return {
        "uid": uid,
        "identity": _format_identity(runtime, uid),
        "username": profile.get("username"),
        "full_name": profile.get("full_name"),
        "last_seen": profile.get("last_seen_at", "-"),
        "last_source": profile.get("last_source", "-"),
        "is_owner": runtime.access_service.is_owner_uid(uid),
        "is_authorized": runtime.access_service.is_authorized_uid(uid),
        "subscription_count": len(subs),
        "subscriptions": _subscription_rows(subs),
        "recent_checks": checks_data["rows"],
        "recent_exports": await _recent_user_exports(runtime, uid),
    }


async def _user_detail(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    uid, err = _parse_uid(request)
    if err is not None:
        return err
    try:
        return web.json_response({"ok": True, "data": await _build_user_detail(runtime, uid)})
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)
