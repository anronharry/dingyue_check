"""Application settings loader."""

from __future__ import annotations

from dataclasses import dataclass
import os

PORT_MIN = 1
PORT_MAX = 65535
BOOL_TRUE_VALUES = {"1", "true", "yes", "on"}
BOOL_FALSE_VALUES = {"0", "false", "no", "off"}


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in BOOL_TRUE_VALUES:
        return True
    if normalized in BOOL_FALSE_VALUES:
        return False
    raise RuntimeError(
        f"{name} must be a boolean: one of 1/0, true/false, yes/no, on/off. Got {value!r}"
    )


def _env_int(
    name: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        value = default
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise RuntimeError(f"{name} must be an integer, got {raw!r}") from exc
    if minimum is not None and value < minimum:
        raise RuntimeError(f"{name} must be >= {minimum}, got {value}")
    if maximum is not None and value > maximum:
        raise RuntimeError(f"{name} must be <= {maximum}, got {value}")
    return value


def _env_int_set(name: str) -> set[int]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return set()
    values: set[int] = set()
    for item in raw.split(","):
        token = item.strip()
        if not token:
            continue
        try:
            values.add(int(token))
        except ValueError as exc:
            raise RuntimeError(f"{name} must contain only integer IDs, got {token!r}") from exc
    return values


@dataclass(frozen=True)
class AppSettings:
    bot_token: str | None
    proxy_port: int
    url_cache_max_size: int
    url_cache_ttl_seconds: int
    allowed_user_ids: set[int]
    enable_web_admin: bool
    web_admin_host: str
    web_admin_port: int
    web_admin_token: str
    web_admin_username: str
    web_admin_session_ttl_seconds: int
    web_admin_allow_header_token: bool
    web_admin_cookie_secure: bool
    web_admin_trust_proxy: bool
    web_admin_login_window_seconds: int
    web_admin_login_max_attempts: int
    web_admin_redis_url: str
    web_admin_redis_allow_memory_fallback: bool

    @classmethod
    def from_env(cls) -> "AppSettings":
        return cls(
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            proxy_port=_env_int("PROXY_PORT", 7890, minimum=PORT_MIN, maximum=PORT_MAX),
            url_cache_max_size=_env_int("URL_CACHE_MAX_SIZE", 5000, minimum=1),
            url_cache_ttl_seconds=_env_int("URL_CACHE_TTL_SECONDS", 86400, minimum=1),
            allowed_user_ids=_env_int_set("ALLOWED_USER_IDS"),
            enable_web_admin=_env_bool("ENABLE_WEB_ADMIN", False),
            web_admin_host=os.getenv("WEB_ADMIN_HOST", "127.0.0.1").strip() or "127.0.0.1",
            web_admin_port=_env_int("WEB_ADMIN_PORT", 8080, minimum=PORT_MIN, maximum=PORT_MAX),
            web_admin_token=os.getenv("WEB_ADMIN_TOKEN", "").strip(),
            web_admin_username=os.getenv("WEB_ADMIN_USERNAME", "admin").strip() or "admin",
            web_admin_session_ttl_seconds=_env_int(
                "WEB_ADMIN_SESSION_TTL_SECONDS",
                28800,
                minimum=1,
            ),
            web_admin_allow_header_token=_env_bool("WEB_ADMIN_ALLOW_HEADER_TOKEN", False),
            web_admin_cookie_secure=_env_bool("WEB_ADMIN_COOKIE_SECURE", True),
            web_admin_trust_proxy=_env_bool("WEB_ADMIN_TRUST_PROXY", False),
            web_admin_login_window_seconds=_env_int(
                "WEB_ADMIN_LOGIN_WINDOW_SECONDS",
                600,
                minimum=1,
            ),
            web_admin_login_max_attempts=_env_int(
                "WEB_ADMIN_LOGIN_MAX_ATTEMPTS",
                10,
                minimum=1,
            ),
            web_admin_redis_url=os.getenv("WEB_ADMIN_REDIS_URL", "").strip(),
            web_admin_redis_allow_memory_fallback=_env_bool(
                "WEB_ADMIN_REDIS_ALLOW_MEMORY_FALLBACK",
                False,
            ),
        )
