from __future__ import annotations

import shutil
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.user_profile_service import UserProfileService


class UserProfileServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path("data/test_tmp/test_user_profiles")
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        self.path = self.tmpdir / "user_profiles.json"
        self.service = UserProfileService(str(self.path))
        self.user = SimpleNamespace(id=123, username="alice", full_name="Alice Zhang")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_first_interaction_creates_profile(self) -> None:
        self.service.touch_user(user=self.user, source="/check", is_owner=False, is_authorized=True)
        profile = self.service.get_profile(123)
        self.assertEqual(profile["username"], "alice")
        self.assertEqual(profile["last_source"], "/check")

    def test_subsequent_interaction_updates_last_seen(self) -> None:
        self.service.touch_user(user=self.user, source="/check", is_owner=False, is_authorized=True)
        first_seen_at = self.service.get_profile(123)["first_seen_at"]
        first_last_seen = self.service.get_profile(123)["last_seen_at"]
        time.sleep(1)
        self.service.touch_user(user=self.user, source="/list", is_owner=False, is_authorized=True)
        profile = self.service.get_profile(123)
        self.assertEqual(profile["first_seen_at"], first_seen_at)
        self.assertNotEqual(profile["last_seen_at"], first_last_seen)
        self.assertEqual(profile["last_source"], "/list")

    def test_owner_formatting_prefers_clickable_mention(self) -> None:
        self.service.touch_user(user=self.user, source="/check", is_owner=False, is_authorized=True)
        formatted = self.service.format_user_identity(123)
        self.assertIn("tg://user?id=123", formatted)
        self.assertIn("@alice", formatted)
