from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

from handlers.commands.admin import (
    make_globallist_command,
    make_owner_panel_command,
    make_recent_exports_command,
    make_recent_users_command,
    make_usage_audit_command,
)


class _FakeMessage:
    def __init__(self):
        self.replies: list[str] = []

    async def reply_text(self, text, **kwargs):
        del kwargs
        self.replies.append(text)
        return SimpleNamespace()


class _FakeUpdate:
    def __init__(self, user_id: int):
        self.effective_user = SimpleNamespace(id=user_id)
        self.message = _FakeMessage()


class AdminSoftDeprecationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._old_url = os.getenv("WEB_ADMIN_PUBLIC_URL")
        os.environ["WEB_ADMIN_PUBLIC_URL"] = "https://example.com/admin"

    def tearDown(self):
        if self._old_url is None:
            os.environ.pop("WEB_ADMIN_PUBLIC_URL", None)
        else:
            os.environ["WEB_ADMIN_PUBLIC_URL"] = self._old_url

    async def test_owner_panel_returns_web_migration_notice(self):
        cmd = make_owner_panel_command(
            is_owner=lambda update: True,
            owner_only_msg="owner only",
            admin_service=SimpleNamespace(),
            schedule_auto_delete=lambda *args, **kwargs: None,
        )
        update = _FakeUpdate(1)
        await cmd(update, SimpleNamespace())
        self.assertIn("控制台已迁移到 Web 后台", update.message.replies[-1])
        self.assertIn("https://example.com/admin", update.message.replies[-1])

    async def test_legacy_read_commands_redirect_to_web(self):
        commands = [
            make_usage_audit_command(
                is_owner=lambda update: True,
                owner_only_msg="owner only",
                admin_service=SimpleNamespace(),
                schedule_auto_delete=lambda *args, **kwargs: None,
            ),
            make_recent_users_command(
                is_owner=lambda update: True,
                owner_only_msg="owner only",
                admin_service=SimpleNamespace(),
                schedule_auto_delete=lambda *args, **kwargs: None,
            ),
            make_recent_exports_command(
                is_owner=lambda update: True,
                owner_only_msg="owner only",
                admin_service=SimpleNamespace(),
                schedule_auto_delete=lambda *args, **kwargs: None,
            ),
            make_globallist_command(
                is_owner=lambda update: True,
                owner_only_msg="owner only",
                admin_service=SimpleNamespace(),
                schedule_auto_delete=lambda *args, **kwargs: None,
            ),
        ]
        for cmd in commands:
            update = _FakeUpdate(1)
            await cmd(update, SimpleNamespace())
            self.assertIn("控制台已迁移到 Web 后台", update.message.replies[-1])
            self.assertIn("https://example.com/admin", update.message.replies[-1])

    async def test_non_owner_still_gets_owner_only(self):
        cmd = make_usage_audit_command(
            is_owner=lambda update: False,
            owner_only_msg="owner only",
            admin_service=SimpleNamespace(),
            schedule_auto_delete=lambda *args, **kwargs: None,
        )
        update = _FakeUpdate(2)
        await cmd(update, SimpleNamespace())
        self.assertEqual(update.message.replies[-1], "owner only")
