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
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._trim_if_needed()

    def _trim_if_needed(self) -> None:
        if not os.path.exists(self.path):
            return

        with open(self.path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if len(lines) <= self.max_records:
            return

        keep_lines = lines[-self.max_records :]
        temp_path = self.path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            f.writelines(keep_lines)
        os.replace(temp_path, self.path)

    def get_recent_records(self, limit: int = 20) -> list[dict]:
        if not os.path.exists(self.path):
            return []

        with self._lock:
            with open(self.path, "r", encoding="utf-8") as f:
                lines = f.readlines()

        records: list[dict] = []
        for line in lines[-self.max_read_records :]:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records[-limit:]
