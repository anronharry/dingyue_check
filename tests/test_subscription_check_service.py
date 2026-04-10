from __future__ import annotations

import asyncio
import unittest

from services.subscription_check_service import SubscriptionCheckService


class _FakeStore:
    def __init__(self):
        self.items = {}

    def add_or_update(self, url, result, user_id=0):
        self.items[url] = {"owner_uid": user_id, **result}

    def begin_batch(self):
        return None

    def end_batch(self, save=True):
        return save


class _ObservedParser:
    def __init__(self):
        self.current = 0
        self.max_seen = 0
        self._lock = asyncio.Lock()

    async def parse(self, url):
        async with self._lock:
            self.current += 1
            self.max_seen = max(self.max_seen, self.current)
        try:
            await asyncio.sleep(0.03)
            return {"name": f"sub:{url}", "remaining": 100}
        finally:
            async with self._lock:
                self.current -= 1


class _CaptureLogger:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.infos = []

    def error(self, msg, *args):
        self.errors.append(msg % args if args else msg)

    def warning(self, msg, *args):
        self.warnings.append(msg % args if args else msg)

    def info(self, msg, *args):
        self.infos.append(msg % args if args else msg)


class SubscriptionCheckServiceConcurrencyTest(unittest.IsolatedAsyncioTestCase):
    async def test_per_user_concurrency_limit_is_enforced(self):
        parser = _ObservedParser()
        store = _FakeStore()

        async def get_parser():
            return parser

        svc = SubscriptionCheckService(
            get_parser=get_parser,
            get_storage=lambda: store,
            logger=type("L", (), {"error": staticmethod(lambda *a, **k: None)})(),
            global_concurrency=20,
            user_concurrency=3,
        )
        urls = [f"https://example.com/sub/{i}" for i in range(12)]
        results = await svc.parse_subscription_urls(subscription_urls=urls, owner_uid=1001)

        self.assertEqual(len(results), 12)
        self.assertLessEqual(parser.max_seen, 3)

    async def test_global_concurrency_limit_is_enforced_across_users(self):
        parser = _ObservedParser()
        store = _FakeStore()

        async def get_parser():
            return parser

        svc = SubscriptionCheckService(
            get_parser=get_parser,
            get_storage=lambda: store,
            logger=type("L", (), {"error": staticmethod(lambda *a, **k: None)})(),
            global_concurrency=5,
            user_concurrency=4,
        )

        async def run_user(uid: int):
            urls = [f"https://example.com/u{uid}/{i}" for i in range(10)]
            return await svc.parse_subscription_urls(subscription_urls=urls, owner_uid=uid)

        await asyncio.gather(run_user(1), run_user(2), run_user(3))
        self.assertLessEqual(parser.max_seen, 5)

    async def test_retry_on_transient_error_then_success(self):
        store = _FakeStore()

        class _RetryParser:
            def __init__(self):
                self.calls = 0

            async def parse(self, url):
                self.calls += 1
                if self.calls == 1:
                    raise Exception("Connection reset by peer")
                return {"name": "ok", "remaining": 88}

        parser = _RetryParser()

        async def get_parser():
            return parser

        svc = SubscriptionCheckService(
            get_parser=get_parser,
            get_storage=lambda: store,
            logger=type("L", (), {"error": staticmethod(lambda *a, **k: None), "warning": staticmethod(lambda *a, **k: None)})(),
            global_concurrency=4,
            user_concurrency=2,
            retry_attempts=2,
            retry_backoff_seconds=0.01,
        )

        result = await svc.parse_and_store(url="https://example.com/retry", owner_uid=9)
        self.assertEqual(result["name"], "ok")
        self.assertEqual(parser.calls, 2)

    async def test_failed_result_uses_standardized_user_message(self):
        store = _FakeStore()

        class _BadParser:
            async def parse(self, url):
                raise Exception("解析订阅失败: connector error, very noisy traceback token=abc123")

        async def get_parser():
            return _BadParser()

        svc = SubscriptionCheckService(
            get_parser=get_parser,
            get_storage=lambda: store,
            logger=type("L", (), {"error": staticmethod(lambda *a, **k: None), "warning": staticmethod(lambda *a, **k: None)})(),
            global_concurrency=2,
            user_concurrency=1,
            retry_attempts=1,
        )

        rows = await svc.parse_subscription_urls(
            subscription_urls=["https://example.com/noisy"],
            owner_uid=9,
        )
        self.assertEqual(rows[0]["status"], "failed")
        self.assertEqual(rows[0]["error_code"], "network_error")
        self.assertIn("网络连接异常", rows[0]["error"])
        self.assertNotIn("token=abc123", rows[0]["error"])

    async def test_observability_logs_slow_and_periodic_stats(self):
        store = _FakeStore()
        logger = _CaptureLogger()

        class _SlowParser:
            async def parse(self, url):
                await asyncio.sleep(0.02)
                return {"name": "ok", "remaining": 1}

        async def get_parser():
            return _SlowParser()

        svc = SubscriptionCheckService(
            get_parser=get_parser,
            get_storage=lambda: store,
            logger=logger,
            global_concurrency=2,
            user_concurrency=1,
            retry_attempts=1,
            slow_threshold_seconds=0.01,
            stats_report_every=1,
        )

        await svc.parse_and_store(url="https://example.com/slow", owner_uid=1)
        snapshot = await svc.get_observability_snapshot()

        self.assertEqual(snapshot["total"], 1)
        self.assertEqual(snapshot["success"], 1)
        self.assertEqual(snapshot["slow"], 1)
        self.assertTrue(any("Slow subscription parse" in line for line in logger.warnings))
        self.assertTrue(any("Subscription parse stats" in line for line in logger.infos))
