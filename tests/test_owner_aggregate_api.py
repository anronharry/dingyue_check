from __future__ import annotations

import asyncio
import json
import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from web.aggregate.api import _owner_aggregate_info, _public_owner_subscription
from web.aggregate.state import OwnerAggregateState
from web.constants import AGG_STATE_KEY, RUNTIME_KEY


class _FakeAggregateState:
    def __init__(
        self,
        *,
        token: str,
        cache: dict | None = None,
        meta: dict | None = None,
        history: list[dict] | None = None,
    ):
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
    def test_owner_aggregate_state_requires_secret_key(self):
        tmpdir = Path("data/db/test_owner_aggregate_missing_secret")
        shutil.rmtree(tmpdir, ignore_errors=True)
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            with self.assertRaisesRegex(RuntimeError, "WEB_ADMIN_TOKEN must be configured"):
                OwnerAggregateState(tmpdir / "owner_aggregate.json", secret_key="")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

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
            self.assertEqual(
                json.loads(state.cache_path.read_text(encoding="utf-8"))["content"], "cached"
            )
            self.assertIn("build_stats", json.loads(state.meta_path.read_text(encoding="utf-8")))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_owner_aggregate_state_creates_token_when_file_is_missing(self):
        tmpdir = Path("data/db/test_owner_aggregate_missing_file")
        shutil.rmtree(tmpdir, ignore_errors=True)
        try:
            state = OwnerAggregateState(tmpdir / "owner_aggregate.json", secret_key="demo")

            token = asyncio.run(state.get_token())
            meta = json.loads(state.meta_path.read_text(encoding="utf-8"))

            self.assertTrue(token)
            self.assertIn("token_enc", meta)
            self.assertNotIn("token", meta)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_owner_aggregate_state_migrates_plain_token_to_encrypted_meta(self):
        tmpdir = Path("data/db/test_owner_aggregate_token_migration")
        shutil.rmtree(tmpdir, ignore_errors=True)
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            legacy_path = tmpdir / "owner_aggregate.json"
            legacy_path.write_text(json.dumps({"token": "legacy-token"}), encoding="utf-8")
            state = OwnerAggregateState(legacy_path, secret_key="demo")

            token = asyncio.run(state.get_token())
            meta = json.loads(state.meta_path.read_text(encoding="utf-8"))

            self.assertEqual(token, "legacy-token")
            self.assertIn("token_enc", meta)
            self.assertNotIn("token", meta)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_owner_aggregate_state_rotates_token_and_clears_cache(self):
        tmpdir = Path("data/db/test_owner_aggregate_token_rotation")
        shutil.rmtree(tmpdir, ignore_errors=True)
        try:
            state = OwnerAggregateState(
                tmpdir / "owner_aggregate.json",
                secret_key="demo",
                rotate_cooldown_seconds=0,
            )
            with patch(
                "web.aggregate.state.secrets.token_urlsafe",
                side_effect=["initial-token", "rotated-token"],
            ):
                first_token = asyncio.run(state.get_token())
                asyncio.run(state.write_cache(content="cached", node_count=1))
                rotated_token = asyncio.run(state.rotate_token())
            meta = json.loads(state.meta_path.read_text(encoding="utf-8"))
            cache = json.loads(state.cache_path.read_text(encoding="utf-8"))

            self.assertEqual(first_token, "initial-token")
            self.assertEqual(rotated_token, "rotated-token")
            self.assertEqual(cache, {})
            self.assertIn("rotated_at", meta)
            self.assertIn("token_enc", meta)
            self.assertNotIn("token", meta)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_owner_aggregate_state_rejects_corrupted_json(self):
        tmpdir = Path("data/db/test_owner_aggregate_corrupted_state")
        shutil.rmtree(tmpdir, ignore_errors=True)
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            legacy_path = tmpdir / "owner_aggregate.json"
            legacy_path.write_text("{bad json", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "State file is corrupted"):
                OwnerAggregateState(legacy_path, secret_key="demo")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_owner_aggregate_state_rejects_non_object_json(self):
        tmpdir = Path("data/db/test_owner_aggregate_non_object_state")
        shutil.rmtree(tmpdir, ignore_errors=True)
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            legacy_path = tmpdir / "owner_aggregate.json"
            legacy_path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "must contain a JSON object"):
                OwnerAggregateState(legacy_path, secret_key="demo")
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
                "pool_snapshot": {
                    "verify_mode": "ok",
                    "timings_ms": {"parse": 12},
                    "delta": {"published_nodes": 2},
                },
            },
            history=[{"ts": 101, "published_nodes": 12}],
        )
        request = make_mocked_request(
            "GET", "/api/v1/owner/aggregate-subscription", app=app, headers={"Host": "example.com"}
        )
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
                "formats": {
                    "yaml": "proxies: []\n",
                    "raw": "vmess://cached",
                    "base64": "dm1lc3M6Ly9jYWNoZWQ=",
                },
                "generated_at": 100,
                "node_count": 1,
                "version": "v2",
            },
        )
        request = make_mocked_request(
            "GET",
            "/sub/demo-token/nodes",
            app=app,
            headers={"Host": "example.com"},
            match_info={"token": "demo-token", "mode": "nodes"},
        )
        response = await _public_owner_subscription(request)
        self.assertEqual(response.text, "vmess://cached")
        self.assertEqual(response.headers["X-Aggregate-Cache"], "hit")
        self.assertEqual(response.headers["X-Node-Count"], "1")


if __name__ == "__main__":
    unittest.main()
