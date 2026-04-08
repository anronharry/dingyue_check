"""Owner-facing usage audit logging."""
from __future__ import annotations

import json
import os
import threading
from collections import deque
from datetime import datetime


class UsageAuditService:
    def __init__(self, path: str, *, max_records: int = 5000, max_read_records: int = 10000):
        self.path = path
        self.max_records = max_records
        self.max_read_records = max_read_records
        self._lock = threading.Lock()
        self._record_count: int | None = None

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
        serialized = json.dumps(record, ensure_ascii=False) + "\n"
        with self._lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            count = self._get_record_count_locked()
            if count < self.max_records:
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(serialized)
                self._record_count = count + 1
                return

            retained = self._read_recent_lines_locked(limit=max(0, self.max_records - 1))
            retained.append(serialized)
            self._write_lines_locked(retained[-self.max_records :])
            self._record_count = min(self.max_records, len(retained))

    def _get_record_count_locked(self) -> int:
        if self._record_count is not None:
            return self._record_count
        if not os.path.exists(self.path):
            self._record_count = 0
            return 0
        with open(self.path, "r", encoding="utf-8") as handle:
            self._record_count = sum(1 for line in handle if line.strip())
        return self._record_count

    def _read_recent_lines_locked(self, *, limit: int) -> list[str]:
        if limit <= 0 or not os.path.exists(self.path):
            return []
        tail = deque(maxlen=limit)
        with open(self.path, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    tail.append(line if line.endswith("\n") else line + "\n")
        return list(tail)

    def _write_lines_locked(self, lines: list[str]) -> None:
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            handle.writelines(lines)
        os.replace(tmp_path, self.path)

    def get_recent_records(self, limit: int = 20) -> list[dict]:
        safe_limit = max(0, min(limit, self.max_read_records))
        if safe_limit == 0 or not os.path.exists(self.path):
            return []
        with self._lock:
            lines = self._read_recent_lines_locked(limit=safe_limit)
        records = []
        for line in lines:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records

    def query_records(
        self,
        *,
        owner_id: int,
        mode: str = "others",
        page: int = 1,
        page_size: int = 5,
        records: list[dict] | None = None,
    ) -> dict:
        source_records = list(records) if records is not None else list(reversed(self.get_recent_records(limit=self.max_read_records)))
        if mode == "owner":
            filtered = [row for row in source_records if row.get("user_id") == owner_id]
        elif mode == "all":
            filtered = source_records
        else:
            filtered = [row for row in source_records if row.get("user_id") != owner_id]
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

    def query_by_source_prefix(
        self,
        *,
        prefix: str,
        limit: int = 20,
        owner_id: int | None = None,
        include_owner: bool = True,
        records: list[dict] | None = None,
    ) -> list[dict]:
        source_records = list(records) if records is not None else list(reversed(self.get_recent_records(limit=self.max_read_records)))
        filtered = []
        for row in source_records:
            source = row.get("source", "")
            if not source.startswith(prefix):
                continue
            if owner_id is not None and not include_owner and row.get("user_id") == owner_id:
                continue
            filtered.append(row)
            if len(filtered) >= limit:
                break
        return filtered
