
from __future__ import annotations
import os
import unittest
from types import SimpleNamespace
from pathlib import Path

from handlers.commands.admin import make_checkall_command
from handlers.commands.basic import make_start_command
from services.usage_audit_service import UsageAuditService


class _FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        async def _delete():
            return None

        async def _edit_text(new_text, **new_kwargs):
            msg.text = new_text
            msg.kwargs = new_kwargs
            return msg

        msg = SimpleNamespace(text=text, kwargs=kwargs, delete=_delete)
        msg.edit_text = _edit_text
        self.replies.append(msg)
        return msg


class _FakeUpdate:
    def __init__(self, user_id=1):
        self.effective_user = SimpleNamespace(id=user_id, username="tester", full_name="Test User")
        self.message = _FakeMessage()


class _FakeContext:
    def __init__(self):
        self.args = []
        self.job_queue = None


class _FakeStorage:
    def __init__(self, subs=None):
        self.subs = subs or {}

    def get_all(self):
        return self.subs

    def begin_batch(self):
        return None

    def end_batch(self, save=True):
        return save

    def add_or_update(self, url, result, user_id=0):
        self.subs[url] = {"owner_uid": user_id, **result}

    def remove(self, url):
        self.subs.pop(url, None)


class _FakeAudit:
    def __init__(self):
        self.calls = []

    def log_check(self, **kwargs):
        self.calls.append(kwargs)


class P2BehaviorTest(unittest.IsolatedAsyncioTestCase):
    async def test_start_command_sends_no_permission_message(self):
        called = {"sent": False}

        async def send_no_permission_msg(update):
            called["sent"] = True
            await update.message.reply_text("denied")

        cmd = make_start_command(
            is_authorized=lambda update: False,
            is_owner=lambda update: False,
            send_no_permission_msg=send_no_permission_msg,
            logger=SimpleNamespace(warning=lambda *args, **kwargs: None),
        )

        update = _FakeUpdate()
        await cmd(update, _FakeContext())

        self.assertTrue(called["sent"])
        self.assertEqual(update.message.replies[-1].text, "denied")

    async def test_checkall_records_usage_audit(self):
        storage = _FakeStorage({"https://example.com/sub": {"owner_uid": 1001, "name": "sub"}})
        audit = _FakeAudit()

        class _Parser:
            async def parse(self, url):
                return {"name": "ok", "remaining": 10}

        async def get_parser():
            return _Parser()

        cmd = make_checkall_command(
            is_owner=lambda update: True,
            owner_only_msg="owner only",
            get_storage=lambda: storage,
            get_parser=get_parser,
            make_sub_keyboard=lambda url: url,
            admin_service=SimpleNamespace(build_checkall_report=lambda **kwargs: "report"),
            usage_audit_service=audit,
            schedule_auto_delete=lambda *args, **kwargs: None,
        )

        update = _FakeUpdate(user_id=42)
        await cmd(update, _FakeContext())

        self.assertEqual(len(audit.calls), 1)
        self.assertEqual(audit.calls[0]["source"], "/checkall")
        self.assertEqual(audit.calls[0]["urls"], ["https://example.com/sub"])

    def test_usage_audit_service_keeps_full_url_and_trims(self):
        tmpdir = Path("data/test_tmp")
        tmpdir.mkdir(parents=True, exist_ok=True)
        path = tmpdir / "audit_test.jsonl"
        if path.exists():
            path.unlink()

        try:
            service = UsageAuditService(str(path), max_records=3)
            user = SimpleNamespace(id=7, username="u", full_name="User")

            for i in range(5):
                service.log_check(
                    user=user,
                    urls=[f"https://example.com/sub/{i}?token=secret-{i}"],
                    source="test",
                )

            records = service.get_recent_records(limit=10)
            self.assertEqual(len(records), 3)
            self.assertEqual(records[-1]["urls"][0], "https://example.com/sub/4?token=secret-4")
        finally:
            if path.exists():
                path.unlink()


if __name__ == "__main__":
    unittest.main()
