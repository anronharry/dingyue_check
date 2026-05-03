from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from web.server import _is_subscription_eligible


class OwnerAggregateEligibilityTest(unittest.TestCase):
    def test_yaml_like_subscription_without_traffic_metadata_is_eligible(self):
        now = datetime(2026, 5, 3, 10, 0, 0)
        row = {
            "last_check_status": "success",
            "total": 0,
            "remaining": 0,
            "expire_time": None,
        }
        self.assertTrue(_is_subscription_eligible(row, now=now))

    def test_subscription_with_positive_total_and_zero_remaining_is_ineligible(self):
        now = datetime(2026, 5, 3, 10, 0, 0)
        row = {
            "last_check_status": "success",
            "total": 1024,
            "remaining": 0,
            "expire_time": None,
        }
        self.assertFalse(_is_subscription_eligible(row, now=now))

    def test_subscription_with_past_expire_time_is_ineligible(self):
        now = datetime(2026, 5, 3, 10, 0, 0)
        row = {
            "last_check_status": "success",
            "total": 0,
            "remaining": 0,
            "expire_time": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.assertFalse(_is_subscription_eligible(row, now=now))


if __name__ == "__main__":
    unittest.main()
