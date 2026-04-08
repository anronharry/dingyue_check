from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.admin_service import AdminService
from services.export_cache_service import ExportCacheService
from services.usage_audit_service import UsageAuditService
from services.user_profile_service import UserProfileService


class _FakeStorage:
    def __init__(self):
        self.grouped = {
            1: {
                "https://owner.example.com/sub": {
                    "name": "owner-sub",
                    "owner_uid": 1,
                    "remaining": 1,
                    "expire_time": "2099-01-01 00:00:00",
                }
            },
            2: {
                "https://example.com/1": {
                    "name": "alpha",
                    "owner_uid": 2,
                    "remaining": 100,
                    "expire_time": "2099-01-01 00:00:00",
                },
                "https://example.com/2": {
                    "name": "beta",
                    "owner_uid": 2,
                    "remaining": 200,
                    "expire_time": "2099-01-02 00:00:00",
                },
                "https://example.com/3": {
                    "name": "gamma",
                    "owner_uid": 2,
                    "remaining": 300,
                    "expire_time": "2099-01-03 00:00:00",
                },
                "https://example.com/4": {
                    "name": "delta",
                    "owner_uid": 2,
                    "remaining": 400,
                    "expire_time": "2099-01-04 00:00:00",
                },
                "https://example.com/5": {
                    "name": "epsilon",
                    "owner_uid": 2,
                    "remaining": 500,
                    "expire_time": "2099-01-05 00:00:00",
                },
            },
        }

    def get_all(self):
        merged = {}
        for subs in self.grouped.values():
            merged.update(subs)
        return merged

    def get_grouped_by_user(self):
        return self.grouped

    def get_statistics(self):
        return {"total": 6, "expired": 1, "active": 5, "total_remaining": 1500}


class UsageAuditPagingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path("data/test_tmp/test_usageaudit")
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        audit_path = self.tmpdir / "audit.jsonl"
        profile_path = self.tmpdir / "profiles.json"
        cache_index = self.tmpdir / "db" / "export_cache_index.json"
        cache_dir = self.tmpdir / "cache_exports"
        self.audit = UsageAuditService(str(audit_path))
        self.profiles = UserProfileService(str(profile_path))
        self.cache = ExportCacheService(index_path=str(cache_index), cache_dir=str(cache_dir), ttl_hours=48)
        self.storage = _FakeStorage()
        self.owner = SimpleNamespace(id=1, username="owner", full_name="Owner")
        self.other = SimpleNamespace(id=2, username="bob", full_name="Bob")
        self.profiles.touch_user(user=self.owner, source="/start", is_owner=True, is_authorized=True)
        self.profiles.touch_user(user=self.other, source="/check", is_owner=False, is_authorized=True)
        for index in range(7):
            self.audit.log_check(user=self.other, urls=[f"https://example.com/{index}"], source="/check")
        for index in range(2):
            self.audit.log_check(user=self.owner, urls=[f"https://owner.example.com/{index}"], source="/usageaudit")
        self.cache.save_generated_artifact(owner_uid=2, source="https://example.com/1", yaml_text="a: 1", txt_text="a")
        self.admin = AdminService(
            get_storage=lambda: self.storage,
            user_manager=SimpleNamespace(get_all=lambda: {1, 2}, is_owner=lambda uid: uid == 1),
            owner_id=1,
            format_traffic=lambda value: str(value),
            access_service=SimpleNamespace(is_allow_all_users_enabled=lambda: False),
            usage_audit_service=self.audit,
            user_profile_service=self.profiles,
            export_cache_service=self.cache,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_pagination_works(self) -> None:
        result = self.audit.query_records(owner_id=1, mode="others", page=2, page_size=5)
        self.assertEqual(result["page"], 2)
        self.assertEqual(len(result["records"]), 2)

    def test_default_mode_excludes_owner(self) -> None:
        result = self.audit.query_records(owner_id=1, mode="others", page=1, page_size=20)
        self.assertTrue(all(row["user_id"] != 1 for row in result["records"]))

    def test_mode_switching_works(self) -> None:
        owner_only = self.audit.query_records(owner_id=1, mode="owner", page=1, page_size=20)
        all_rows = self.audit.query_records(owner_id=1, mode="all", page=1, page_size=20)
        self.assertEqual(len(owner_only["records"]), 2)
        self.assertEqual(len(all_rows["records"]), 9)

    def test_page_boundaries_are_safe(self) -> None:
        result = self.audit.query_records(owner_id=1, mode="others", page=99, page_size=5)
        self.assertEqual(result["page"], result["total_pages"])

    def test_admin_report_returns_paging_metadata(self) -> None:
        report, paging = self.admin.build_usage_audit_report(mode="others", page=1, page_size=5)
        self.assertIn("使用审计", report)
        self.assertEqual(paging["page"], 1)

    def test_admin_detail_view_contains_full_urls(self) -> None:
        detail = self.admin.build_usage_audit_detail(mode="others", page=1, page_size=5, detail_index=0)
        self.assertIn("使用审计详情", detail)
        self.assertIn("https://example.com/", detail)

    def test_recent_users_report_prefers_non_owner_by_default(self) -> None:
        report = self.admin.build_recent_users_report(limit=5, include_owner=False)
        self.assertIn("最近活跃用户", report)
        self.assertIn("@bob", report)
        self.assertNotIn("@owner", report)

    def test_recent_exports_report_reads_export_audit(self) -> None:
        self.audit.log_check(user=self.other, urls=["https://example.com/exported"], source="导出缓存:yaml")
        report = self.admin.build_recent_exports_report(limit=5, include_owner=False)
        self.assertIn("最近导出记录", report)
        self.assertIn("YAML", report)
        self.assertIn("https://example.com/exported", report)

    def test_recent_users_page_includes_summary_stats(self) -> None:
        report, paging = self.admin.build_recent_users_page(include_owner=False, page=1, page_size=5)
        self.assertIn("24小时活跃", report)
        self.assertIn("已授权", report)
        self.assertEqual(paging["page"], 1)

    def test_recent_exports_page_includes_summary_stats(self) -> None:
        self.audit.log_check(user=self.other, urls=["https://example.com/exported"], source="导出缓存:yaml")
        report, paging = self.admin.build_recent_exports_page(include_owner=False, page=1, page_size=5)
        self.assertIn("24小时导出", report)
        self.assertIn("YAML", report)
        self.assertEqual(paging["page"], 1)

    def test_owner_panel_text_includes_health_summary(self) -> None:
        panel = self.admin.build_owner_panel_text()
        self.assertIn("管理员控制台", panel)
        self.assertIn("异常订阅", panel)
        self.assertIn("有效缓存", panel)
        self.assertIn("全员可用", panel)

    def test_globallist_report_compacts_per_user_output(self) -> None:
        report = self.admin.build_globallist_report(max_users=5, max_subs_per_user=2)
        self.assertIn("全局订阅概览", report)
        self.assertIn("alpha", report)
        self.assertIn("beta", report)
        self.assertIn("其余 3 条已折叠", report)

    def test_admin_usage_report_reads_audit_file_once(self) -> None:
        with patch.object(self.audit, "get_recent_records", wraps=self.audit.get_recent_records) as mocked:
            self.admin.build_usage_audit_report(mode="others", page=1, page_size=5)
        self.assertEqual(mocked.call_count, 1)


if __name__ == "__main__":
    unittest.main()
