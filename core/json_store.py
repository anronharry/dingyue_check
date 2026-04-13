"""Shared JSON file persistence helpers."""
from __future__ import annotations

import asyncio
import json
import os
import threading
from copy import deepcopy

import aiofiles


class JsonStore:
    def __init__(self, path: str, *, default_factory):
        self.path = path
        self.default_factory = default_factory
        self._lock = threading.Lock()
        self._async_lock = asyncio.Lock()
        self._data = self._load()
        self._dirty = False

    def _load(self):
        if not os.path.exists(self.path):
            return self.default_factory()
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if data is not None else self.default_factory()
        except Exception:
            return self.default_factory()

    def mark_dirty(self) -> None:
        with self._lock:
            self._dirty = True

    def save(self) -> None:
        with self._lock:
            self._write_unlocked()

    async def asave(self) -> None:
        async with self._async_lock:
            with self._lock:
                snapshot = deepcopy(self._data)
            await self._write_snapshot_async(snapshot)
            with self._lock:
                self._dirty = False

    def flush(self) -> bool:
        with self._lock:
            if not self._dirty:
                return False
            self._write_unlocked()
            return True

    async def aflush(self) -> bool:
        async with self._async_lock:
            with self._lock:
                if not self._dirty:
                    return False
                snapshot = deepcopy(self._data)
            await self._write_snapshot_async(snapshot)
            with self._lock:
                self._dirty = False
            return True

    def _write_unlocked(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(self._data, handle, indent=2, ensure_ascii=False)
        os.replace(tmp_path, self.path)
        self._dirty = False

    async def _write_snapshot_async(self, snapshot) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp_path = self.path + ".tmp"
        payload = json.dumps(snapshot, indent=2, ensure_ascii=False)
        async with aiofiles.open(tmp_path, "w", encoding="utf-8") as handle:
            await handle.write(payload)
        await asyncio.to_thread(os.replace, tmp_path, self.path)

    def get_data(self):
        return self._data

    def snapshot(self):
        with self._lock:
            return deepcopy(self._data)
