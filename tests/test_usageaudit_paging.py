from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.admin_service import AdminService
from services.usage_audit_service import UsageAuditService
from services.user_profile_service import UserProfileService


class UsageAuditPagingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path("data/test_tmp/test_usageaudit")
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        audit_path = self.tmpdir / "audit.jsonl"
        profile_path = self.tmpdir / "profiles.json"
        self.audit = UsageAuditService(str(audit_path))
        self.profiles = UserProfileService(str(profile_path))
        self.owner = SimpleNamespace(id=1, username="owner", full_name="Owner")
        self.other = SimpleNamespace(id=2, username="bob", full_name="Bob")
        self.profiles.touch_user(user=self.owner, source="/start", is_owner=True, is_authorized=True)
        self.profiles.touch_user(user=self.other, source="/check", is_owner=False, is_authorized=True)
        for index in range(7):
            self.audit.log_check(user=self.other, urls=[f"https://example.com/{index}"], source="/check")
        for index in range(2):
            self.audit.log_check(user=self.owner, urls=[f"https://owner.example.com/{index}"], source="/usageaudit")
        self.admin = AdminService(
            get_storage=lambda: None,
            user_manager=SimpleNamespace(get_all=lambda: {1, 2}, is_owner=lambda uid: uid == 1),
            owner_id=1,
            format_traffic=lambda value: str(value),
            access_service=SimpleNamespace(is_allow_all_users_enabled=lambda: False),
            usage_audit_service=self.audit,
            user_profile_service=self.profiles,
            export_cache_service=SimpleNamespace(get_entry=lambda **kwargs: None, get_index_snapshot=lambda: {}),
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
