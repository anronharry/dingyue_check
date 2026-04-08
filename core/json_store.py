"""Shared JSON file persistence helpers."""
from __future__ import annotations

import json
import os
import threading
from copy import deepcopy


class JsonStore:
    def __init__(self, path: str, *, default_factory):
        self.path = path
        self.default_factory = default_factory
        self._lock = threading.RLock()
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

    def flush(self) -> bool:
        with self._lock:
            if not self._dirty:
                return False
            self._write_unlocked()
            return True

    def _write_unlocked(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(self._data, handle, indent=2, ensure_ascii=False)
        os.replace(tmp_path, self.path)
        self._dirty = False

    def get_data(self):
        return self._data

    def snapshot(self):
        with self._lock:
            return deepcopy(self._data)
