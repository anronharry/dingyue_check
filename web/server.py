"""Lightweight aiohttp-based web admin server."""
from __future__ import annotations

import hmac
import logging
import secrets
import time
from pathlib import Path
from typing import Any

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
    app.router.add_static("/admin/static/", path=static_dir, show_index=False)
    return app
