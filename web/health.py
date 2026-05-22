"""Health endpoint handlers for the web admin server."""

from __future__ import annotations

from aiohttp import web

from web.constants import (
    ALLOW_HEADER_TOKEN_KEY,
    AUTH_BACKEND_KEY,
    COOKIE_SECURE_KEY,
    LOGIN_MAX_ATTEMPTS_KEY,
    LOGIN_WINDOW_KEY,
    TRUST_PROXY_KEY,
)


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
