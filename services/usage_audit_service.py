"""Owner-facing usage audit logging."""
from __future__ import annotations

import asyncio
import json
import os
import threading
from collections import deque
from datetime import datetime

import aiofiles


class UsageAuditService:
    def __init__(self, path: str, *, max_records: int = 5000, max_read_records: int = 10000):
        self.path = path
        self.max_records = max_records
        self.max_read_records = max_read_records
        self._lock = threading.Lock()
        self._async_lock = asyncio.Lock()
        self._record_count: int | None = None
        self._records_cache: deque[dict] | None = None

    @staticmethod
    def _safe_parse_line(line: str) -> dict | None:
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None

    def _ensure_records_cache_locked(self) -> None:
        if self._records_cache is not None:
            return
        cache = deque(maxlen=max(1, self.max_records))
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as handle:
                for line in handle:
                    text = line.strip()
                    if not text:
                        continue
                    parsed = self._safe_parse_line(text)
                    if parsed is not None:
                        cache.append(parsed)
        self._records_cache = cache
        self._record_count = len(cache)

    def _set_records_cache_from_lines_locked(self, lines: list[str]) -> None:
        cache = deque(maxlen=max(1, self.max_records))
        for line in lines:
            parsed = self._safe_parse_line(line.strip())
            if parsed is not None:
                cache.append(parsed)
        self._records_cache = cache
        self._record_count = len(cache)

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

    async def alog_check(self, *, user, urls: list[str], source: str) -> None:
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
        await self._append_record_async(record)

    def _append_record(self, record: dict) -> None:
        serialized = json.dumps(record, ensure_ascii=False) + "\n"
        with self._lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            count = self._get_record_count_locked()
            self._ensure_records_cache_locked()
            if count < self.max_records:
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(serialized)
                self._record_count = count + 1
                self._records_cache.append(dict(record))
                return

            retained = self._read_recent_lines_locked(limit=max(0, self.max_records - 1))
            retained.append(serialized)
            self._write_lines_locked(retained[-self.max_records :])
            self._set_records_cache_from_lines_locked(retained[-self.max_records :])

    async def _append_record_async(self, record: dict) -> None:
        serialized = json.dumps(record, ensure_ascii=False) + "\n"
        async with self._async_lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            count = await self._aget_record_count_locked()
            with self._lock:
                self._ensure_records_cache_locked()
            if count < self.max_records:
                async with aiofiles.open(self.path, "a", encoding="utf-8") as handle:
                    await handle.write(serialized)
                self._record_count = count + 1
                with self._lock:
                    self._records_cache.append(dict(record))
                return

            retained = await self._aread_recent_lines_locked(limit=max(0, self.max_records - 1))
            retained.append(serialized)
            await self._awrite_lines_locked(retained[-self.max_records :])
            with self._lock:
                self._set_records_cache_from_lines_locked(retained[-self.max_records :])

    def _get_record_count_locked(self) -> int:
        if self._records_cache is not None:
            self._record_count = len(self._records_cache)
            return self._record_count
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

    async def _aget_record_count_locked(self) -> int:
        if self._record_count is not None:
            return self._record_count
        if not os.path.exists(self.path):
            self._record_count = 0
            return 0
        count = 0
        async with aiofiles.open(self.path, "r", encoding="utf-8") as handle:
            async for line in handle:
                if line.strip():
                    count += 1
        self._record_count = count
        return count

    async def _aread_recent_lines_locked(self, *, limit: int) -> list[str]:
        if limit <= 0 or not os.path.exists(self.path):
            return []
        tail = deque(maxlen=limit)
        async with aiofiles.open(self.path, "r", encoding="utf-8") as handle:
            async for line in handle:
                if line.strip():
                    tail.append(line if line.endswith("\n") else line + "\n")
        return list(tail)

    async def _awrite_lines_locked(self, lines: list[str]) -> None:
        tmp_path = self.path + ".tmp"
        async with aiofiles.open(tmp_path, "w", encoding="utf-8") as handle:
            await handle.writelines(lines)
        await asyncio.to_thread(os.replace, tmp_path, self.path)

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
            self._ensure_records_cache_locked()
            rows = list(self._records_cache)[-safe_limit:]
        return [dict(row) for row in rows]

    async def aget_recent_records(self, limit: int = 20) -> list[dict]:
        safe_limit = max(0, min(limit, self.max_read_records))
        if safe_limit == 0 or not os.path.exists(self.path):
            return []
        async with self._async_lock:
            with self._lock:
                self._ensure_records_cache_locked()
                rows = list(self._records_cache)[-safe_limit:]
        return [dict(row) for row in rows]

    async def _yield_records_reverse(self):
        """Yields records from the file in reverse order (newest first)."""
        with self._lock:
            if self._records_cache is not None:
                snapshot = list(self._records_cache)
            else:
                snapshot = None
        if snapshot is not None:
            for row in reversed(snapshot):
                yield dict(row)
            return

        if not os.path.exists(self.path):
            return
        
        chunk_size = 64 * 1024
        async with aiofiles.open(self.path, 'rb') as f:
            await f.seek(0, os.SEEK_END)
            filesize = await f.tell()
            pointer = filesize
            buffer = b""
            
            while pointer > 0:
                step = min(pointer, chunk_size)
                pointer -= step
                await f.seek(pointer)
                chunk = await f.read(step)
                buffer = chunk + buffer
                lines = buffer.split(b"\n")
                
                # The first element might be incomplete if it's not the start of the file
                # Save it for the next iteration
                if pointer > 0:
                    buffer = lines[0]
                    lines = lines[1:]
                else:
                    buffer = b""
                
                for line in reversed(lines):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line.decode('utf-8'))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue

    def query_records(
        self,
        *,
        owner_id: int,
        mode: str = "others",
        page: int = 1,
        page_size: int = 5,
        records: list[dict] | None = None,
        predicate=None,
    ) -> dict:
        source_records = list(records) if records is not None else list(reversed(self.get_recent_records(limit=self.max_read_records)))
        if mode == "owner":
            filtered = [row for row in source_records if row.get("user_id") == owner_id]
        elif mode == "all":
            filtered = source_records
        else:
            filtered = [row for row in source_records if row.get("user_id") != owner_id]
        if predicate is not None:
            filtered = [row for row in filtered if predicate(row)]
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

    async def aquery_records(
        self,
        *,
        owner_id: int,
        mode: str = "others",
        page: int = 1,
        page_size: int = 5,
        predicate=None
    ) -> dict:
        """
        Efficiently query records with filtering and pagination without loading everything.
        'predicate' is an optional sync function(row) -> bool.
        """
        safe_page = max(1, page)
        safe_size = max(1, page_size)
        start_idx = (safe_page - 1) * safe_size
        end_idx = start_idx + safe_size
        
        scanned_count = 0
        filtered_count = 0
        page_records = []
        
        async for row in self._yield_records_reverse():
            scanned_count += 1
            if scanned_count > self.max_read_records:
                break

            uid = row.get("user_id")
            # Apply mode filter first
            if mode == "owner":
                if uid != owner_id: continue
            elif mode == "others":
                if uid == owner_id: continue
            # Else 'all', no filter
            
            if predicate and not predicate(row):
                continue
            
            if filtered_count >= start_idx and filtered_count < end_idx:
                page_records.append(row)
            
            filtered_count += 1

        total_pages = max(1, (filtered_count + safe_size - 1) // safe_size)
        
        return {
            "mode": mode,
            "page": safe_page,
            "page_size": safe_size,
            "total": filtered_count,
            "total_pages": total_pages,
            "records": page_records,
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

    async def aquery_by_source_prefix(
        self,
        *,
        prefix: str,
        limit: int = 20,
        owner_id: int | None = None,
        include_owner: bool = True,
    ) -> list[dict]:
        """Async version of source prefix query."""
        results = []
        async for row in self._yield_records_reverse():
            source = row.get("source", "")
            if not source.startswith(prefix):
                continue
            if owner_id is not None and not include_owner and row.get("user_id") == owner_id:
                continue
            results.append(row)
            if len(results) >= limit:
                break
        return results
