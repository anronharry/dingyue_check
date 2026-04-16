"""User-level preference persistence for monitor alert delivery."""
from __future__ import annotations

import time

from core.json_store import JsonStore


class AlertPreferenceService:
    def __init__(self, path: str, *, auto_flush_interval_seconds: float = 30.0):
        self.path = path
        self.store = JsonStore(path, default_factory=dict)
        self._preferences = self.store.get_data()
        self.auto_flush_interval_seconds = max(0.0, float(auto_flush_interval_seconds))
        self._last_flush_monotonic = time.monotonic()

    def is_muted(self, user_id: int | None) -> bool:
        if not user_id:
            return False
        row = self._preferences.get(str(user_id), {})
        return bool(row.get("monitor_alerts_muted", False))

    def mute_user(self, user_id: int | None) -> None:
        if not user_id:
            return
        key = str(user_id)
        existing = self._preferences.get(key, {})
        self._preferences[key] = {
            **existing,
            "monitor_alerts_muted": True,
        }
        self.store.mark_dirty()
        if self._should_auto_flush():
            self.flush()

    def unmute_user(self, user_id: int | None) -> None:
        if not user_id:
            return
        key = str(user_id)
        existing = self._preferences.get(key, {})
        self._preferences[key] = {
            **existing,
            "monitor_alerts_muted": False,
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
