from __future__ import annotations

import os
import unittest
from pathlib import Path

from core.access_state import AccessStateStore


class AccessStateTest(unittest.TestCase):
    def test_set_allow_all_users_reports_saved_status(self):
        path = Path("data/test_tmp/access_state_test.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()

        try:
            store = AccessStateStore(str(path))
            changed, saved = store.set_allow_all_users(True)
            self.assertTrue(changed)
            self.assertTrue(saved)
            self.assertTrue(store.is_allow_all_users_enabled())
        finally:
            if path.exists():
                path.unlink()


if __name__ == "__main__":
    unittest.main()
