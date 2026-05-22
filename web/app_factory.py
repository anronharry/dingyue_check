"""Application factory for the aiohttp web admin server."""

from __future__ import annotations

import time
from typing import Any

from aiohttp import web

from web.admin.audit_api import _audit_alerts, _audit_export, _audit_summary, _recent_checks
from web.admin.detail_api import _user_detail
from web.admin.owner_api import (
    _owner_backup_download,
    _owner_check_all,
    _owner_export_json,
    _owner_import_json,
    _owner_restore_backup,
)
from web.admin.subscriptions_api import _subscriptions_available, _subscriptions_global
from web.admin.system_api import (
    _revoke_all_sessions,
    _runtime_status,
    _set_public_access,
    _system_overview,
)
from web.admin.users_api import _authorized_users, _recent_exports, _recent_users, _set_user_access
from web.aggregate.api import (
    AggregateApiDeps,
    _owner_aggregate_info,
    _owner_aggregate_refresh,
    _owner_aggregate_rotate,
    _public_owner_subscription,
)
from web.aggregate.lifecycle import (
    _aggregate_state_file,
    _close_auth_backend,
    _start_background_tasks,
    _validate_auth_backend,
)
from web.aggregate.rendering import _build_pool_snapshot, _format_timing_ms
from web.aggregate.service import _build_owner_aggregate_bundle, _compute_owner_fingerprint
from web.aggregate.state import OwnerAggregateState
from web.auth import build_auth_backend as _build_auth_backend, require_secret as _require_secret
from web.constants import (
    AGG_API_DEPS_KEY,
    AGG_STATE_KEY,
    ALLOW_HEADER_TOKEN_KEY,
    API_PREFIX,
    AUTH_BACKEND_KEY,
    COOKIE_SECURE_KEY,
    LOGIN_MAX_ATTEMPTS_KEY,
    LOGIN_WINDOW_KEY,
    LOGIN_WINDOW_SECONDS,
    MAX_LOGIN_ATTEMPTS,
    REDIS_ALLOW_MEMORY_FALLBACK_KEY,
    RUNTIME_KEY,
    SESSION_TTL_KEY,
    STARTED_AT_KEY,
    TOKEN_KEY,
    TRUST_PROXY_KEY,
    USERNAME_KEY,
)
from web.health import _healthz
from web.pages import _admin_index, _aggregate_page, _get_admin_static_dir, _login_page
from web.session_api import _auth_middleware, _login, _logout, _security_headers_middleware


def _configure_app_state(
    app: web.Application,
    *,
    runtime: Any,
    web_admin_token: str,
    web_admin_username: str,
    web_admin_session_ttl_seconds: int,
    web_admin_allow_header_token: bool,
    web_admin_cookie_secure: bool,
    web_admin_trust_proxy: bool,
    web_admin_login_window_seconds: int,
    web_admin_login_max_attempts: int,
    web_admin_redis_url: str,
    web_admin_redis_allow_memory_fallback: bool,
) -> None:
    app[RUNTIME_KEY] = runtime
    app[TOKEN_KEY] = web_admin_token
    app[USERNAME_KEY] = web_admin_username
    app[SESSION_TTL_KEY] = max(60, web_admin_session_ttl_seconds)
    app[ALLOW_HEADER_TOKEN_KEY] = web_admin_allow_header_token
    app[COOKIE_SECURE_KEY] = web_admin_cookie_secure
    app[TRUST_PROXY_KEY] = web_admin_trust_proxy
    app[LOGIN_WINDOW_KEY] = max(60, web_admin_login_window_seconds)
    app[LOGIN_MAX_ATTEMPTS_KEY] = max(1, web_admin_login_max_attempts)
    app[REDIS_ALLOW_MEMORY_FALLBACK_KEY] = web_admin_redis_allow_memory_fallback
    app[AUTH_BACKEND_KEY] = _build_auth_backend(
        web_admin_redis_url,
        allow_memory_fallback=web_admin_redis_allow_memory_fallback,
    )
    app[STARTED_AT_KEY] = time.time()


def _configure_aggregate_state(app: web.Application, *, web_admin_token: str) -> None:
    app[AGG_STATE_KEY] = OwnerAggregateState(_aggregate_state_file(), secret_key=web_admin_token)
    app[AGG_API_DEPS_KEY] = AggregateApiDeps(
        build_bundle=_build_owner_aggregate_bundle,
        build_pool_snapshot=_build_pool_snapshot,
        compute_fingerprint=_compute_owner_fingerprint,
        format_timing_ms=_format_timing_ms,
    )


def _register_lifecycle(app: web.Application) -> None:
    app.on_startup.append(_validate_auth_backend)
    app.on_startup.append(_start_background_tasks)
    app.on_cleanup.append(_close_auth_backend)


def _register_page_routes(app: web.Application) -> None:
    app.router.add_get("/healthz", _healthz)
    app.router.add_get("/admin/login", _login_page)
    app.router.add_post("/admin/login", _login)
    app.router.add_post("/admin/logout", _logout)
    app.router.add_get("/admin", _admin_index)
    app.router.add_get("/admin/", _admin_index)
    app.router.add_get("/admin/aggregate", _aggregate_page)
    app.router.add_get("/admin/aggregate/", _aggregate_page)


def _register_api_routes(app: web.Application) -> None:
    app.router.add_get(f"{API_PREFIX}/system/overview", _system_overview)
    app.router.add_get(f"{API_PREFIX}/users/recent", _recent_users)
    app.router.add_get(f"{API_PREFIX}/exports/recent", _recent_exports)
    app.router.add_get(f"{API_PREFIX}/audit/summary", _audit_summary)
    app.router.add_get(f"{API_PREFIX}/subscriptions/global", _subscriptions_global)
    app.router.add_get(f"{API_PREFIX}/subscriptions/available", _subscriptions_available)
    app.router.add_get(f"{API_PREFIX}/users/authorized", _authorized_users)
    app.router.add_get(f"{API_PREFIX}/audit/recent-checks", _recent_checks)
    app.router.add_get(f"{API_PREFIX}/system/runtime", _runtime_status)
    app.router.add_get(f"{API_PREFIX}/users/detail", _user_detail)
    app.router.add_post(f"{API_PREFIX}/users/access", _set_user_access)
    app.router.add_post(f"{API_PREFIX}/system/public-access", _set_public_access)
    app.router.add_post(f"{API_PREFIX}/system/sessions/revoke-all", _revoke_all_sessions)
    app.router.add_get(f"{API_PREFIX}/audit/alerts", _audit_alerts)
    app.router.add_get(f"{API_PREFIX}/audit/export", _audit_export)


def _register_owner_routes(app: web.Application) -> None:
    app.router.add_get(f"{API_PREFIX}/owner/export-json", _owner_export_json)
    app.router.add_post(f"{API_PREFIX}/owner/import-json", _owner_import_json)
    app.router.add_get(f"{API_PREFIX}/owner/backup", _owner_backup_download)
    app.router.add_post(f"{API_PREFIX}/owner/restore", _owner_restore_backup)
    app.router.add_post(f"{API_PREFIX}/owner/check-all", _owner_check_all)
    app.router.add_get(f"{API_PREFIX}/owner/aggregate-subscription", _owner_aggregate_info)
    app.router.add_post(
        f"{API_PREFIX}/owner/aggregate-subscription/rotate", _owner_aggregate_rotate
    )
    app.router.add_post(
        f"{API_PREFIX}/owner/aggregate-subscription/refresh", _owner_aggregate_refresh
    )
    app.router.add_get("/sub/{token}", _public_owner_subscription)
    app.router.add_get("/sub/{token}/{mode}", _public_owner_subscription)


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
    web_admin_redis_allow_memory_fallback: bool = False,
) -> web.Application:
    token = _require_secret(web_admin_token, name="WEB_ADMIN_TOKEN")
    app = web.Application(middlewares=[_auth_middleware, _security_headers_middleware])
    _configure_app_state(
        app,
        runtime=runtime,
        web_admin_token=token,
        web_admin_username=web_admin_username,
        web_admin_session_ttl_seconds=web_admin_session_ttl_seconds,
        web_admin_allow_header_token=web_admin_allow_header_token,
        web_admin_cookie_secure=web_admin_cookie_secure,
        web_admin_trust_proxy=web_admin_trust_proxy,
        web_admin_login_window_seconds=web_admin_login_window_seconds,
        web_admin_login_max_attempts=web_admin_login_max_attempts,
        web_admin_redis_url=web_admin_redis_url,
        web_admin_redis_allow_memory_fallback=web_admin_redis_allow_memory_fallback,
    )
    _configure_aggregate_state(app, web_admin_token=token)
    _register_lifecycle(app)
    _register_page_routes(app)
    _register_api_routes(app)
    _register_owner_routes(app)
    app.router.add_static("/admin/static/", path=_get_admin_static_dir(), show_index=False)
    return app
