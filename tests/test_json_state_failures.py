from __future__ import annotations

import unittest
from pathlib import Path

from core.access_control import UserManager
from core.json_store import JsonStore
from core.storage_enhanced import SubscriptionStorage


class JsonStateFailureTest(unittest.TestCase):
    def test_json_store_raises_on_corrupted_state_file(self):
        path = Path("data/test_tmp/json_store_corrupted.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken", encoding="utf-8")

        try:
            with self.assertRaisesRegex(RuntimeError, "JSON state file is corrupted"):
                JsonStore(str(path), default_factory=dict)
        finally:
            if path.exists():
                path.unlink()

    def test_subscription_storage_raises_on_corrupted_state_file(self):
        path = Path("data/test_tmp/subscriptions_corrupted.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken", encoding="utf-8")

        try:
            with self.assertRaisesRegex(RuntimeError, "Subscriptions state file is corrupted"):
                SubscriptionStorage(str(path))
        finally:
            if path.exists():
                path.unlink()

    def test_user_manager_raises_on_corrupted_state_file(self):
        path = Path("data/test_tmp/users_corrupted.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken", encoding="utf-8")

        try:
            with self.assertRaisesRegex(RuntimeError, "Authorized users file is corrupted"):
                UserManager(str(path), owner_id=1)
        finally:
            if path.exists():
                path.unlink()


if __name__ == "__main__":
    unittest.main()
