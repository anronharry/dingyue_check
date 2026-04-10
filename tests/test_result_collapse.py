from __future__ import annotations

import unittest
from types import SimpleNamespace

from handlers.messages.subscriptions import make_subscription_handler


class _FakeMessage:
    def __init__(self, text="https://example.com/sub"):
        self.text = text
        self.sent = []

    async def reply_text(self, text, **kwargs):
        msg = SimpleNamespace(text=text, kwargs=kwargs)
        self.sent.append(msg)
        return msg


class ResultCollapseTest(unittest.IsolatedAsyncioTestCase):
    async def test_subscription_handler_sends_verbose_result_without_delayed_collapse(self):
        scheduled = []
        audit_calls = []

        class _DocService:
            async def parse_subscription_urls(self, *, subscription_urls, owner_uid):
                return [{"status": "success", "url": subscription_urls[0], "data": {"name": "A", "remaining": 1, "node_count": 2}}]

        def schedule_result_collapse(**kwargs):
            scheduled.append(kwargs)

        handler = make_subscription_handler(
            is_valid_url=lambda url: True,
            is_owner=lambda update: False,
            document_service=_DocService(),
            format_subscription_info=lambda info, url=None: f"verbose:{info['name']}",
            make_sub_keyboard=lambda url, owner_mode=False: f"kb:{url}:{owner_mode}",
            usage_audit_service=SimpleNamespace(log_check=lambda **kwargs: audit_calls.append(kwargs)),
            logger=SimpleNamespace(warning=lambda *a, **k: None, error=lambda *a, **k: None),
        )
        update = SimpleNamespace(effective_user=SimpleNamespace(id=7), message=_FakeMessage())
        await handler(update, SimpleNamespace(job_queue=True))
        self.assertTrue(update.message.sent[1].text.startswith("verbose:"))
        self.assertEqual(len(scheduled), 0)

    async def test_edit_failure_is_ignored(self):
        async def _edit_text(*args, **kwargs):
            raise RuntimeError("deleted")

        scheduled_job = None

        class _JobQueue:
            def run_once(self, callback, delay):
                nonlocal scheduled_job
                scheduled_job = callback

        from bot_async import schedule_result_collapse

        message = SimpleNamespace(edit_text=_edit_text)
        schedule_result_collapse(
            context=SimpleNamespace(job_queue=_JobQueue()),
            message=message,
            info={"name": "A"},
            url="https://example.com",
            formatter=lambda info, url=None: "compact",
            reply_markup=None,
        )
        await scheduled_job(SimpleNamespace())


if __name__ == "__main__":
    unittest.main()
