"""Temporary export artifact cache for parsed subscriptions and conversion outputs."""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta

import yaml
from core.json_store import JsonStore


class ExportCacheService:
    def __init__(self, *, index_path: str, cache_dir: str, ttl_hours: int = 48):
        self.index_path = index_path
        self.cache_dir = cache_dir
        self.ttl_hours = ttl_hours
        self.store = JsonStore(index_path, default_factory=dict)
        self._index = self.store.get_data()
        os.makedirs(self.cache_dir, exist_ok=True)

    @staticmethod
    def _now() -> datetime:
        return datetime.now()

    @staticmethod
    def _ts(value: datetime) -> str:
        return value.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _parse_ts(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    @staticmethod
    def make_source_key(source: str, *, owner_uid: int) -> str:
        return f"{owner_uid}:{source}"

    def _build_paths(self, *, owner_uid: int, source_key: str) -> tuple[str, str, str]:
        digest = hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:12]
        prefix = f"{owner_uid}_{digest}"
        return (
            os.path.join(self.cache_dir, f"{prefix}.yaml"),
            os.path.join(self.cache_dir, f"{prefix}.txt"),
            os.path.join(self.cache_dir, f"{prefix}.raw"),
        )

    def save_subscription_cache(self, *, owner_uid: int, source: str, result: dict) -> dict | None:
        raw_content = result.get("_raw_content")
        if raw_content is None:
            return None
        source_key = self.make_source_key(source, owner_uid=owner_uid)
        yaml_path, txt_path, raw_path = self._build_paths(owner_uid=owner_uid, source_key=source_key)
        content_format = (result.get("_content_format") or "unknown").lower()
        nodes = result.get("_normalized_nodes") or result.get("_raw_nodes") or []
        yaml_text = self._build_yaml_text(content_format=content_format, raw_content=raw_content, nodes=nodes)
        txt_text = self._build_txt_text(content_format=content_format, raw_content=raw_content, nodes=nodes)
        self._write_text(yaml_path, yaml_text)
        self._write_text(txt_path, txt_text)
        self._write_text(raw_path, str(raw_content))
        now = self._now()
        self._index[source_key] = {
            "source": source,
            "owner_uid": owner_uid,
            "created_at": self._ts(now),
            "expires_at": self._ts(now + timedelta(hours=self.ttl_hours)),
            "yaml_path": yaml_path,
            "txt_path": txt_path,
            "raw_snapshot_path": raw_path,
            "last_exported_at": None,
        }
        self.store.save()
        return self._index[source_key]

    def save_generated_artifact(self, *, owner_uid: int, source: str, yaml_text: str | None = None, txt_text: str | None = None) -> dict:
        source_key = self.make_source_key(source, owner_uid=owner_uid)
        yaml_path, txt_path, raw_path = self._build_paths(owner_uid=owner_uid, source_key=source_key)
        now = self._now()
        if yaml_text is not None:
            self._write_text(yaml_path, yaml_text)
        if txt_text is not None:
            self._write_text(txt_path, txt_text)
        self._write_text(raw_path, source)
        self._index[source_key] = {
            "source": source,
            "owner_uid": owner_uid,
            "created_at": self._ts(now),
            "expires_at": self._ts(now + timedelta(hours=self.ttl_hours)),
            "yaml_path": yaml_path if os.path.exists(yaml_path) else None,
            "txt_path": txt_path if os.path.exists(txt_path) else None,
            "raw_snapshot_path": raw_path,
            "last_exported_at": None,
        }
        self.store.save()
        return self._index[source_key]

    @staticmethod
    def _write_text(path: str, content: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    @staticmethod
    def _build_yaml_text(*, content_format: str, raw_content: str, nodes: list[dict]) -> str:
        if content_format == "yaml":
            return raw_content
        proxies = []
        for index, node in enumerate(nodes, start=1):
            proxies.append(
                {
                    "name": node.get("name", f"node-{index}"),
                    "type": node.get("protocol", "unknown"),
                    "server": node.get("server") or "unknown",
                    "port": node.get("port") or 0,
                }
            )
        return yaml.safe_dump({"proxies": proxies}, allow_unicode=True, sort_keys=False)

    @staticmethod
    def _build_txt_text(*, content_format: str, raw_content: str, nodes: list[dict]) -> str:
        if content_format in {"base64", "txt", "text"}:
            return raw_content
        raw_lines = [node.get("raw") for node in nodes if node.get("raw")]
        if raw_lines:
            return "\n".join(raw_lines)
        return "\n".join(node.get("name", "unknown") for node in nodes)

    def get_entry(self, *, owner_uid: int, source: str) -> dict | None:
        source_key = self.make_source_key(source, owner_uid=owner_uid)
        entry = self._index.get(source_key)
        if not entry:
            return None
        expires_at = self._parse_ts(entry.get("expires_at"))
        if expires_at and expires_at < self._now():
            self.delete_entry(owner_uid=owner_uid, source=source)
            return None
        return entry

    def resolve_export_path(self, *, owner_uid: int, source: str, fmt: str, requester_uid: int, is_owner: bool) -> tuple[str | None, str | None]:
        entry = self.get_entry(owner_uid=owner_uid, source=source)
        if not entry:
            return None, "缓存不存在或已过期"
        if requester_uid != owner_uid and not is_owner:
            return None, "无权导出他人的缓存"
        key = "yaml_path" if fmt == "yaml" else "txt_path"
        path = entry.get(key)
        if not path or not os.path.exists(path):
            return None, "缓存文件不存在"
        entry["last_exported_at"] = self._ts(self._now())
        self.store.save()
        return path, None

    def delete_entry(self, *, owner_uid: int, source: str, requester_uid: int | None = None, is_owner: bool = False) -> tuple[bool, str | None]:
        source_key = self.make_source_key(source, owner_uid=owner_uid)
        entry = self._index.get(source_key)
        if not entry:
            return False, "缓存不存在"
        if requester_uid is not None and requester_uid != owner_uid and not is_owner:
            return False, "无权删除他人的缓存"
        for key in ("yaml_path", "txt_path", "raw_snapshot_path"):
            path = entry.get(key)
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        self._index.pop(source_key, None)
        self.store.save()
        return True, None

    def cleanup_expired(self) -> int:
        removed = 0
        for source_key, entry in list(self._index.items()):
            expires_at = self._parse_ts(entry.get("expires_at"))
            if expires_at and expires_at < self._now():
                owner_uid = int(entry.get("owner_uid", 0))
                source = entry.get("source")
                if source is not None:
                    self.delete_entry(owner_uid=owner_uid, source=source)
                    removed += 1
        return removed

    def get_index_snapshot(self) -> dict[str, dict]:
        return self.store.snapshot()
