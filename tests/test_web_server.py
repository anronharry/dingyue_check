from __future__ import annotations

import unittest
from types import SimpleNamespace

from aiohttp.test_utils import TestClient, TestServer

from web.server import build_web_app


class WebServerTest(unittest.IsolatedAsyncioTestCase):
    async def _make_client(
        self,
        token: str,
        *,
        username: str = "admin",
        allow_header_token: bool = True,
        cookie_secure: bool = False,
        trust_proxy: bool = False,
        login_window_seconds: int = 600,
        login_max_attempts: int = 10,
    ) -> TestClient:
        runtime = SimpleNamespace(
            admin_service=SimpleNamespace(
                get_owner_panel_data=lambda: {"total_subs": 3, "authorized_users": 2},
                get_recent_users_summary=lambda **kwargs: {"scope": "others", "rows": [], "args": kwargs},
                get_recent_exports_summary=lambda **kwargs: {"scope": "others", "rows": [], "args": kwargs},
                get_usage_audit_summary=lambda **kwargs: {"mode": kwargs.get("mode", "others"), "rows": []},
                get_globallist_data=lambda **kwargs: {"rows": [], "args": kwargs},
            )
        )
        app = build_web_app(
            runtime=runtime,
            web_admin_token=token,
            web_admin_username=username,
            web_admin_allow_header_token=allow_header_token,
            web_admin_session_ttl_seconds=3600,
            web_admin_cookie_secure=cookie_secure,
            web_admin_trust_proxy=trust_proxy,
            web_admin_login_window_seconds=login_window_seconds,
            web_admin_login_max_attempts=login_max_attempts,
        )
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        self.addAsyncCleanup(client.close)
        return client

    async def _login(self, client: TestClient, username: str = "admin", password: str = "secret"):
        return await client.post(
            "/admin/login",
            json={"username": username, "password": password},
        )

    async def test_healthz_is_public(self):
        client = await self._make_client("secret")
        resp = await client.get("/healthz")
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertTrue(payload["ok"])
        self.assertIn("security", payload)
        self.assertIn("cookie_secure", payload["security"])
        self.assertEqual(payload.get("auth_backend"), "memory")

    async def test_admin_redirects_to_login_without_auth(self):
        client = await self._make_client("secret")
        resp = await client.get("/admin", allow_redirects=False)
        self.assertEqual(resp.status, 302)
        self.assertIn("/admin/login", resp.headers.get("Location", ""))

    async def test_login_success_then_access_api_by_cookie(self):
        client = await self._make_client("secret")
        login_resp = await self._login(client, username="admin", password="secret")
        self.assertEqual(login_resp.status, 200)
        payload = await login_resp.json()
        self.assertTrue(payload["ok"])

        resp = await client.get("/api/v1/system/overview")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["data"]["total_subs"], 3)

    async def test_login_rejects_invalid_credentials(self):
        client = await self._make_client("secret")
        resp = await self._login(client, username="admin", password="wrong")
        self.assertEqual(resp.status, 401)
        payload = await resp.json()
        self.assertEqual(payload["error"], "invalid_credentials")

    async def test_overview_rejects_missing_auth(self):
        client = await self._make_client("secret")
        resp = await client.get("/api/v1/system/overview")
        self.assertEqual(resp.status, 401)
        payload = await resp.json()
        self.assertEqual(payload["error"], "unauthorized")

    async def test_overview_accepts_valid_header_token_when_enabled(self):
        client = await self._make_client("secret", allow_header_token=True)
        resp = await client.get(
            "/api/v1/system/overview",
            headers={"X-Admin-Token": "secret"},
        )
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertTrue(payload["ok"])

    async def test_overview_rejects_header_token_when_disabled(self):
        client = await self._make_client("secret", allow_header_token=False)
        resp = await client.get(
            "/api/v1/system/overview",
            headers={"X-Admin-Token": "secret"},
        )
        self.assertEqual(resp.status, 401)
        payload = await resp.json()
        self.assertEqual(payload["error"], "unauthorized")

    async def test_api_returns_503_if_token_not_configured(self):
        client = await self._make_client("")
        resp = await client.get("/api/v1/system/overview")
        self.assertEqual(resp.status, 503)
        payload = await resp.json()
        self.assertEqual(payload["error"], "web_admin_token_not_configured")

    async def test_recent_users_uses_scope_and_limit(self):
        client = await self._make_client("secret")
        await self._login(client)
        resp = await client.get("/api/v1/users/recent?scope=all&limit=7")
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["data"]["args"]["include_owner"])
        self.assertEqual(payload["data"]["args"]["limit"], 7)

    async def test_recent_users_rejects_bad_scope(self):
        client = await self._make_client("secret")
        await self._login(client)
        resp = await client.get("/api/v1/users/recent?scope=bad")
        self.assertEqual(resp.status, 400)
        payload = await resp.json()
        self.assertEqual(payload["error"], "invalid_scope")

    async def test_audit_summary_rejects_bad_mode(self):
        client = await self._make_client("secret")
        await self._login(client)
        resp = await client.get("/api/v1/audit/summary?mode=bad")
        self.assertEqual(resp.status, 400)
        payload = await resp.json()
        self.assertEqual(payload["error"], "invalid_mode")

    async def test_global_subscriptions_supports_limits(self):
        client = await self._make_client("secret")
        await self._login(client)
        resp = await client.get("/api/v1/subscriptions/global?max_users=12&max_subs_per_user=5")
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertEqual(payload["data"]["args"]["max_users"], 12)
        self.assertEqual(payload["data"]["args"]["max_subs_per_user"], 5)

    async def test_logout_clears_cookie_session(self):
        client = await self._make_client("secret")
        await self._login(client)
        before = await client.get("/api/v1/system/overview")
        self.assertEqual(before.status, 200)

        out = await client.post("/admin/logout")
        self.assertEqual(out.status, 200)

        after = await client.get("/api/v1/system/overview")
        self.assertEqual(after.status, 401)

    async def test_secure_cookie_flag_enabled(self):
        client = await self._make_client("secret", cookie_secure=True)
        resp = await self._login(client, username="admin", password="secret")
        self.assertEqual(resp.status, 200)
        raw = resp.headers.get("Set-Cookie", "")
        self.assertIn("Secure", raw)
        self.assertIn("HttpOnly", raw)

    async def test_login_rate_limit_blocks_excessive_attempts(self):
        client = await self._make_client("secret", login_window_seconds=600, login_max_attempts=2)
        r1 = await self._login(client, username="admin", password="bad")
        r2 = await self._login(client, username="admin", password="bad")
        r3 = await self._login(client, username="admin", password="bad")
        self.assertEqual(r1.status, 401)
        self.assertEqual(r2.status, 401)
        self.assertEqual(r3.status, 429)

    async def test_rate_limit_uses_forwarded_for_when_trust_proxy(self):
        client = await self._make_client("secret", trust_proxy=True, login_window_seconds=600, login_max_attempts=1)
        r1 = await client.post(
            "/admin/login",
            json={"username": "admin", "password": "bad"},
            headers={"X-Forwarded-For": "1.1.1.1"},
        )
        r2 = await client.post(
            "/admin/login",
            json={"username": "admin", "password": "bad"},
            headers={"X-Forwarded-For": "1.1.1.1"},
        )
        r3 = await client.post(
            "/admin/login",
            json={"username": "admin", "password": "bad"},
            headers={"X-Forwarded-For": "2.2.2.2"},
        )
        self.assertEqual(r1.status, 401)
        self.assertEqual(r2.status, 429)
        self.assertEqual(r3.status, 401)
