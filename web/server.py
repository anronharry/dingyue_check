"""Lightweight aiohttp-based web admin server."""
from __future__ import annotations

import hmac
import io
import json
import logging
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
import csv

from aiohttp import web


API_PREFIX = "/api/v1"
SESSION_COOKIE = "web_admin_session"
LOGIN_WINDOW_SECONDS = 600
MAX_LOGIN_ATTEMPTS = 10
logger = logging.getLogger(__name__)

RUNTIME_KEY = web.AppKey("runtime", object)
TOKEN_KEY = web.AppKey("web_admin_token", str)
USERNAME_KEY = web.AppKey("web_admin_username", str)
ALLOW_HEADER_TOKEN_KEY = web.AppKey("web_admin_allow_header_token", bool)
COOKIE_SECURE_KEY = web.AppKey("web_admin_cookie_secure", bool)
TRUST_PROXY_KEY = web.AppKey("web_admin_trust_proxy", bool)
LOGIN_WINDOW_KEY = web.AppKey("web_admin_login_window_seconds", int)
LOGIN_MAX_ATTEMPTS_KEY = web.AppKey("web_admin_login_max_attempts", int)
SESSION_TTL_KEY = web.AppKey("web_admin_session_ttl", int)
AUTH_BACKEND_KEY = web.AppKey("web_admin_auth_backend", object)
STARTED_AT_KEY = web.AppKey("web_admin_started_at", float)


class MemoryAuthBackend:
    """In-memory auth/session backend for single-process deployment."""

    name = "memory"

    def __init__(self):
        self._sessions: dict[str, float] = {}
        self._login_hits: dict[str, list[float]] = {}

    async def create_session(self, *, username: str, ttl_seconds: int) -> str:
        del username
        sid = secrets.token_urlsafe(32)
        self._sessions[sid] = time.time() + max(60, ttl_seconds)
        return sid

    async def is_session_valid(self, sid: str) -> bool:
        if not sid:
            return False
        now = time.time()
        expires_at = self._sessions.get(sid, 0)
        if expires_at <= now:
            self._sessions.pop(sid, None)
            return False
        return True

    async def delete_session(self, sid: str) -> None:
        if sid:
            self._sessions.pop(sid, None)

    async def allow_login_attempt(self, *, ip: str, window_seconds: int, max_attempts: int) -> bool:
        now = time.time()
        hits = [ts for ts in self._login_hits.get(ip, []) if now - ts <= window_seconds]
        if len(hits) >= max_attempts:
            self._login_hits[ip] = hits
            return False
        hits.append(now)
        self._login_hits[ip] = hits
        return True

    async def close(self) -> None:
        return None

    async def clear_all_sessions(self) -> int:
        count = len(self._sessions)
        self._sessions.clear()
        return count


class RedisAuthBackend:
    """Redis-backed auth/session backend for multi-instance deployment."""

    name = "redis"

    def __init__(self, redis_client):
        self._redis = redis_client

    @staticmethod
    def _session_key(sid: str) -> str:
        return f"webadmin:sess:{sid}"

    @staticmethod
    def _rate_key(ip: str) -> str:
        return f"webadmin:rate:{ip}"

    async def create_session(self, *, username: str, ttl_seconds: int) -> str:
        sid = secrets.token_urlsafe(32)
        await self._redis.setex(self._session_key(sid), max(60, ttl_seconds), username)
        return sid

    async def is_session_valid(self, sid: str) -> bool:
        if not sid:
            return False
        return bool(await self._redis.exists(self._session_key(sid)))

    async def delete_session(self, sid: str) -> None:
        if sid:
            await self._redis.delete(self._session_key(sid))

    async def allow_login_attempt(self, *, ip: str, window_seconds: int, max_attempts: int) -> bool:
        key = self._rate_key(ip)
        count = int(await self._redis.incr(key))
        if count == 1:
            await self._redis.expire(key, max(60, window_seconds))
        return count <= max_attempts

    async def close(self) -> None:
        close = getattr(self._redis, "aclose", None) or getattr(self._redis, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result

    async def clear_all_sessions(self) -> int:
        deleted = 0
        async for key in self._redis.scan_iter(match="webadmin:sess:*", count=200):
            deleted += int(await self._redis.delete(key))
        return deleted


def _build_auth_backend(redis_url: str | None):
    redis_url = (redis_url or "").strip()
    if not redis_url:
        logger.info("Web auth backend: memory")
        return MemoryAuthBackend()

    try:
        import redis.asyncio as redis  # type: ignore

        client = redis.from_url(redis_url, decode_responses=True)
        logger.info("Web auth backend: redis (%s)", redis_url)
        return RedisAuthBackend(client)
    except Exception as exc:
        logger.warning("Redis auth backend unavailable, falling back to memory. reason=%s", exc)
        return MemoryAuthBackend()


def _get_admin_static_dir() -> Path:
    return Path(__file__).resolve().parent / "static"


def _is_api_path(path: str) -> bool:
    return path.startswith(API_PREFIX)


def _is_protected_path(path: str) -> bool:
    if path in {"/admin/login", "/admin/login/", "/healthz"}:
        return False
    return path.startswith("/admin") or _is_api_path(path)


def _json_error(message: str, *, status: int = 400) -> web.Response:
    return web.json_response({"ok": False, "error": message}, status=status)


def _has_valid_header_token(request: web.Request) -> bool:
    if not request.app[ALLOW_HEADER_TOKEN_KEY]:
        return False
    token = request.app[TOKEN_KEY]
    if not token:
        return False
    supplied = request.headers.get("X-Admin-Token", "")
    return hmac.compare_digest(supplied, token)


def _client_ip(request: web.Request) -> str:
    if request.app[TRUST_PROXY_KEY]:
        xff = request.headers.get("X-Forwarded-For", "")
        if xff:
            first = xff.split(",", 1)[0].strip()
            if first:
                return first
    return request.remote or "unknown"


@web.middleware
async def _security_headers_middleware(request: web.Request, handler):
    response = await handler(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Cache-Control"] = "no-store"
    return response


@web.middleware
async def _auth_middleware(request: web.Request, handler):
    path = request.path
    if not _is_protected_path(path):
        return await handler(request)

    token = request.app[TOKEN_KEY]
    if not token:
        if _is_api_path(path):
            return _json_error("web_admin_token_not_configured", status=503)
        return web.Response(status=503, text="Web admin token is not configured.")

    backend = request.app[AUTH_BACKEND_KEY]
    sid = request.cookies.get(SESSION_COOKIE, "")
    if _has_valid_header_token(request) or await backend.is_session_valid(sid):
        return await handler(request)

    if _is_api_path(path):
        return _json_error("unauthorized", status=401)

    if request.method == "GET":
        raise web.HTTPFound("/admin/login")
    return web.Response(status=401, text="Unauthorized")


async def _issue_session(response: web.Response, *, request: web.Request, username: str) -> None:
    backend = request.app[AUTH_BACKEND_KEY]
    sid = await backend.create_session(
        username=username,
        ttl_seconds=request.app[SESSION_TTL_KEY],
    )
    response.set_cookie(
        SESSION_COOKIE,
        sid,
        httponly=True,
        secure=request.app[COOKIE_SECURE_KEY],
        samesite="Lax",
        max_age=max(60, request.app[SESSION_TTL_KEY]),
        path="/",
    )


async def _login_page(_request: web.Request) -> web.FileResponse:
    static_dir = _get_admin_static_dir()
    return web.FileResponse(static_dir / "login.html")


async def _admin_index(_request: web.Request) -> web.FileResponse:
    static_dir = _get_admin_static_dir()
    return web.FileResponse(static_dir / "index.html")


async def _login(request: web.Request) -> web.Response:
    backend = request.app[AUTH_BACKEND_KEY]
    allowed = await backend.allow_login_attempt(
        ip=_client_ip(request),
        window_seconds=request.app[LOGIN_WINDOW_KEY],
        max_attempts=request.app[LOGIN_MAX_ATTEMPTS_KEY],
    )
    if not allowed:
        logger.warning("Web login blocked by rate limit ip=%s", _client_ip(request))
        return _json_error("too_many_attempts", status=429)
    try:
        payload = await request.json()
    except Exception:
        payload = await request.post()

    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    expected_user = request.app[USERNAME_KEY]
    expected_pass = request.app[TOKEN_KEY]
    if not expected_pass:
        return _json_error("web_admin_token_not_configured", status=503)
    if not (hmac.compare_digest(username, expected_user) and hmac.compare_digest(password, expected_pass)):
        logger.warning("Web login failed ip=%s username=%s", _client_ip(request), username or "<empty>")
        return _json_error("invalid_credentials", status=401)

    resp = web.json_response({"ok": True, "redirect": "/admin"})
    await _issue_session(resp, request=request, username=username)
    logger.info("Web login success ip=%s username=%s", _client_ip(request), username)
    return resp


async def _logout(request: web.Request) -> web.Response:
    sid = request.cookies.get(SESSION_COOKIE, "")
    backend = request.app[AUTH_BACKEND_KEY]
    if sid:
        await backend.delete_session(sid)
    resp = web.json_response({"ok": True})
    resp.del_cookie(SESSION_COOKIE, path="/")
    logger.info("Web logout ip=%s", _client_ip(request))
    return resp


async def _healthz(request: web.Request) -> web.Response:
    backend = request.app[AUTH_BACKEND_KEY]
    return web.json_response(
        {
            "ok": True,
            "service": "web-admin",
            "security": {
                "cookie_secure": request.app[COOKIE_SECURE_KEY],
                "allow_header_token": request.app[ALLOW_HEADER_TOKEN_KEY],
                "trust_proxy": request.app[TRUST_PROXY_KEY],
                "login_window_seconds": request.app[LOGIN_WINDOW_KEY],
                "login_max_attempts": request.app[LOGIN_MAX_ATTEMPTS_KEY],
            },
            "auth_backend": getattr(backend, "name", "unknown"),
        }
    )


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
        payload = _extract_overview(runtime)
        return web.json_response(payload)
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


def _parse_scope(request: web.Request) -> tuple[bool, web.Response | None]:
    scope = request.query.get("scope", "others").strip().lower()
    if scope not in {"others", "all"}:
        return False, _json_error("invalid_scope", status=400)
    return scope == "all", None


def _parse_limit(request: web.Request, *, default: int = 10, minimum: int = 1, maximum: int = 100) -> tuple[int, web.Response | None]:
    raw = request.query.get("limit", str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        return 0, _json_error("invalid_limit", status=400)
    if value < minimum or value > maximum:
        return 0, _json_error("limit_out_of_range", status=400)
    return value, None


def _parse_datetime_text(value: str | None) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _format_identity(runtime: Any, uid: int | None) -> str:
    return runtime.user_profile_service.format_user_identity(uid)


def _collect_check_rows(
    runtime: Any,
    *,
    mode: str,
    limit: int,
    query_text: str = "",
    source: str = "",
    user_id: int | None = None,
    dt_from: datetime | None = None,
    dt_to: datetime | None = None,
) -> dict[str, Any]:
    service = runtime.usage_audit_service
    source_records = list(reversed(service.get_recent_records(limit=service.max_read_records)))
    rows = service.query_records(
        owner_id=runtime.admin_service.owner_id,
        mode=mode,
        page=1,
        page_size=max(1, len(source_records) or 1),
        records=source_records,
    )["records"]

    query_text = query_text.strip().lower()
    source = source.strip().lower()
    filtered: list[dict[str, Any]] = []
    for row in rows:
        uid = row.get("user_id")
        if user_id is not None and uid != user_id:
            continue
        row_source = str(row.get("source", ""))
        if source and source not in row_source.lower():
            continue
        ts = _parse_datetime_text(row.get("ts"))
        if dt_from and (ts is None or ts < dt_from):
            continue
        if dt_to and (ts is None or ts > dt_to):
            continue
        urls = [str(u) for u in (row.get("urls") or []) if str(u).strip()]
        identity = _format_identity(runtime, uid if isinstance(uid, int) else None)
        if query_text:
            haystack = " ".join([identity, row_source, " ".join(urls), str(uid or "")]).lower()
            if query_text not in haystack:
                continue
        filtered.append(
            {
                "user_id": uid if isinstance(uid, int) else 0,
                "identity": identity,
                "ts": row.get("ts", "-"),
                "source": row_source,
                "url_count": len(urls),
                "urls": urls,
            }
        )

    return {"mode": mode, "total": len(filtered), "rows": filtered[: max(1, limit)]}


async def _recent_users(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    include_owner, err = _parse_scope(request)
    if err is not None:
        return err
    limit, err = _parse_limit(request, default=10)
    if err is not None:
        return err
    try:
        data = runtime.admin_service.get_recent_users_summary(include_owner=include_owner, limit=limit)
        return web.json_response({"ok": True, "data": data})
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def _recent_exports(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    include_owner, err = _parse_scope(request)
    if err is not None:
        return err
    limit, err = _parse_limit(request, default=10)
    if err is not None:
        return err
    try:
        data = runtime.admin_service.get_recent_exports_summary(include_owner=include_owner, limit=limit)
        return web.json_response({"ok": True, "data": data})
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def _audit_summary(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    mode = request.query.get("mode", "others").strip().lower()
    if mode not in {"others", "owner", "all"}:
        return _json_error("invalid_mode", status=400)
    try:
        data = runtime.admin_service.get_usage_audit_summary(mode=mode)
        return web.json_response({"ok": True, "data": data})
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


def _parse_positive_int(request: web.Request, name: str, default: int, minimum: int, maximum: int) -> tuple[int, web.Response | None]:
    raw = request.query.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        return 0, _json_error(f"invalid_{name}", status=400)
    if value < minimum or value > maximum:
        return 0, _json_error(f"{name}_out_of_range", status=400)
    return value, None


async def _subscriptions_global(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    max_users, err = _parse_positive_int(request, "max_users", 8, 1, 200)
    if err is not None:
        return err
    max_subs_per_user, err = _parse_positive_int(request, "max_subs_per_user", 4, 1, 100)
    if err is not None:
        return err
    try:
        data = runtime.admin_service.get_globallist_data(
            max_users=max_users,
            max_subs_per_user=max_subs_per_user,
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
        data = runtime.admin_service.get_user_list_data(page=page, limit=limit)
        return web.json_response({"ok": True, "data": data})
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def _recent_checks(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    mode = request.query.get("mode", "others").strip().lower()
    if mode not in {"others", "owner", "all"}:
        return _json_error("invalid_mode", status=400)
    limit, err = _parse_limit(request, default=20, maximum=200)
    if err is not None:
        return err
    query_text = request.query.get("q", "")
    source = request.query.get("source", "")
    raw_uid = request.query.get("user_id", "").strip()
    user_id: int | None = None
    if raw_uid:
        try:
            user_id = int(raw_uid)
        except ValueError:
            return _json_error("invalid_user_id", status=400)
    dt_from = _parse_datetime_text(request.query.get("from"))
    dt_to = _parse_datetime_text(request.query.get("to"))
    try:
        data = _collect_check_rows(
            runtime,
            mode=mode,
            limit=limit,
            query_text=query_text,
            source=source,
            user_id=user_id,
            dt_from=dt_from,
            dt_to=dt_to,
        )
        return web.json_response({"ok": True, "data": data})
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def _user_detail(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    raw_uid = request.query.get("uid", "").strip()
    if not raw_uid:
        return _json_error("uid_required", status=400)
    try:
        uid = int(raw_uid)
    except ValueError:
        return _json_error("invalid_uid", status=400)
    if uid <= 0:
        return _json_error("invalid_uid", status=400)

    try:
        profile = runtime.user_profile_service.get_profile(uid) or {}
        is_owner = runtime.access_service.is_owner_uid(uid)
        is_authorized = runtime.access_service.is_authorized_uid(uid)
        subs = runtime.get_storage().get_by_user(uid)
        sorted_subs = sorted(
            subs.items(),
            key=lambda item: item[1].get("updated_at", ""),
            reverse=True,
        )
        sub_rows = []
        for url, data in sorted_subs[:20]:
            sub_rows.append(
                {
                    "name": data.get("name", "未命名"),
                    "url": url,
                    "updated_at": data.get("updated_at", "-"),
                    "expire_time": data.get("expire_time", "-"),
                }
            )
        checks = _collect_check_rows(runtime, mode="all", limit=200, user_id=uid)["rows"][:20]
        audit_records = list(reversed(runtime.usage_audit_service.get_recent_records(limit=runtime.usage_audit_service.max_read_records)))
        export_records = runtime.usage_audit_service.query_by_source_prefix(
            prefix="导出缓存:",
            limit=200,
            owner_id=runtime.admin_service.owner_id,
            include_owner=True,
            records=audit_records,
        )
        user_exports = []
        for row in export_records:
            if row.get("user_id") != uid:
                continue
            urls = row.get("urls") or []
            first_url = str(urls[0] if urls else "-")
            user_exports.append(
                {
                    "identity": _format_identity(runtime, uid),
                    "ts": row.get("ts", "-"),
                    "fmt": str(row.get("source", "-").split(":", 1)[-1].upper()),
                    "target": first_url[:120] + ("..." if len(first_url) > 120 else ""),
                }
            )
            if len(user_exports) >= 20:
                break
        return web.json_response(
            {
                "ok": True,
                "data": {
                    "uid": uid,
                    "identity": _format_identity(runtime, uid),
                    "username": profile.get("username"),
                    "full_name": profile.get("full_name"),
                    "last_seen": profile.get("last_seen_at", "-"),
                    "last_source": profile.get("last_source", "-"),
                    "is_owner": is_owner,
                    "is_authorized": is_authorized,
                    "subscription_count": len(subs),
                    "subscriptions": sub_rows,
                    "recent_checks": checks,
                    "recent_exports": user_exports,
                },
            }
        )
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
            changed = runtime.user_manager.add_user(uid)
        else:
            changed = runtime.user_manager.remove_user(uid)
        return web.json_response(
            {
                "ok": True,
                "data": {
                    "uid": uid,
                    "enabled": runtime.access_service.is_authorized_uid(uid),
                    "changed": bool(changed),
                },
            }
        )
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def _set_public_access(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    try:
        payload = await request.json()
    except Exception:
        return _json_error("invalid_payload", status=400)
    enabled = bool(payload.get("enabled"))
    changed, current = runtime.access_service.set_allow_all_users(enabled)
    return web.json_response({"ok": True, "data": {"changed": bool(changed), "enabled": bool(current)}})


async def _revoke_all_sessions(request: web.Request) -> web.Response:
    backend = request.app[AUTH_BACKEND_KEY]
    clear_all = getattr(backend, "clear_all_sessions", None)
    if clear_all is None:
        return _json_error("revoke_not_supported", status=400)
    try:
        deleted = clear_all()
        if hasattr(deleted, "__await__"):
            deleted = await deleted
        return web.json_response({"ok": True, "data": {"revoked": int(deleted or 0)}})
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def _audit_alerts(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    hf_threshold, err = _parse_positive_int(request, "high_freq_threshold", 12, 1, 500)
    if err is not None:
        return err
    url_threshold, err = _parse_positive_int(request, "high_url_threshold", 40, 1, 2000)
    if err is not None:
        return err
    rows = _collect_check_rows(runtime, mode="all", limit=10000)["rows"]
    cutoff = datetime.now() - timedelta(hours=24)
    recent = []
    for row in rows:
        ts = _parse_datetime_text(row.get("ts"))
        if ts and ts >= cutoff:
            recent.append(row)

    bucket: dict[int, dict[str, Any]] = {}
    for row in recent:
        uid = int(row.get("user_id", 0) or 0)
        item = bucket.setdefault(uid, {"checks": 0, "urls": 0, "identity": row.get("identity", "-")})
        item["checks"] += 1
        item["urls"] += int(row.get("url_count", 0) or 0)

    alerts: list[dict[str, Any]] = []
    if runtime.access_service.is_allow_all_users_enabled():
        alerts.append({"severity": "high", "title": "公开访问已开启", "detail": "当前 allow_all_users=true，建议仅临时使用。"})
    if request.app[ALLOW_HEADER_TOKEN_KEY]:
        alerts.append({"severity": "medium", "title": "Header Token 已开启", "detail": "建议仅在必须的自动化场景开启。"})
    if not request.app[COOKIE_SECURE_KEY]:
        alerts.append({"severity": "medium", "title": "Cookie Secure 未开启", "detail": "HTTPS 场景建议启用 WEB_ADMIN_COOKIE_SECURE=true。"})

    for uid, item in sorted(bucket.items(), key=lambda x: (-x[1]["checks"], -x[1]["urls"]))[:20]:
        if item["checks"] >= hf_threshold:
            alerts.append(
                {
                    "severity": "medium",
                    "title": "高频检测用户",
                    "detail": f"{item['identity']} 24h 检测 {item['checks']} 次。",
                    "uid": uid,
                }
            )
        if item["urls"] >= url_threshold:
            alerts.append(
                {
                    "severity": "medium",
                    "title": "高 URL 量用户",
                    "detail": f"{item['identity']} 24h 检测 URL 共 {item['urls']} 个。",
                    "uid": uid,
                }
            )

    return web.json_response(
        {
            "ok": True,
            "data": {
                "window_hours": 24,
                "alerts": alerts,
                "recent_check_rows": len(recent),
            },
        }
    )


def _build_export_rows(runtime: Any, request: web.Request) -> tuple[list[dict[str, Any]], web.Response | None]:
    mode = request.query.get("mode", "others").strip().lower()
    if mode not in {"others", "owner", "all"}:
        return [], _json_error("invalid_mode", status=400)
    limit, err = _parse_limit(request, default=300, maximum=2000)
    if err is not None:
        return [], err
    raw_uid = request.query.get("user_id", "").strip()
    user_id: int | None = None
    if raw_uid:
        try:
            user_id = int(raw_uid)
        except ValueError:
            return [], _json_error("invalid_user_id", status=400)
    dt_from = _parse_datetime_text(request.query.get("from"))
    dt_to = _parse_datetime_text(request.query.get("to"))
    data = _collect_check_rows(
        runtime,
        mode=mode,
        limit=limit,
        query_text=request.query.get("q", ""),
        source=request.query.get("source", ""),
        user_id=user_id,
        dt_from=dt_from,
        dt_to=dt_to,
    )
    return data.get("rows", []), None


async def _audit_export(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    fmt = request.query.get("format", "csv").strip().lower()
    rows, err = _build_export_rows(runtime, request)
    if err is not None:
        return err
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if fmt == "json":
        body = json.dumps(rows, ensure_ascii=False, indent=2)
        return web.Response(
            text=body,
            content_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="audit_checks_{ts}.json"'},
        )
    if fmt != "csv":
        return _json_error("invalid_format", status=400)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["user_id", "identity", "ts", "source", "url_count", "urls"])
    for row in rows:
        writer.writerow(
            [
                row.get("user_id", 0),
                row.get("identity", "-"),
                row.get("ts", "-"),
                row.get("source", "-"),
                row.get("url_count", 0),
                "\n".join(row.get("urls", [])),
            ]
        )
    return web.Response(
        text=output.getvalue(),
        content_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="audit_checks_{ts}.csv"'},
    )


async def _close_auth_backend(app: web.Application) -> None:
    backend = app[AUTH_BACKEND_KEY]
    close = getattr(backend, "close", None)
    if close is not None:
        result = close()
        if hasattr(result, "__await__"):
            await result


def build_web_app(
    *,
    runtime: Any,
    web_admin_token: str,
    web_admin_username: str = "admin",
    web_admin_session_ttl_seconds: int = 28800,
    web_admin_allow_header_token: bool = True,
    web_admin_cookie_secure: bool = False,
    web_admin_trust_proxy: bool = False,
    web_admin_login_window_seconds: int = LOGIN_WINDOW_SECONDS,
    web_admin_login_max_attempts: int = MAX_LOGIN_ATTEMPTS,
    web_admin_redis_url: str = "",
) -> web.Application:
    app = web.Application(middlewares=[_auth_middleware, _security_headers_middleware])
    app[RUNTIME_KEY] = runtime
    app[TOKEN_KEY] = web_admin_token
    app[USERNAME_KEY] = web_admin_username
    app[SESSION_TTL_KEY] = max(60, web_admin_session_ttl_seconds)
    app[ALLOW_HEADER_TOKEN_KEY] = web_admin_allow_header_token
    app[COOKIE_SECURE_KEY] = web_admin_cookie_secure
    app[TRUST_PROXY_KEY] = web_admin_trust_proxy
    app[LOGIN_WINDOW_KEY] = max(60, web_admin_login_window_seconds)
    app[LOGIN_MAX_ATTEMPTS_KEY] = max(1, web_admin_login_max_attempts)
    app[AUTH_BACKEND_KEY] = _build_auth_backend(web_admin_redis_url)
    app[STARTED_AT_KEY] = time.time()
    app.on_cleanup.append(_close_auth_backend)

    static_dir = _get_admin_static_dir()
    app.router.add_get("/healthz", _healthz)
    app.router.add_get("/admin/login", _login_page)
    app.router.add_post("/admin/login", _login)
    app.router.add_post("/admin/logout", _logout)
    app.router.add_get("/admin", _admin_index)
    app.router.add_get("/admin/", _admin_index)
    app.router.add_get(f"{API_PREFIX}/system/overview", _system_overview)
    app.router.add_get(f"{API_PREFIX}/users/recent", _recent_users)
    app.router.add_get(f"{API_PREFIX}/exports/recent", _recent_exports)
    app.router.add_get(f"{API_PREFIX}/audit/summary", _audit_summary)
    app.router.add_get(f"{API_PREFIX}/subscriptions/global", _subscriptions_global)
    app.router.add_get(f"{API_PREFIX}/users/authorized", _authorized_users)
    app.router.add_get(f"{API_PREFIX}/audit/recent-checks", _recent_checks)
    app.router.add_get(f"{API_PREFIX}/system/runtime", _runtime_status)
    app.router.add_get(f"{API_PREFIX}/users/detail", _user_detail)
    app.router.add_post(f"{API_PREFIX}/users/access", _set_user_access)
    app.router.add_post(f"{API_PREFIX}/system/public-access", _set_public_access)
    app.router.add_post(f"{API_PREFIX}/system/sessions/revoke-all", _revoke_all_sessions)
    app.router.add_get(f"{API_PREFIX}/audit/alerts", _audit_alerts)
    app.router.add_get(f"{API_PREFIX}/audit/export", _audit_export)
    app.router.add_static("/admin/static/", path=static_dir, show_index=False)
    return app
