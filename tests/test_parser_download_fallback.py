from __future__ import annotations

import unittest

from core.parser import SubscriptionParser


class _FakeResponse:
    def __init__(self, *, status: int, body: str, headers: dict[str, str] | None = None, charset: str | None = "utf-8"):
        self.status = status
        self._body = body.encode("utf-8")
        self.headers = headers or {}
        self.charset = charset

    async def read(self) -> bytes:
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)
        self.user_agents: list[str] = []

    def get(self, url, **kwargs):
        _ = url
        headers = kwargs.get("headers") or {}
        self.user_agents.append(str(headers.get("User-Agent", "")))
        if not self._responses:
            raise AssertionError("No fake responses left")
        return self._responses.pop(0)


class ParserDownloadFallbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_download_retries_with_browser_ua_after_waf_block(self):
        session = _FakeSession(
            [
                _FakeResponse(status=403, body="safeline waf blocked", headers={"content-type": "text/html"}),
                _FakeResponse(status=200, body="trojan://password@example.org:443#JP01"),
                _FakeResponse(
                    status=200,
                    body="trojan://password@example.org:443#JP01",
                    headers={"subscription-userinfo": "upload=1; download=2; total=10; expire=2000000000"},
                ),
            ]
        )
        parser = SubscriptionParser(session=session)

        text, headers = await parser._download_subscription("https://139.196.241.76:18181/api/v1/client/subscribe?token=abc")
        ua_candidates = list(SubscriptionParser._resolve_subscription_user_agents())

        self.assertIn("trojan://", text)
        self.assertIn("subscription-userinfo", headers)
        self.assertEqual(
            session.user_agents,
            ua_candidates[:3],
        )

    async def test_download_uses_single_request_when_first_response_is_valid(self):
        session = _FakeSession(
            [
                _FakeResponse(status=200, body="trojan://password@example.org:443#JP01"),
            ]
        )
        parser = SubscriptionParser(session=session)

        text, _ = await parser._download_subscription("https://example.com/sub")
        ua_clash = SubscriptionParser._resolve_subscription_user_agents()[0]

        self.assertIn("trojan://", text)
        self.assertEqual(session.user_agents, [ua_clash])


if __name__ == "__main__":
    unittest.main()
