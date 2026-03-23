"""Application settings loader."""
from __future__ import annotations


from dataclasses import dataclass
import os


@dataclass(frozen=True)
class AppSettings:
    bot_token: str | None
    proxy_port: int
    url_cache_max_size: int
    url_cache_ttl_seconds: int
    allowed_user_ids: set[int]

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
        )
