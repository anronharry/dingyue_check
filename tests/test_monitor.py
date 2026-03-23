from __future__ import annotations

import unittest

from app.bootstrap import build_application
from features import monitor


class _FakeStorage:
    def __init__(self, subs):
        self.subs = subs
        self.updated = []

    def get_all(self):
        return self.subs

    def add_or_update(self, url, result, user_id=0):
        self.updated.append((url, user_id, result))


class _FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, parse_mode=None):
        self.sent.append((chat_id, text, parse_mode))


class _FakeApp:
    def __init__(self):
        self.bot = _FakeBot()


class MonitorTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for job in monitor.scheduler.get_jobs():
            job.remove()

    async def test_configure_monitor_does_not_override_post_init(self):
        async def existing_post_init(application):
            return application

        app = build_application("123:TEST", existing_post_init, lambda application: application)
        original = app.post_init

        monitor.configure_monitor(app, _FakeStorage({}), lambda: None, None)

        self.assertIs(app.post_init, original)
        self.assertTrue(any(job.id == "sub_monitor" for job in monitor.scheduler.get_jobs()))

    async def test_check_subscriptions_job_sends_only_to_subscription_owner(self):
        storage = _FakeStorage(
            {
                "https://example.com/sub1": {"owner_uid": 1001},
                "https://example.com/sub2": {"owner_uid": 1002},
            }
        )

        class _Parser:
            async def parse(self, url):
                return {
                    "name": url.rsplit("/", 1)[-1],
                    "total": 10 * 1024 * 1024 * 1024,
                    "remaining": 1 * 1024 * 1024 * 1024,
                    "expire_time": None,
                }

        async def get_parser():
            return _Parser()

        app = _FakeApp()
        await monitor.check_subscriptions_job(app, storage, get_parser, None)

        sent_to = {item[0] for item in app.bot.sent}
        self.assertEqual(sent_to, {1001, 1002})
        self.assertEqual(len(app.bot.sent), 2)


if __name__ == "__main__":
    unittest.main()
