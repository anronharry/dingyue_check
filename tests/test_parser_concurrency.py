from __future__ import annotations

import asyncio
import unittest

from core.parser import SubscriptionParser


class _CountingParser(SubscriptionParser):
    def __init__(self):
        super().__init__(max_parse_concurrency=2, success_cache_ttl_seconds=30, success_cache_max_size=32)
        self.download_calls = 0

    async def _download_subscription(self, url):
        self.download_calls += 1
        await asyncio.sleep(0.03)
        return "trojan://password@example.org:443#JP01", {}

    async def _analyze_nodes(self, nodes):
        return {"protocols": {"trojan": len(nodes)}, "countries": {"其他": len(nodes)}, "locations": []}


class ParserConcurrencyTest(unittest.IsolatedAsyncioTestCase):
    async def test_same_url_concurrent_requests_share_single_fetch(self):
        parser = _CountingParser()

        async def _run_once():
            return await parser.parse("https://example.com/sub")

        results = await asyncio.gather(*[_run_once() for _ in range(8)])

        self.assertEqual(parser.download_calls, 1)
        self.assertTrue(all(item["node_count"] == 1 for item in results))

    async def test_success_cache_reuses_recent_result(self):
        parser = _CountingParser()

        await parser.parse("https://example.com/sub")
        await parser.parse("https://example.com/sub")

        self.assertEqual(parser.download_calls, 1)

    async def test_force_refresh_bypasses_short_cache(self):
        parser = _CountingParser()

        await parser.parse("https://example.com/sub")
        await parser.parse("https://example.com/sub", force_refresh=True)

        self.assertEqual(parser.download_calls, 2)


if __name__ == "__main__":
    unittest.main()
