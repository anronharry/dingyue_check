from __future__ import annotations

import builtins
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp import web

from web.auth import MemoryAuthBackend, build_auth_backend as _build_auth_backend
from web.aggregate.lifecycle import _validate_auth_backend
from web.constants import (
    ALLOW_HEADER_TOKEN_KEY,
    AUTH_BACKEND_KEY,
    COOKIE_SECURE_KEY,
    LOGIN_MAX_ATTEMPTS_KEY,
    LOGIN_WINDOW_KEY,
    REDIS_ALLOW_MEMORY_FALLBACK_KEY,
    SESSION_COOKIE,
    SESSION_TTL_KEY,
    TOKEN_KEY,
    USERNAME_KEY,
    RUNTIME_KEY,
    STARTED_AT_KEY,
    TRUST_PROXY_KEY,
)
from web import build_web_app
from web.session_api import _auth_middleware, _login
from web.health import _healthz
from web.admin.detail_api import _user_detail
from web.admin.owner_api import _owner_check_all, _owner_import_json
from web.admin.system_api import _runtime_status
from web.admin.subscriptions_api import _subscriptions_available
from web.admin.users_api import _recent_users


def _raise_for_redis_import(name, *args, **kwargs):
    if name == "redis.asyncio" or name == "redis":
        raise ImportError("redis is not installed")
    return _ORIGINAL_IMPORT(name, *args, **kwargs)


_ORIGINAL_IMPORT = builtins.__import__


class WebAdminConfigTest(unittest.TestCase):
    def test_build_auth_backend_uses_memory_when_redis_url_is_empty(self):
        backend = _build_auth_backend("")
        self.assertIsInstance(backend, MemoryAuthBackend)

    def test_build_auth_backend_fails_when_configured_redis_is_unavailable(self):
        with patch("builtins.__import__", side_effect=_raise_for_redis_import):
            with self.assertRaisesRegex(RuntimeError, "WEB_ADMIN_REDIS_URL is configured"):
                _build_auth_backend("redis://127.0.0.1:6379/0")

    def test_build_auth_backend_only_falls_back_when_explicitly_allowed(self):
        with patch("builtins.__import__", side_effect=_raise_for_redis_import):
            backend = _build_auth_backend(
                "redis://127.0.0.1:6379/0",
                allow_memory_fallback=True,
            )
        self.assertIsInstance(backend, MemoryAuthBackend)

    def test_build_web_app_requires_web_admin_token(self):
        with self.assertRaisesRegex(RuntimeError, "WEB_ADMIN_TOKEN must be configured"):
            build_web_app(runtime=SimpleNamespace(), web_admin_token="")


class WebAdminStartupValidationTest(unittest.IsolatedAsyncioTestCase):
    async def test_startup_validation_fails_when_redis_ping_fails(self):
        app = web.Application()
        app[AUTH_BACKEND_KEY] = _FailingRedisBackend()
        app[REDIS_ALLOW_MEMORY_FALLBACK_KEY] = False

        with self.assertRaisesRegex(RuntimeError, "Redis auth backend is unreachable"):
            await _validate_auth_backend(app)

    async def test_startup_validation_falls_back_when_explicitly_allowed(self):
        app = web.Application()
        app[AUTH_BACKEND_KEY] = _FailingRedisBackend()
        app[REDIS_ALLOW_MEMORY_FALLBACK_KEY] = True

        await _validate_auth_backend(app)

        self.assertIsInstance(app[AUTH_BACKEND_KEY], MemoryAuthBackend)


class WebAdminHealthTest(unittest.IsolatedAsyncioTestCase):
    async def test_healthz_reports_security_and_auth_backend(self):
        app = web.Application()
        app[AUTH_BACKEND_KEY] = MemoryAuthBackend()
        app[COOKIE_SECURE_KEY] = True
        app[ALLOW_HEADER_TOKEN_KEY] = False
        app[TRUST_PROXY_KEY] = True
        app[LOGIN_WINDOW_KEY] = 120
        app[LOGIN_MAX_ATTEMPTS_KEY] = 3
        request = SimpleNamespace(app=app)

        response = await _healthz(request)
        payload = response.text

        self.assertIn('"service": "web-admin"', payload)
        self.assertIn('"auth_backend": "memory"', payload)
        self.assertIn('"cookie_secure": true', payload)
        self.assertIn('"allow_header_token": false', payload)

    async def test_runtime_status_reports_runtime_fields(self):
        app = web.Application()
        app[RUNTIME_KEY] = SimpleNamespace(
            access_service=SimpleNamespace(is_allow_all_users_enabled=lambda: True),
            user_manager=SimpleNamespace(get_all=lambda: {1, 2}),
            url_cache={"u": "v"},
            parser=object(),
            storage=object(),
        )
        app[STARTED_AT_KEY] = 100.0
        app[AUTH_BACKEND_KEY] = MemoryAuthBackend()
        request = SimpleNamespace(app=app)

        response = await _runtime_status(request)
        payload = response.text

        self.assertIn('"run_mode": "unified_async"', payload)
        self.assertIn('"authorized_users": 2', payload)
        self.assertIn('"auth_backend": "memory"', payload)

    async def test_recent_users_passes_scope_and_limit(self):
        calls = []

        def recent_users_summary(*, include_owner, limit):
            calls.append((include_owner, limit))
            return {"rows": []}

        app = web.Application()
        app[RUNTIME_KEY] = SimpleNamespace(
            admin_service=SimpleNamespace(get_recent_users_summary=recent_users_summary)
        )
        request = SimpleNamespace(app=app, query={"scope": "all", "limit": "7"})

        response = await _recent_users(request)

        self.assertIn('"rows": []', response.text)
        self.assertEqual(calls, [(True, 7)])

    async def test_available_subscriptions_passes_page_and_limit(self):
        calls = []

        def available_subscriptions(*, page, limit):
            calls.append((page, limit))
            return {"rows": []}

        app = web.Application()
        app[RUNTIME_KEY] = SimpleNamespace(
            admin_service=SimpleNamespace(get_available_subscriptions_data=available_subscriptions)
        )
        request = SimpleNamespace(app=app, query={"page": "3", "limit": "11"})

        response = await _subscriptions_available(request)

        self.assertIn('"rows": []', response.text)
        self.assertEqual(calls, [(3, 11)])

    async def test_user_detail_returns_profile_subscriptions_and_audit_rows(self):
        async def query_records(**kwargs):
            return {
                "mode": kwargs["mode"],
                "total": 1,
                "total_pages": 1,
                "records": [
                    {
                        "user_id": 42,
                        "ts": "2026-05-20 12:00:00",
                        "source": "web",
                        "urls": ["https://example.test/sub"],
                    }
                ],
            }

        async def query_by_source_prefix(**kwargs):
            return [
                {
                    "user_id": 42,
                    "ts": "2026-05-20 13:00:00",
                    "source": "导出缓存:clash",
                    "urls": ["https://example.test/export"],
                }
            ]

        app = web.Application()
        app[RUNTIME_KEY] = SimpleNamespace(
            admin_service=SimpleNamespace(owner_id=1),
            access_service=SimpleNamespace(
                is_owner_uid=lambda uid: False,
                is_authorized_uid=lambda uid: True,
            ),
            user_profile_service=SimpleNamespace(
                get_profile=lambda uid: {"username": "alice", "full_name": "Alice"},
                format_user_identity=lambda uid: f"alice ({uid})",
            ),
            usage_audit_service=SimpleNamespace(
                aquery_records=query_records,
                aquery_by_source_prefix=query_by_source_prefix,
            ),
            get_storage=lambda: SimpleNamespace(
                get_by_user=lambda uid: {
                    "https://example.test/sub": {
                        "name": "main",
                        "updated_at": "2026-05-20",
                        "expire_time": "2099-01-01",
                    }
                }
            ),
        )
        request = SimpleNamespace(app=app, query={"uid": "42"})

        response = await _user_detail(request)
        payload = json.loads(response.text)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["uid"], 42)
        self.assertEqual(payload["data"]["username"], "alice")
        self.assertEqual(payload["data"]["subscription_count"], 1)
        self.assertEqual(payload["data"]["recent_checks"][0]["url_count"], 1)
        self.assertEqual(payload["data"]["recent_exports"][0]["fmt"], "CLASH")

    async def test_owner_check_all_returns_success_and_failure_counts(self):
        class Store:
            def __init__(self):
                self.failed_urls = []
                self.batch_started = False
                self.batch_ended = False

            def get_all(self):
                return {
                    "https://ok.example/sub": {"owner_uid": 1},
                    "https://bad.example/sub": {"owner_uid": 2},
                }

            def begin_batch(self):
                self.batch_started = True

            def end_batch(self, save):
                self.batch_ended = bool(save)

            def mark_check_failed(self, url, message):
                self.failed_urls.append((url, message))

        class Checker:
            async def parse_and_store(self, *, url, owner_uid):
                if "bad" in url:
                    raise RuntimeError(f"failed {owner_uid}")

        store = Store()
        app = web.Application()
        app[RUNTIME_KEY] = SimpleNamespace(
            get_storage=lambda: store,
            subscription_check_service=Checker(),
        )
        request = SimpleNamespace(app=app)

        response = await _owner_check_all(request)
        payload = json.loads(response.text)

        self.assertEqual(payload["data"], {"total": 2, "success": 1, "failed": 1})
        self.assertTrue(store.batch_started)
        self.assertTrue(store.batch_ended)
        self.assertEqual(store.failed_urls[0][0], "https://bad.example/sub")

    async def test_owner_import_json_failure_returns_error_code_and_message(self):
        class DocumentService:
            async def import_json(self, *, content_bytes):
                raise RuntimeError(f"bad import: {len(content_bytes)}")

        app = web.Application()
        app[RUNTIME_KEY] = SimpleNamespace(document_service=DocumentService())
        request = _FakeUploadRequest(
            app=app,
            filename="subscriptions.json",
            content=b'{"subscriptions": {}}',
        )

        response = await _owner_import_json(request)
        payload = json.loads(response.text)

        self.assertEqual(response.status, 500)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "import_failed")
        self.assertIn("bad import", payload["error"]["message"])


class WebAdminAuthFlowTest(unittest.IsolatedAsyncioTestCase):
    async def test_login_success_sets_secure_session_cookie(self):
        app = _auth_test_app(cookie_secure=True)
        request = _FakeWebRequest(
            app=app,
            payload={"username": "admin", "password": "secret-token"},
            remote="203.0.113.10",
        )

        response = await _login(request)

        self.assertEqual(response.status, 200)
        self.assertIn(SESSION_COOKIE, response.cookies)
        cookie = response.cookies[SESSION_COOKIE]
        self.assertEqual(cookie["httponly"], True)
        self.assertEqual(cookie["secure"], True)
        self.assertTrue(await app[AUTH_BACKEND_KEY].is_session_valid(cookie.value))

    async def test_login_failure_does_not_issue_session(self):
        app = _auth_test_app()
        request = _FakeWebRequest(
            app=app,
            payload={"username": "admin", "password": "wrong"},
            remote="203.0.113.11",
        )

        response = await _login(request)

        self.assertEqual(response.status, 401)
        self.assertNotIn(SESSION_COOKIE, response.cookies)

    async def test_login_rate_limit_blocks_after_max_attempts(self):
        app = _auth_test_app(max_attempts=1)
        first = _FakeWebRequest(app=app, payload={"username": "admin", "password": "wrong"})
        second = _FakeWebRequest(app=app, payload={"username": "admin", "password": "secret-token"})

        first_response = await _login(first)
        second_response = await _login(second)

        self.assertEqual(first_response.status, 401)
        self.assertEqual(second_response.status, 429)

    async def test_header_token_is_rejected_when_disabled(self):
        app = _auth_test_app(allow_header_token=False)
        request = _FakeWebRequest(
            app=app, path="/api/v1/system/runtime", headers={"X-Admin-Token": "secret-token"}
        )

        response = await _auth_middleware(request, _ok_handler)

        self.assertEqual(response.status, 401)

    async def test_header_token_is_accepted_when_enabled(self):
        app = _auth_test_app(allow_header_token=True)
        request = _FakeWebRequest(
            app=app, path="/api/v1/system/runtime", headers={"X-Admin-Token": "secret-token"}
        )

        response = await _auth_middleware(request, _ok_handler)

        self.assertEqual(response.status, 200)
        self.assertEqual(response.text, "ok")


def _auth_test_app(*, allow_header_token=False, cookie_secure=False, max_attempts=3):
    app = web.Application()
    app[AUTH_BACKEND_KEY] = MemoryAuthBackend()
    app[ALLOW_HEADER_TOKEN_KEY] = allow_header_token
    app[COOKIE_SECURE_KEY] = cookie_secure
    app[LOGIN_WINDOW_KEY] = 60
    app[LOGIN_MAX_ATTEMPTS_KEY] = max_attempts
    app[SESSION_TTL_KEY] = 600
    app[TOKEN_KEY] = "secret-token"
    app[USERNAME_KEY] = "admin"
    app[TRUST_PROXY_KEY] = False
    return app


class _FakeWebRequest:
    def __init__(
        self,
        *,
        app,
        payload=None,
        path="/admin/login",
        method="POST",
        headers=None,
        cookies=None,
        remote="127.0.0.1",
    ):
        self.app = app
        self._payload = payload or {}
        self.path = path
        self.method = method
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.remote = remote

    async def json(self):
        return self._payload

    async def post(self):
        return self._payload


class _FakeUpload:
    def __init__(self, *, filename, content):
        self.filename = filename
        self.file = _FakeUploadFile(content)


class _FakeUploadFile:
    def __init__(self, content):
        self._content = content

    def read(self):
        return self._content


class _FakeUploadRequest:
    def __init__(self, *, app, filename, content):
        self.app = app
        self._upload = _FakeUpload(filename=filename, content=content)

    async def post(self):
        return {"file": self._upload}


async def _ok_handler(_request):
    return web.Response(text="ok")


class _FailingRedisBackend:
    async def validate_connection(self):
        raise ConnectionError("redis down")


if __name__ == "__main__":
    unittest.main()
