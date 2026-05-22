"""Owner aggregate subscription state storage."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

from web.auth import require_secret


DEFAULT_ROTATE_COOLDOWN_SECONDS = 30


class OwnerAggregateState:
    def __init__(
        self,
        path: Path,
        *,
        secret_key: str,
        rotate_cooldown_seconds: int = DEFAULT_ROTATE_COOLDOWN_SECONDS,
    ) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state_dir = path.with_suffix("")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.meta_path = self.state_dir / "meta.json"
        self.cache_path = self.state_dir / "cache.json"
        self.node_health_path = self.state_dir / "node_health.json"
        self._lock = asyncio.Lock()
        self._secret = require_secret(secret_key, name="WEB_ADMIN_TOKEN").encode("utf-8")
        self._rotate_cooldown_seconds = max(0, int(rotate_cooldown_seconds))
        self._meta, self._cache, self._node_health = self._load_split_state()

    def _encode_token(self, token: str) -> str:
        payload = token.encode("utf-8")
        key = self._secret
        mixed = bytes([b ^ key[i % len(key)] for i, b in enumerate(payload)])
        return base64.urlsafe_b64encode(mixed).decode("ascii")

    def _decode_token(self, token_enc: str) -> str:
        raw = base64.urlsafe_b64decode(token_enc.encode("ascii"))
        key = self._secret
        plain = bytes([b ^ key[i % len(key)] for i, b in enumerate(raw)])
        return plain.decode("utf-8")

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"State file is corrupted: {path}") from exc
        if not isinstance(loaded, dict):
            raise RuntimeError(f"State file must contain a JSON object: {path}")
        return loaded

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _load_split_state(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        legacy = self._load_json(self.path)
        meta = self._load_json(self.meta_path)
        cache = self._load_json(self.cache_path)
        node_health = self._load_json(self.node_health_path)
        if meta or cache or node_health:
            return meta, cache, node_health
        if not legacy:
            return {}, {}, {}
        migrated_meta = {
            key: value for key, value in legacy.items() if key not in {"cache", "node_health"}
        }
        migrated_cache = dict(legacy.get("cache", {}) or {})
        migrated_node_health = dict(legacy.get("node_health", {}) or {})
        self._write_json(self.meta_path, migrated_meta)
        self._write_json(self.cache_path, migrated_cache)
        self._write_json(self.node_health_path, migrated_node_health)
        return migrated_meta, migrated_cache, migrated_node_health

    def _save_if_changed(self, kind: str, next_state: dict[str, Any]) -> None:
        current = {"meta": self._meta, "cache": self._cache, "node_health": self._node_health}[kind]
        if next_state == current:
            return
        if kind == "meta":
            self._meta = next_state
            self._write_json(self.meta_path, self._meta)
        elif kind == "cache":
            self._cache = next_state
            self._write_json(self.cache_path, self._cache)
        else:
            self._node_health = next_state
            self._write_json(self.node_health_path, self._node_health)

    async def get_token(self) -> str:
        async with self._lock:
            token = ""
            token_enc = str(self._meta.get("token_enc", "") or "").strip()
            if token_enc:
                try:
                    token = self._decode_token(token_enc).strip()
                except Exception:
                    token = ""
            if not token:
                token = str(self._meta.get("token", "") or "").strip()
                if token:
                    next_meta = dict(self._meta)
                    next_meta["token_enc"] = self._encode_token(token)
                    next_meta.pop("token", None)
                    self._save_if_changed("meta", next_meta)
            if token:
                return token
            token = secrets.token_urlsafe(24)
            next_meta = dict(self._meta)
            next_meta["token_enc"] = self._encode_token(token)
            next_meta["created_at"] = int(time.time())
            self._save_if_changed("meta", next_meta)
            return token

    async def rotate_token(self) -> str:
        async with self._lock:
            now_ts = int(time.time())
            last_rotated = int(self._meta.get("rotated_at", self._meta.get("created_at", 0)) or 0)
            if last_rotated and now_ts - last_rotated < self._rotate_cooldown_seconds:
                raise ValueError("rotate_cooldown")
            token = secrets.token_urlsafe(24)
            next_meta = dict(self._meta)
            next_meta["token_enc"] = self._encode_token(token)
            next_meta.pop("token", None)
            next_meta["rotated_at"] = now_ts
            self._save_if_changed("meta", next_meta)
            self._save_if_changed("cache", {})
            return token

    async def read_cache(self) -> dict[str, Any] | None:
        async with self._lock:
            cache = self._cache
            if not isinstance(cache, dict):
                return None
            return dict(cache)

    async def read_meta(self) -> dict[str, Any]:
        async with self._lock:
            return {
                "last_error": str(self._meta.get("last_error", "") or ""),
                "last_error_at": int(self._meta.get("last_error_at", 0) or 0),
                "rotated_at": int(self._meta.get("rotated_at", 0) or 0),
                "build_stats": dict(self._meta.get("build_stats", {}) or {}),
                "pool_snapshot": dict(self._meta.get("pool_snapshot", {}) or {}),
            }

    async def write_cache(
        self,
        *,
        content: str,
        node_count: int,
        fingerprint: str = "",
        raw_content: str = "",
        base64_content: str = "",
    ) -> None:
        async with self._lock:
            generated_at = int(time.time())
            version = str(int(time.time()))
            next_cache = {
                "content": content,
                "formats": {
                    "yaml": content,
                    "raw": str(raw_content or ""),
                    "base64": str(base64_content or ""),
                },
                "node_count": int(node_count),
                "generated_at": generated_at,
                "version": version,
                "fingerprint": str(fingerprint or ""),
            }
            next_meta = dict(self._meta)
            next_meta["last_error"] = ""
            next_meta["last_error_at"] = 0
            self._save_if_changed("cache", next_cache)
            self._save_if_changed("meta", next_meta)

    async def write_error(self, *, message: str) -> None:
        async with self._lock:
            next_meta = dict(self._meta)
            next_meta["last_error"] = str(message or "")[:300]
            next_meta["last_error_at"] = int(time.time())
            self._save_if_changed("meta", next_meta)

    async def write_build_stats(
        self, stats: dict[str, Any], *, snapshot: dict[str, Any] | None = None
    ) -> None:
        async with self._lock:
            next_meta = dict(self._meta)
            next_meta["build_stats"] = dict(stats or {})
            next_meta["pool_snapshot"] = dict(snapshot or {})
            history = list(next_meta.get("build_history", []) or [])
            row = dict(stats or {})
            row["ts"] = int(time.time())
            history.append(row)
            next_meta["build_history"] = history[-20:]
            self._save_if_changed("meta", next_meta)

    async def read_history(self) -> list[dict[str, Any]]:
        async with self._lock:
            rows = list(self._meta.get("build_history", []) or [])
            return [dict(r) for r in rows]

    async def read_node_health(self) -> dict[str, Any]:
        async with self._lock:
            rows = self._node_health
            if not isinstance(rows, dict):
                return {}
            return dict(rows)

    async def write_node_health(self, rows: dict[str, Any]) -> None:
        async with self._lock:
            self._save_if_changed("node_health", dict(rows or {}))
