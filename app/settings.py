"""Application settings loader."""
from __future__ import annotations


from dataclasses import dataclass
import os


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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

    @classmethod
    def from_env(cls) -> "AppSettings":
        raw_ids = os.getenv("ALLOWED_USER_IDS", "").strip()
        allowed_user_ids = {int(uid) for uid in raw_ids.split(",") if uid.strip().isdigit()}
        return cls(
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            proxy_port=int(os.getenv("PROXY_PORT", 7890)),
            url_cache_max_size=int(os.getenv("URL_CACHE_MAX_SIZE", 5000)),
            url_cache_ttl_seconds=int(os.getenv("URL_CACHE_TTL_SECONDS", 86400)),
            allowed_user_ids=allowed_user_ids,
            enable_web_admin=_env_bool("ENABLE_WEB_ADMIN", False),
            web_admin_host=os.getenv("WEB_ADMIN_HOST", "127.0.0.1").strip() or "127.0.0.1",
            web_admin_port=int(os.getenv("WEB_ADMIN_PORT", 8080)),
            web_admin_token=os.getenv("WEB_ADMIN_TOKEN", "").strip(),
            web_admin_username=os.getenv("WEB_ADMIN_USERNAME", "admin").strip() or "admin",
            web_admin_session_ttl_seconds=int(os.getenv("WEB_ADMIN_SESSION_TTL_SECONDS", 28800)),
            web_admin_allow_header_token=_env_bool("WEB_ADMIN_ALLOW_HEADER_TOKEN", False),
            web_admin_cookie_secure=_env_bool("WEB_ADMIN_COOKIE_SECURE", True),
            web_admin_trust_proxy=_env_bool("WEB_ADMIN_TRUST_PROXY", False),
            web_admin_login_window_seconds=int(os.getenv("WEB_ADMIN_LOGIN_WINDOW_SECONDS", 600)),
            web_admin_login_max_attempts=int(os.getenv("WEB_ADMIN_LOGIN_MAX_ATTEMPTS", 10)),
            web_admin_redis_url=os.getenv("WEB_ADMIN_REDIS_URL", "").strip(),
        )
