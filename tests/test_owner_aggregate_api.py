from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from web import server as server_module
from web.server import AGG_STATE_KEY, RUNTIME_KEY, OwnerAggregateState, _owner_aggregate_info, _public_owner_subscription


class _FakeAggregateState:
    def __init__(self, *, token: str, cache: dict | None = None, meta: dict | None = None, history: list[dict] | None = None):
        self.token = token
        self.cache = dict(cache or {})
        self.meta = dict(meta or {})
        self.history = list(history or [])

    async def get_token(self):
        return self.token

    async def read_cache(self):
        return dict(self.cache)

    async def read_meta(self):
        return dict(self.meta)

    async def read_history(self):
        return list(self.history)

    async def write_error(self, *, message: str):
        self.meta["last_error"] = message

    async def write_cache(self, **kwargs):
        self.cache = dict(kwargs)

    async def write_build_stats(self, stats, *, snapshot=None):
        self.meta["build_stats"] = dict(stats or {})
        self.meta["pool_snapshot"] = dict(snapshot or {})


class OwnerAggregateStateTest(unittest.TestCase):
    def test_owner_aggregate_state_migrates_legacy_file_to_split_files(self):
        tmpdir = Path("data/db/test_owner_aggregate_state_case")
        shutil.rmtree(tmpdir, ignore_errors=True)
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            legacy_path = tmpdir / "owner_aggregate.json"
            legacy_path.write_text(
                json.dumps(
                    {
                        "token": "legacy-token",
                        "cache": {"content": "cached"},
                        "node_health": {"n1": {"status": "alive"}},
                        "build_stats": {"parsed_ok": 1},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            state = OwnerAggregateState(legacy_path, secret_key="demo")
            self.assertTrue(state.meta_path.exists())
            self.assertTrue(state.cache_path.exists())
            self.assertTrue(state.node_health_path.exists())
            self.assertEqual(json.loads(state.cache_path.read_text(encoding="utf-8"))["content"], "cached")
            self.assertIn("build_stats", json.loads(state.meta_path.read_text(encoding="utf-8")))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class OwnerAggregateApiTest(unittest.IsolatedAsyncioTestCase):

    async def test_owner_aggregate_info_returns_snapshot_and_cache_age(self):
        app = web.Application()
        app[RUNTIME_KEY] = SimpleNamespace(admin_service=SimpleNamespace(owner_id=7))
        app[AGG_STATE_KEY] = _FakeAggregateState(
            token="demo-token",
            cache={"generated_at": 100, "node_count": 12, "version": "v1"},
            meta={
                "last_error": "",
                "last_error_at": 0,
                "build_stats": {"parsed_ok": 4},
                "pool_snapshot": {"verify_mode": "ok", "timings_ms": {"parse": 12}, "delta": {"published_nodes": 2}},
            },
            history=[{"ts": 101, "published_nodes": 12}],
        )
        request = make_mocked_request("GET", "/api/v1/owner/aggregate-subscription", app=app, headers={"Host": "example.com"})
        response = await _owner_aggregate_info(request)
        data = json.loads(response.text)["data"]
        self.assertEqual(data["node_count"], 12)
        self.assertIn("cache_age_seconds", data)
        self.assertEqual(data["pool_snapshot"]["verify_mode"], "ok")
        self.assertEqual(data["pool_snapshot"]["timings_ms"]["parse"], 12)
        self.assertEqual(data["pool_snapshot"]["delta"]["published_nodes"], 2)

    async def test_public_owner_subscription_uses_cached_raw_without_rebuild(self):
        app = web.Application()
        app[RUNTIME_KEY] = SimpleNamespace(admin_service=SimpleNamespace(owner_id=7))
        app[AGG_STATE_KEY] = _FakeAggregateState(
            token="demo-token",
            cache={
                "content": "proxies: []\n",
                "formats": {"yaml": "proxies: []\n", "raw": "vmess://cached", "base64": "dm1lc3M6Ly9jYWNoZWQ="},
                "generated_at": 100,
                "node_count": 1,
                "version": "v2",
            },
        )
        request = make_mocked_request("GET", "/sub/demo-token/nodes", app=app, headers={"Host": "example.com"}, match_info={"token": "demo-token", "mode": "nodes"})
        original = server_module._build_owner_aggregate_bundle
        server_module._build_owner_aggregate_bundle = None
        try:
            response = await _public_owner_subscription(request)
        finally:
            server_module._build_owner_aggregate_bundle = original
        self.assertEqual(response.text, "vmess://cached")
        self.assertEqual(response.headers["X-Aggregate-Cache"], "hit")
        self.assertEqual(response.headers["X-Node-Count"], "1")


if __name__ == "__main__":
    unittest.main()
