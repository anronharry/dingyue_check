"""Persistent runtime access mode flags."""
from __future__ import annotations


import json
import logging
import os

logger = logging.getLogger(__name__)


class AccessStateStore:
    """Stores owner-controlled access mode flags."""

    def __init__(self, path: str):
        self.path = path
        self.allow_all_users = False
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.allow_all_users = bool(data.get("allow_all_users", False))
        except Exception as exc:
            logger.error("加载访问控制状态失败: %s", exc)
            self.allow_all_users = False

    def _save(self) -> bool:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"allow_all_users": self.allow_all_users}, f, ensure_ascii=False, indent=2)
            return True
        except Exception as exc:
            logger.error("保存访问控制状态失败: %s", exc)
            return False

    def set_allow_all_users(self, enabled: bool) -> tuple[bool, bool]:
        enabled = bool(enabled)
        changed = self.allow_all_users != enabled
        previous = self.allow_all_users
        self.allow_all_users = enabled
        saved = self._save()
        if not saved:
            self.allow_all_users = previous
        return changed, saved

    def is_allow_all_users_enabled(self) -> bool:
        return self.allow_all_users
