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

    def test_path_version_segment_is_not_used_as_name(self) -> None:
        name = self.parser._extract_airport_name(
            [],
            "https://103.118.41.216:15674/api/v1/client/subscribe?token=abc",
            headers={},
            content=None,
        )
        self.assertNotEqual(name.lower(), "v1")
        self.assertEqual(name, "103.118.41.216")

    def test_brand_can_be_inferred_from_node_names(self) -> None:
        nodes = [
            {"name": "TigerCloud-HK-01"},
            {"name": "TigerCloud-JP-02"},
            {"name": "TigerCloud-SG-03"},
            {"name": "TigerCloud-US-04"},
        ]
        name = self.parser._extract_airport_name(nodes, "https://example.com/sub", headers={}, content=None)
        self.assertEqual(name, "TigerCloud")

    def test_generic_ai_brand_from_nodes_is_ignored(self) -> None:
        nodes = [
            {"name": "ChatGPT-HK-01"},
            {"name": "ChatGPT-JP-02"},
            {"name": "ChatGPT-US-03"},
        ]
        name = self.parser._extract_airport_name(
            nodes,
            "https://139.196.241.76:18181/api/v1/client/subscribe?token=abc",
            headers={},
            content=None,
        )
        self.assertEqual(name, "139.196.241.76")

    def test_x_subscription_title_is_supported(self) -> None:
        headers = {"x-subscription-title": "TigerCloud"}
        name = self.parser._extract_airport_name([], "https://example.com/sub", headers=headers, content=None)
        self.assertEqual(name, "TigerCloud")

    def test_content_disposition_filename_star_is_supported(self) -> None:
        headers = {"content-disposition": "attachment; filename*=UTF-8''TigerCloud.yaml"}
        name = self.parser._extract_airport_name([], "https://example.com/sub", headers=headers, content=None)
        self.assertEqual(name, "TigerCloud")

    def test_yaml_top_level_name_has_high_priority(self) -> None:
        content = """
name: AuroraAir
proxies:
  - name: HK-01
    type: trojan
    server: example.com
    port: 443
"""
        name = self.parser._extract_airport_name([], "https://foo.example/sub", headers={}, content=content)
        self.assertEqual(name, "AuroraAir")

    def test_profile_title_comment_can_be_detected(self) -> None:
        content = """
# profile-title: NeonNet
vmess://example
"""
        name = self.parser._extract_airport_name([], "https://foo.example/sub", headers={}, content=content)
        self.assertEqual(name, "NeonNet")

    def test_url_query_name_is_supported(self) -> None:
        name = self.parser._extract_airport_name(
            [],
            "https://example.com/sub?token=abc&name=BlueWave",
            headers={},
            content=None,
        )
        self.assertEqual(name, "BlueWave")

    def test_multi_signal_candidate_wins_by_aggregated_score(self) -> None:
        name = self.parser._extract_airport_name(
            [{"name": "BlueWave-HK-01"}, {"name": "BlueWave-JP-02"}, {"name": "BlueWave-US-03"}],
            "https://service.example.com/sub?name=BlueWave",
            headers={"x-subscription-title": "AlphaOne"},
            content=None,
        )
        self.assertEqual(name, "BlueWave")


if __name__ == "__main__":
    unittest.main()
