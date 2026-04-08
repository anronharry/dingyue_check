"""Persistence-backed user profile tracking for owner views."""
from __future__ import annotations

import html
import time
from datetime import datetime

from core.json_store import JsonStore


class UserProfileService:
    def __init__(self, path: str, *, auto_flush_interval_seconds: float = 30.0):
        self.path = path
        self.store = JsonStore(path, default_factory=dict)
        self._profiles = self.store.get_data()
        self.auto_flush_interval_seconds = max(0.0, float(auto_flush_interval_seconds))
        self._last_flush_monotonic = time.monotonic()

    def touch_user(self, *, user, source: str, is_owner: bool, is_authorized: bool) -> None:
        if not user:
            return
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        key = str(user.id)
        existing = self._profiles.get(key, {})
        self._profiles[key] = {
            "user_id": user.id,
            "username": getattr(user, "username", None),
            "full_name": getattr(user, "full_name", None),
            "first_seen_at": existing.get("first_seen_at", now),
            "last_seen_at": now,
            "last_source": source,
            "is_owner": bool(is_owner),
            "is_authorized": bool(is_authorized),
        }
        self.store.mark_dirty()
        if self._should_auto_flush():
            self.flush()

    def flush(self) -> bool:
        flushed = self.store.flush()
        if flushed:
            self._last_flush_monotonic = time.monotonic()
        return flushed

    def _should_auto_flush(self) -> bool:
        if self.auto_flush_interval_seconds == 0:
            return True
        return (time.monotonic() - self._last_flush_monotonic) >= self.auto_flush_interval_seconds

    def get_profile(self, user_id: int | None) -> dict | None:
        if not user_id:
            return None
        return self._profiles.get(str(user_id))

    def format_user_identity(self, user_id: int | None) -> str:
        if not user_id:
            return "<code>0</code>"
        profile = self.get_profile(user_id) or {}
        username = profile.get("username")
        full_name = profile.get("full_name")
        if username:
            return f'<a href="tg://user?id={user_id}">@{html.escape(username)}</a> (<code>{user_id}</code>)'
        if full_name:
            return f'<a href="tg://user?id={user_id}">{html.escape(full_name)}</a> (<code>{user_id}</code>)'
        return f"<code>{user_id}</code>"

    def get_recent_profiles(self, *, limit: int = 10, include_owner: bool = True) -> list[dict]:
        profiles = list(self._profiles.values())
        if not include_owner:
            profiles = [row for row in profiles if not row.get("is_owner")]
        profiles.sort(key=lambda row: row.get("last_seen_at", ""), reverse=True)
        return profiles[:limit]
