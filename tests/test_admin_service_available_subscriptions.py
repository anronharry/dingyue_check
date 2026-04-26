from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from services.admin_service import AdminService
from shared.format_helpers import format_traffic


class _Store:
    def __init__(self, payload: dict):
        self._payload = payload

    def get_all(self):
        return dict(self._payload)


class AdminServiceAvailableSubscriptionsTest(unittest.TestCase):
    def _build_service(self, payload: dict) -> AdminService:
        store = _Store(payload)
        return AdminService(
            get_storage=lambda: store,
            user_manager=SimpleNamespace(get_all=lambda: [1, 2]),
            owner_id=1,
            format_traffic=format_traffic,
            access_service=SimpleNamespace(is_allow_all_users_enabled=lambda: False, is_authorized_uid=lambda _uid: True),
            usage_audit_service=SimpleNamespace(max_read_records=1000, get_recent_records=lambda limit: []),
            user_profile_service=SimpleNamespace(format_user_identity=lambda uid: f"@user{uid} ({uid})"),
            export_cache_service=SimpleNamespace(get_index_snapshot=lambda: {}),
        )

    def test_filters_only_available_rows(self):
        now = datetime.now()
        payload = {
            "https://ok-1": {
                "name": "ok1",
                "owner_uid": 2,
                "remaining": 1024,
                "expire_time": (now + timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
                "last_check_status": "success",
                "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            },
            "https://expired": {
                "name": "expired",
                "owner_uid": 2,
                "remaining": 4096,
                "expire_time": (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
                "last_check_status": "success",
                "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            },
            "https://failed": {
                "name": "failed",
                "owner_uid": 2,
                "remaining": 4096,
                "expire_time": (now + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"),
                "last_check_status": "failed",
                "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            },
            "https://empty": {
                "name": "empty",
                "owner_uid": 2,
                "remaining": 0,
                "expire_time": (now + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"),
                "last_check_status": "success",
                "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            },
        }
        service = self._build_service(payload)
        data = service.get_available_subscriptions_data(page=1, limit=20)
        self.assertEqual(data["total"], 1)
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(data["rows"][0]["url"], "https://ok-1")

    def test_supports_pagination(self):
        now = datetime.now()
        payload = {}
        for idx in range(1, 4):
            payload[f"https://ok-{idx}"] = {
                "name": f"ok{idx}",
                "owner_uid": 2,
                "remaining": 1000 + idx,
                "expire_time": (now + timedelta(days=idx)).strftime("%Y-%m-%d %H:%M:%S"),
                "last_check_status": "success",
                "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            }
        service = self._build_service(payload)
        page1 = service.get_available_subscriptions_data(page=1, limit=2)
        page2 = service.get_available_subscriptions_data(page=2, limit=2)
        self.assertEqual(page1["total"], 3)
        self.assertEqual(page1["total_pages"], 2)
        self.assertEqual(len(page1["rows"]), 2)
        self.assertEqual(len(page2["rows"]), 1)

