from __future__ import annotations

import json
import os
import shutil
import unittest
import zipfile
from pathlib import Path

from services.backup_service import BackupService


class BackupRestoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cwd = os.getcwd()
        self.tmpdir = Path("data/test_tmp/test_backup_restore")
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        os.chdir(self.tmpdir)
        Path("data/db").mkdir(parents=True, exist_ok=True)
        Path("data/logs").mkdir(parents=True, exist_ok=True)
        Path("data/cache_exports").mkdir(parents=True, exist_ok=True)
        Path("data/db/subscriptions.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
        Path("data/db/users.json").write_text(json.dumps([1]), encoding="utf-8")
        Path("data/db/access_state.json").write_text(json.dumps({"allow_all_users": False}), encoding="utf-8")
        Path("data/db/user_profiles.json").write_text(json.dumps({"1": {"user_id": 1}}), encoding="utf-8")
        Path("data/db/export_cache_index.json").write_text(json.dumps({}), encoding="utf-8")
        Path("data/logs/usage_audit.jsonl").write_text('{"a":1}\n', encoding="utf-8")
        Path("data/cache_exports/cache.yaml").write_text("proxies: []", encoding="utf-8")
        self.service = BackupService(base_dir="data")

    def tearDown(self) -> None:
        os.chdir(self.cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_backup_archive_is_created(self) -> None:
        zip_path, _ = self.service.create_backup()
        self.assertTrue(Path(zip_path).exists())

    def test_restore_reconstructs_state(self) -> None:
        zip_path, _ = self.service.create_backup()
        external_zip = Path("backup_copy.zip")
        shutil.copy(zip_path, external_zip)
        shutil.rmtree(Path("data"))
        restored = self.service.restore_backup(str(external_zip))
        self.assertIn(os.path.normpath("data/db/subscriptions.json"), restored)
        self.assertTrue(Path("data/db/subscriptions.json").exists())

    def test_startup_bootstrap_restore_only_runs_on_empty_state(self) -> None:
        zip_path, _ = self.service.create_backup()
        bootstrap = Path("data/bootstrap_restore/latest_backup.zip")
        bootstrap.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(zip_path, bootstrap)
        restored, _ = self.service.auto_restore_if_needed(str(bootstrap))
        self.assertFalse(restored)
        shutil.rmtree(Path("data/db"))
        shutil.rmtree(Path("data/logs"))
        Path("data/db").mkdir(parents=True, exist_ok=True)
        Path("data/logs").mkdir(parents=True, exist_ok=True)
        shutil.copy(zip_path, bootstrap)
        restored, _ = self.service.auto_restore_if_needed(str(bootstrap))
        self.assertTrue(restored)

    def test_restore_skips_unsafe_zip_members(self) -> None:
        unsafe_zip = Path("unsafe_backup.zip")
        with zipfile.ZipFile(unsafe_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("../../evil.txt", "hacked")
            archive.writestr("C:/tmp/evil_windows.txt", "hacked")
            archive.writestr("data/db/users.json", "[2]")

        restored = self.service.restore_backup(str(unsafe_zip))
        self.assertIn(os.path.normpath("data/db/users.json"), restored)
        self.assertFalse(Path("evil.txt").exists())
        self.assertFalse(any("evil" in item for item in restored))

    def test_restore_rejects_oversized_uncompressed_payload(self) -> None:
        constrained = BackupService(base_dir="data", max_restore_total_bytes=8)
        large_zip = Path("too_large_backup.zip")
        with zipfile.ZipFile(large_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("data/db/too_large.txt", "0123456789")

        with self.assertRaises(ValueError):
            constrained.restore_backup(str(large_zip))

    def test_restore_backup_bytes_rejects_oversized_package(self) -> None:
        constrained = BackupService(base_dir="data", max_restore_total_bytes=8)
        with self.assertRaises(ValueError):
            constrained.restore_backup_bytes(b"0123456789")
