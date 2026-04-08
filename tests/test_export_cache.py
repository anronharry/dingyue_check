from __future__ import annotations

import json
import os
import shutil
import unittest
from pathlib import Path

from services.export_cache_service import ERROR_FORBIDDEN, ExportCacheService


class ExportCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path("data/test_tmp/test_export_cache")
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        self.service = ExportCacheService(
            index_path=str(self.tmpdir / "db" / "export_cache_index.json"),
            cache_dir=str(self.tmpdir / "cache_exports"),
            ttl_hours=48,
        )
        self.result = {
            "_raw_content": "vmess://abc#node1",
            "_content_format": "text",
            "_normalized_nodes": [{"name": "node1", "protocol": "vmess", "raw": "vmess://abc#node1"}],
        }

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_successful_parse_writes_cache_index(self) -> None:
        self.service.save_subscription_cache(owner_uid=1, source="https://example.com/sub", result=self.result)
        self.assertEqual(len(self.service.get_index_snapshot()), 1)

    def test_yaml_and_txt_artifacts_are_generated(self) -> None:
        entry = self.service.save_subscription_cache(owner_uid=1, source="https://example.com/sub", result=self.result)
        self.assertTrue(os.path.exists(entry["yaml_path"]))
        self.assertTrue(os.path.exists(entry["txt_path"]))

    def test_permissions_are_respected(self) -> None:
        self.service.save_subscription_cache(owner_uid=1, source="https://example.com/sub", result=self.result)
        path, error = self.service.resolve_export_path(
            owner_uid=1,
            source="https://example.com/sub",
            fmt="yaml",
            requester_uid=2,
            is_owner=False,
        )
        self.assertIsNone(path)
        self.assertEqual(error, ERROR_FORBIDDEN)

    def test_expired_entries_are_cleaned_up(self) -> None:
        self.service.save_subscription_cache(owner_uid=1, source="https://example.com/sub", result=self.result)
        index_path = self.tmpdir / "db" / "export_cache_index.json"
        with open(index_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        key = next(iter(data))
        data[key]["expires_at"] = "2000-01-01 00:00:00"
        with open(index_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
        self.service = ExportCacheService(index_path=str(index_path), cache_dir=str(self.tmpdir / "cache_exports"), ttl_hours=48)
        self.assertEqual(self.service.cleanup_expired(), 1)

    def test_yaml_subscription_txt_export_contains_protocol_urls(self) -> None:
        yaml_result = {
            "_raw_content": (
                "proxies:\n"
                "  - name: hk-01\n"
                "    type: trojan\n"
                "    server: hk.example.com\n"
                "    port: 443\n"
                "    password: secret\n"
                "    sni: hk.example.com\n"
            ),
            "_content_format": "yaml",
            "_normalized_nodes": [
                {"name": "hk-01", "protocol": "trojan", "server": "hk.example.com", "port": 443}
            ],
        }
        entry = self.service.save_subscription_cache(owner_uid=1, source="https://example.com/yaml", result=yaml_result)
        txt_text = Path(entry["txt_path"]).read_text(encoding="utf-8")
        self.assertIn("trojan://", txt_text)
        self.assertIn("hk.example.com:443", txt_text)


if __name__ == "__main__":
    unittest.main()
