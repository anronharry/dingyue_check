from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from core.models import BatchCheckResult, SubscriptionEntity, SubscriptionStatus
from renderers.messages.admin_reports import render_subscription_check_report


class SubscriptionStatusLogicTest(unittest.TestCase):
    def test_from_parse_result_keeps_remaining_unknown_when_missing(self):
        entity = SubscriptionEntity.from_parse_result(
            url="https://example.com/sub",
            result={"name": "demo"},
            owner_uid=1,
        )
        self.assertIsNone(entity.remaining_bytes)
        self.assertEqual(entity.status, SubscriptionStatus.ACTIVE)

    def test_status_is_warning_when_remaining_is_zero(self):
        entity = SubscriptionEntity.from_parse_result(
            url="https://example.com/sub",
            result={"name": "demo", "remaining": 0},
            owner_uid=1,
        )
        self.assertEqual(entity.status, SubscriptionStatus.WARNING)

    def test_report_displays_unknown_remaining_for_warning_item(self):
        warning_item = SubscriptionEntity(
            url="https://example.com/sub",
            name="demo",
            remaining_bytes=None,
            expire_date=datetime.now() + timedelta(days=1),
            owner_uid=1,
            error=None,
        )
        text = render_subscription_check_report(
            batch=BatchCheckResult(entries=[warning_item]),
            format_traffic=lambda value: f"{value}B",
        )
        self.assertIn("需关注订阅", text)
        self.assertIn("剩余: 未知", text)


if __name__ == "__main__":
    unittest.main()
