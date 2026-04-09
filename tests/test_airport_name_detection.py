from __future__ import annotations

import unittest

from core.parser import SubscriptionParser


class AirportNameDetectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = SubscriptionParser()

    def test_profile_title_base64_decoded(self) -> None:
        # "alberhong" in base64
        headers = {"profile-title": "YWxiZXJob25n"}
        name = self.parser._extract_airport_name([], "https://example.com/sub", headers=headers, content=None)
        self.assertEqual(name, "alberhong")

    def test_profile_title_base64_prefix_decoded(self) -> None:
        headers = {"profile-title": "base64:YWxiZXJob25n"}
        name = self.parser._extract_airport_name([], "https://example.com/sub", headers=headers, content=None)
        self.assertEqual(name, "alberhong")

    def test_known_alias_can_fallback_from_url(self) -> None:
        name = self.parser._extract_airport_name(
            [],
            "https://hha.albertabobbi.ndjp.net/sub?token=abc",
            headers={},
            content=None,
        )
        self.assertEqual(name, "alberhong")


if __name__ == "__main__":
    unittest.main()
