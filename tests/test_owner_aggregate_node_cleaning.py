from __future__ import annotations

import unittest
from types import SimpleNamespace

from web.server import (
    AGG_PUBLISH_SERVER_LIMIT,
    AGG_PUBLISH_SOURCE_LIMIT,
    _aggregate_node_key,
    _dedupe_aggregate_nodes,
    _mark_aggregate_health,
    _quick_filter_aggregate_nodes,
)


class _FakeAggregateState:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})

    async def read_node_health(self):
        return dict(self.rows)

    async def write_node_health(self, rows):
        self.rows = dict(rows or {})


class OwnerAggregateNodeCleaningTest(unittest.IsolatedAsyncioTestCase):
    def test_dedupe_aggregate_nodes_removes_same_endpoint_auth_tuple(self):
        nodes = [
            {"name": "A", "type": "vmess", "server": "1.1.1.1", "port": 443, "uuid": "u1"},
            {"name": "B", "type": "vmess", "server": "1.1.1.1", "port": 443, "uuid": "u1"},
            {"name": "C", "type": "vmess", "server": "1.1.1.1", "port": 443, "uuid": "u2"},
        ]
        deduped = _dedupe_aggregate_nodes(nodes)
        self.assertEqual(len(deduped), 2)
        self.assertEqual(_aggregate_node_key(deduped[0]), ("vmess", "1.1.1.1", 443, "u1"))

    async def test_quick_filter_keeps_only_alive_nodes_and_attaches_latency(self):
        async def fake_ping(nodes, concurrency=80, timeout=1.8):
            del concurrency, timeout
            alive = [
                {"latency": 42.5, "raw_node": nodes[0]},
                {"latency": 88.1, "raw_node": nodes[2]},
            ]
            return 2, len(nodes), alive

        runtime = SimpleNamespace(document_service=SimpleNamespace(quick_ping_runner=fake_ping))
        state = _FakeAggregateState()
        nodes = [
            {"name": "A [src:x]", "type": "vmess", "server": "1.1.1.1", "port": 443, "uuid": "u1"},
            {"name": "B [src:x]", "type": "vmess", "server": "2.2.2.2", "port": 443, "uuid": "u2"},
            {"name": "C [src:y]", "type": "trojan", "server": "3.3.3.3", "port": 443, "password": "p3"},
        ]
        filtered, stats = await _quick_filter_aggregate_nodes(runtime, nodes, state=state)
        self.assertEqual(len(filtered), 2)
        self.assertEqual(stats["alive_nodes"], 2)
        self.assertEqual(filtered[0]["latency"], 42.5)
        self.assertEqual(filtered[1]["latency"], 88.1)

    async def test_quick_filter_falls_back_to_deduped_candidates_when_runner_missing(self):
        runtime = SimpleNamespace(document_service=SimpleNamespace(quick_ping_runner=None))
        state = _FakeAggregateState()
        nodes = [
            {"name": "A [src:x]", "type": "vmess", "server": "1.1.1.1", "port": 443, "uuid": "u1"},
            {"name": "B [src:x]", "type": "vmess", "server": "1.1.1.1", "port": 443, "uuid": "u1"},
        ]
        filtered, stats = await _quick_filter_aggregate_nodes(runtime, nodes, state=state)
        self.assertEqual(len(filtered), 1)
        self.assertFalse(stats["connectivity_filter_enabled"])

    async def test_cached_verified_success_streak_promotes_node_into_stable_pool(self):
        runtime = SimpleNamespace(document_service=SimpleNamespace(quick_ping_runner=None))
        state = _FakeAggregateState(
            {
                "stable-key": {
                    "mode": "verify",
                    "status": "alive",
                    "checked_at": 9999999999,
                    "latency": 23.0,
                    "success_streak": 3,
                    "failure_streak": 0,
                    "stable": True,
                }
            }
        )
        node = {"name": "A [src:x]", "type": "vmess", "server": "1.1.1.1", "port": 443, "uuid": "u1"}
        from web import server as server_module

        original = server_module._aggregate_node_cache_key
        server_module._aggregate_node_cache_key = lambda _node: "stable-key"
        try:
            filtered, stats = await _quick_filter_aggregate_nodes(runtime, [node], state=state)
        finally:
            server_module._aggregate_node_cache_key = original
        self.assertEqual(len(filtered), 1)
        self.assertEqual(stats["cache_stable_alive"], 1)
        self.assertEqual(stats["stable_pool_nodes"], 1)

    async def test_cached_dead_node_is_skipped_after_failure_threshold(self):
        runtime = SimpleNamespace(document_service=SimpleNamespace(quick_ping_runner=None))
        state = _FakeAggregateState(
            {
                "dead-key": {
                    "mode": "verify",
                    "status": "dead",
                    "checked_at": 9999999999,
                    "latency": 0.0,
                    "success_streak": 0,
                    "failure_streak": 3,
                    "stable": False,
                }
            }
        )
        node = {"name": "A [src:x]", "type": "vmess", "server": "1.1.1.1", "port": 443, "uuid": "u1"}
        from web import server as server_module

        original = server_module._aggregate_node_cache_key
        server_module._aggregate_node_cache_key = lambda _node: "dead-key"
        try:
            filtered, _stats = await _quick_filter_aggregate_nodes(runtime, [node], state=state)
        finally:
            server_module._aggregate_node_cache_key = original
        self.assertEqual(filtered, [])

    def test_mark_aggregate_health_updates_streaks_and_health_score(self):
        first = _mark_aggregate_health("quick", "alive")
        self.assertEqual(first["success_streak"], 1)
        self.assertEqual(first["failure_streak"], 0)
        self.assertGreater(first["health_score"], 0)

        second = _mark_aggregate_health("verify", "alive", previous=first)
        self.assertGreater(second["health_score"], first["health_score"])
        self.assertTrue(second["stable"])

        third = _mark_aggregate_health("verify", "dead", previous=second)
        self.assertEqual(third["success_streak"], 0)
        self.assertEqual(third["failure_streak"], 1)
        self.assertLess(third["health_score"], second["health_score"])

    async def test_quick_filter_exposes_pool_snapshot_metrics(self):
        async def fake_ping(nodes, concurrency=80, timeout=1.8):
            del concurrency, timeout
            return 1, len(nodes), [{"latency": 31.5, "raw_node": nodes[0]}]

        runtime = SimpleNamespace(document_service=SimpleNamespace(quick_ping_runner=fake_ping))
        state = _FakeAggregateState()
        nodes = [
            {"name": "A [src:x]", "type": "vmess", "server": "1.1.1.1", "port": 443, "uuid": "u1"},
            {"name": "B [src:y]", "type": "vmess", "server": "2.2.2.2", "port": 443, "uuid": "u2"},
        ]
        filtered, stats = await _quick_filter_aggregate_nodes(runtime, nodes, state=state)
        self.assertEqual(len(filtered), 1)
        self.assertIn("pool_snapshot", stats)
        self.assertEqual(stats["pool_snapshot"]["published_nodes"], 1)
        self.assertEqual(stats["pool_snapshot"]["tested_nodes"], 2)
        self.assertIn("top_sources", stats["pool_snapshot"])

    async def test_quick_filter_applies_publish_diversity_limits(self):
        async def fake_ping(nodes, concurrency=80, timeout=1.8):
            del concurrency, timeout
            alive = [{"latency": 20.0 + idx, "raw_node": node} for idx, node in enumerate(nodes)]
            return len(nodes), len(nodes), alive

        runtime = SimpleNamespace(document_service=SimpleNamespace(quick_ping_runner=fake_ping))
        state = _FakeAggregateState()
        nodes = []
        for idx in range(10):
            nodes.append({"name": f"A-{idx} [src:one]", "type": "vmess", "server": "1.1.1.1", "port": 443, "uuid": f"u{idx}"})
        for idx in range(3):
            nodes.append({"name": f"B-{idx} [src:two]", "type": "vmess", "server": f"2.2.2.{idx}", "port": 443, "uuid": f"v{idx}"})
        from web import server as server_module

        original = server_module._verify_aggregate_nodes_with_mihomo
        server_module._verify_aggregate_nodes_with_mihomo = lambda _nodes: (__import__("asyncio").sleep(0, result=([], {"verify_attempted": 0, "verify_alive": 0, "verify_mode": "disabled"})))
        try:
            filtered, _stats = await _quick_filter_aggregate_nodes(runtime, nodes, state=state)
        finally:
            server_module._verify_aggregate_nodes_with_mihomo = original
        source_one = [row for row in filtered if "[src:one]" in row["name"]]
        same_server = [row for row in filtered if row["server"] == "1.1.1.1"]
        self.assertLessEqual(len(source_one), AGG_PUBLISH_SOURCE_LIMIT)
        self.assertLessEqual(len(same_server), AGG_PUBLISH_SERVER_LIMIT)


if __name__ == "__main__":
    unittest.main()
