"""Owner-facing usage audit logging."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime


class UsageAuditService:
    def __init__(self, path: str, *, max_records: int = 5000, max_read_records: int = 10000):
        self.path = path
        self.max_records = max_records
        self.max_read_records = max_read_records
        self._lock = threading.Lock()

    def log_check(self, *, user, urls: list[str], source: str) -> None:
        if not user or not urls:
            return
        record = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user_id": user.id,
            "username": getattr(user, "username", None),
            "full_name": getattr(user, "full_name", None),
            "source": source,
            "urls": urls,
        }
        self._append_record(record)

    def _append_record(self, record: dict) -> None:
        with self._lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._trim_if_needed()

    def _trim_if_needed(self) -> None:
        if not os.path.exists(self.path):
            return
        with open(self.path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
        if len(lines) <= self.max_records:
            return
        temp_path = self.path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            handle.writelines(lines[-self.max_records :])
        os.replace(temp_path, self.path)

    def get_recent_records(self, limit: int = 20) -> list[dict]:
        if not os.path.exists(self.path):
            return []
        with self._lock:
            with open(self.path, "r", encoding="utf-8") as handle:
                lines = handle.readlines()
        records = []
        for line in lines[-self.max_read_records :]:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records[-limit:]

    def query_records(self, *, owner_id: int, mode: str = "others", page: int = 1, page_size: int = 5) -> dict:
        records = list(reversed(self.get_recent_records(limit=self.max_read_records)))
        if mode == "owner":
            filtered = [row for row in records if row.get("user_id") == owner_id]
        elif mode == "all":
            filtered = records
        else:
            filtered = [row for row in records if row.get("user_id") != owner_id]
        total = len(filtered)
        total_pages = max(1, (total + page_size - 1) // page_size)
        safe_page = max(1, min(page, total_pages))
        start = (safe_page - 1) * page_size
        return {
            "mode": mode,
            "page": safe_page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "records": filtered[start : start + page_size],
        }

    def query_by_source_prefix(self, *, prefix: str, limit: int = 20, owner_id: int | None = None, include_owner: bool = True) -> list[dict]:
        records = list(reversed(self.get_recent_records(limit=self.max_read_records)))
        filtered = []
        for row in records:
            source = row.get("source", "")
            if not source.startswith(prefix):
                continue
            if owner_id is not None and not include_owner and row.get("user_id") == owner_id:
                continue
            filtered.append(row)
            if len(filtered) >= limit:
                break
        return filtered
