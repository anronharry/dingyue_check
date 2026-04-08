"""Enhanced subscription storage with owner/tag/import-export support."""
from __future__ import annotations

import json
import logging
import os
import threading
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List

from core.workspace_manager import WorkspaceManager

logger = logging.getLogger(__name__)

ws_manager = WorkspaceManager("data")
DATA_DIR = ws_manager.db_dir
DATA_FILE = ws_manager.get_subscription_db_path()


class SubscriptionStorage:
    """Persistent storage for subscriptions."""

    def __init__(self, data_file: str = DATA_FILE):
        self.data_file = data_file
        self._lock = threading.RLock()
        self._batch_depth = 0
        self._dirty = False
        self._ensure_data_dir()
        self.subscriptions: Dict[str, Dict[str, Any]] = self._load_data()

    def _ensure_data_dir(self) -> None:
        data_dir = os.path.dirname(self.data_file)
        os.makedirs(data_dir, exist_ok=True)

    def _load_data(self) -> Dict[str, Dict[str, Any]]:
        if not os.path.exists(self.data_file):
            return {}
        try:
            with open(self.data_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
            logger.warning("Invalid subscriptions data type: %s", type(data).__name__)
            return {}
        except Exception as exc:
            logger.error("Failed to load subscriptions data: %s", exc)
            return {}

    def _save_data_blocking(self) -> bool:
        """Durable synchronous save with atomic replace."""
        try:
            with self._lock:
                snapshot = deepcopy(self.subscriptions)
            temp_file = self.data_file + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2, ensure_ascii=False)
            os.replace(temp_file, self.data_file)
            logger.debug("Saved %s subscriptions", len(snapshot))
            return True
        except Exception as exc:
            logger.error("Failed to save subscriptions data: %s", exc)
            return False

    def _save_data(self) -> bool:
        saved = self._save_data_blocking()
        if saved:
            with self._lock:
                self._dirty = False
        return saved

    def _mark_dirty(self) -> None:
        with self._lock:
            self._dirty = True
            should_save_now = self._batch_depth == 0
        if should_save_now:
            self._save_data()

    def begin_batch(self) -> None:
        with self._lock:
            self._batch_depth += 1

    def end_batch(self, save: bool = True) -> None:
        with self._lock:
            if self._batch_depth > 0:
                self._batch_depth -= 1
            should_save = save and self._batch_depth == 0 and self._dirty
        if should_save:
            self._save_data()

    def flush(self) -> bool:
        """Force-persist pending data, returns True if flushed."""
        with self._lock:
            if not self._dirty:
                return False
        return self._save_data()

    def add_or_update(self, url: str, info: Dict[str, Any], user_id: int = 0) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            existing = self.subscriptions.get(url, {})
            existing_owner = existing.get("owner_uid", 0)
            owner_uid = existing_owner if existing_owner else user_id

            data = {
                "name": info.get("name", "Unknown Subscription"),
                "url": url,
                "updated_at": now,
                "expire_time": info.get("expire_time"),
                "node_count": info.get("node_count", 0),
                "total": info.get("total", 0),
                "used": info.get("used", 0),
                "remaining": info.get("remaining", 0),
                "last_check_status": "success",
                "owner_uid": owner_uid,
                "tags": [],
            }
            if url not in self.subscriptions:
                data["added_at"] = now
                data["tags"] = []
            else:
                data["added_at"] = existing.get("added_at", now)
                data["tags"] = existing.get("tags", [])
                data["last_check_error"] = None

            self.subscriptions[url] = data

        self._mark_dirty()
        logger.info("Saved subscription: %s", data["name"])

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return deepcopy(self.subscriptions)

    def get_by_user(self, user_id: int) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {url: data for url, data in self.subscriptions.items() if data.get("owner_uid", 0) == user_id}

    def get_grouped_by_user(self) -> Dict[int, Dict[str, Dict[str, Any]]]:
        grouped: Dict[int, Dict[str, Dict[str, Any]]] = {}
        with self._lock:
            for url, data in self.subscriptions.items():
                uid = data.get("owner_uid", 0)
                grouped.setdefault(uid, {})[url] = data
        return grouped

    def migrate_subscriptions(self, default_owner_id: int) -> int:
        count = 0
        with self._lock:
            for data in self.subscriptions.values():
                if not data.get("owner_uid"):
                    data["owner_uid"] = default_owner_id
                    count += 1
        if count:
            self._mark_dirty()
            logger.info("Migrated %s subscriptions to owner UID %s", count, default_owner_id)
        return count

    def get_by_tag(self, tag: str) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {url: data for url, data in self.subscriptions.items() if tag in data.get("tags", [])}

    def get_user_statistics(self, user_id: int) -> Dict[str, Any]:
        user_subs = self.get_by_user(user_id)
        return self._calc_statistics(user_subs)

    def remove(self, url: str, operator_uid: int = 0, require_owner: bool = False) -> bool:
        with self._lock:
            if url not in self.subscriptions:
                return False
            if require_owner and operator_uid:
                sub_owner = self.subscriptions[url].get("owner_uid", 0)
                if sub_owner and sub_owner != operator_uid:
                    logger.warning("UID %s attempted to delete UID %s subscription", operator_uid, sub_owner)
                    return False
            name = self.subscriptions[url].get("name", "Unknown")
            del self.subscriptions[url]
        self._mark_dirty()
        logger.info("Deleted subscription: %s", name)
        return True

    def mark_check_failed(self, url: str, error: str, operator_uid: int = 0, require_owner: bool = False) -> bool:
        if not self._can_modify_subscription(url, operator_uid, require_owner):
            return False
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            data = self.subscriptions[url]
            data["last_check_status"] = "failed"
            data["last_check_error"] = str(error)[:500]
            data["updated_at"] = now
        self._mark_dirty()
        return True

    def _can_modify_subscription(self, url: str, operator_uid: int = 0, require_owner: bool = False) -> bool:
        with self._lock:
            if url not in self.subscriptions:
                logger.warning("Subscription not found: %s", url)
                return False
            if require_owner and operator_uid:
                sub_owner = self.subscriptions[url].get("owner_uid", 0)
                if sub_owner and sub_owner != operator_uid:
                    logger.warning("UID %s attempted to modify UID %s subscription", operator_uid, sub_owner)
                    return False
        return True

    def add_tag(self, url: str, tag: str, operator_uid: int = 0, require_owner: bool = False) -> bool:
        if not self._can_modify_subscription(url, operator_uid, require_owner):
            return False
        with self._lock:
            tags = self.subscriptions[url].get("tags", [])
            if tag in tags:
                logger.info("Tag already exists: %s", tag)
                return False
            tags.append(tag)
            self.subscriptions[url]["tags"] = tags
            name = self.subscriptions[url].get("name", "Unknown")
        self._mark_dirty()
        logger.info("Added tag %s to %s", tag, name)
        return True

    def remove_tag(self, url: str, tag: str, operator_uid: int = 0, require_owner: bool = False) -> bool:
        if not self._can_modify_subscription(url, operator_uid, require_owner):
            return False
        with self._lock:
            tags = self.subscriptions[url].get("tags", [])
            if tag not in tags:
                return False
            tags.remove(tag)
            self.subscriptions[url]["tags"] = tags
        self._mark_dirty()
        logger.info("Removed tag: %s", tag)
        return True

    def get_all_tags(self) -> List[str]:
        all_tags = set()
        with self._lock:
            for data in self.subscriptions.values():
                all_tags.update(data.get("tags", []))
        return sorted(all_tags)

    def export_to_file(self, filepath: str) -> bool:
        try:
            with self._lock:
                snapshot = deepcopy(self.subscriptions)
            export_data = {
                "version": "1.0",
                "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "count": len(snapshot),
                "subscriptions": snapshot,
            }
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            logger.info("Exported %s subscriptions to %s", len(snapshot), filepath)
            return True
        except Exception as exc:
            logger.error("Export failed: %s", exc)
            return False

    def import_from_file(self, filepath: str, merge: bool = True) -> int:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                import_data = json.load(f)
            if "subscriptions" not in import_data:
                logger.error("Invalid import file: missing 'subscriptions'")
                return 0

            imported_subs = import_data["subscriptions"]
            if not isinstance(imported_subs, dict):
                logger.error("Invalid subscriptions payload in import file")
                return 0

            count = 0
            with self._lock:
                if not merge:
                    self.subscriptions = {}
                for url, data in imported_subs.items():
                    self.subscriptions[url] = data
                    count += 1
            self._mark_dirty()
            logger.info("Imported %s subscriptions", count)
            return count
        except Exception as exc:
            logger.error("Import failed: %s", exc)
            return 0

    def get_statistics(self) -> Dict[str, Any]:
        with self._lock:
            snapshot = deepcopy(self.subscriptions)
        return self._calc_statistics(snapshot)

    def _calc_statistics(self, subs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        total = len(subs)
        expired = 0
        total_traffic = 0
        total_remaining = 0
        now = datetime.now()

        for data in subs.values():
            expire_time_str = data.get("expire_time")
            if expire_time_str:
                try:
                    expire_date = datetime.strptime(expire_time_str, "%Y-%m-%d %H:%M:%S")
                    if expire_date < now:
                        expired += 1
                except Exception:
                    pass
            total_traffic += data.get("total", 0)
            total_remaining += data.get("remaining", 0)

        return {
            "total": total,
            "expired": expired,
            "active": total - expired,
            "total_traffic": total_traffic,
            "total_remaining": total_remaining,
            "tags": self.get_all_tags(),
        }
