"""Full-state backup and restore helpers."""
from __future__ import annotations

import json
import os
import shutil
import zipfile
from datetime import datetime

from core.json_store import JsonStore

class BackupService:
    def __init__(self, *, base_dir: str = "data"):
        self.base_dir = base_dir
        self.db_dir = os.path.join(base_dir, "db")
        self.logs_dir = os.path.join(base_dir, "logs")
        self.cache_dir = os.path.join(base_dir, "cache_exports")
        self.backups_dir = os.path.join(base_dir, "backups")
        self.bootstrap_dir = os.path.join(base_dir, "bootstrap_restore")
        os.makedirs(self.backups_dir, exist_ok=True)
        os.makedirs(self.bootstrap_dir, exist_ok=True)

    def _core_files(self) -> list[str]:
        return [
            os.path.join(self.db_dir, "subscriptions.json"),
            os.path.join(self.db_dir, "users.json"),
            os.path.join(self.db_dir, "access_state.json"),
            os.path.join(self.db_dir, "user_profiles.json"),
            os.path.join(self.logs_dir, "usage_audit.jsonl"),
            os.path.join(self.db_dir, "export_cache_index.json"),
        ]

    def create_backup(self) -> tuple[str, str]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = os.path.join(self.backups_dir, f"backup_{timestamp}.zip")
        manifest = {
            "version": "2.0",
            "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "app": "dingyue_TG",
            "files": [],
        }
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in self._core_files():
                if os.path.exists(path):
                    arcname = os.path.relpath(path, start=".")
                    archive.write(path, arcname)
                    manifest["files"].append(arcname)
            if os.path.isdir(self.cache_dir):
                for name in os.listdir(self.cache_dir):
                    path = os.path.join(self.cache_dir, name)
                    if os.path.isfile(path):
                        arcname = os.path.relpath(path, start=".")
                        archive.write(path, arcname)
                        manifest["files"].append(arcname)
            archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        return zip_path, os.path.basename(zip_path)

    def restore_backup(self, zip_path: str) -> list[str]:
        restored = []
        with zipfile.ZipFile(zip_path, "r") as archive:
            for name in archive.namelist():
                if name.endswith("/") or name == "manifest.json":
                    continue
                normalized = os.path.normpath(name)
                if normalized.startswith(".."):
                    continue
                target_path = os.path.join(".", normalized)
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                with archive.open(name) as src, open(target_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                restored.append(normalized)
        return restored

    def restore_backup_bytes(self, content_bytes: bytes) -> list[str]:
        tmp_path = os.path.join(self.backups_dir, f"restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")
        with open(tmp_path, "wb") as handle:
            handle.write(content_bytes)
        try:
            return self.restore_backup(tmp_path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def is_core_state_empty(self) -> bool:
        for path in self._core_files():
            if not os.path.exists(path):
                continue
            try:
                if os.path.getsize(path) == 0:
                    continue
                if path.endswith(".json"):
                    data = JsonStore(path, default_factory=dict).get_data()
                    if data:
                        return False
                else:
                    with open(path, "r", encoding="utf-8") as handle:
                        if handle.read().strip():
                            return False
            except Exception:
                return False
        return True

    def auto_restore_if_needed(self, bootstrap_zip_path: str | None = None) -> tuple[bool, str]:
        zip_path = bootstrap_zip_path or os.path.join(self.bootstrap_dir, "latest_backup.zip")
        if not os.path.exists(zip_path):
            return False, "bootstrap package not found"
        if not self.is_core_state_empty():
            return False, "existing state is not empty"
        self.restore_backup(zip_path)
        archived = zip_path + ".restored"
        os.replace(zip_path, archived)
        return True, archived
