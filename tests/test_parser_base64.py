from __future__ import annotations

import base64
import unittest

from core.parser import SubscriptionParser


class ParserBase64Test(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = SubscriptionParser()

    def test_parse_nodes_supports_base64_encoded_raw_nodes(self) -> None:
        raw_text = (
            "ss://YWVzLTI1Ni1nY206cGFzc0BleGFtcGxlLmNvbTo0NDM=#香港01\n"
            "trojan://password@example.org:443#日本01"
        )
        encoded = base64.b64encode(raw_text.encode("utf-8")).decode("ascii")

        nodes, content_format, _, normalized_content = self.parser._parse_nodes(encoded)

        self.assertEqual(content_format, "text")
        self.assertEqual(len(nodes), 2)
        self.assertEqual(nodes[0]["protocol"], "ss")
        self.assertEqual(nodes[0]["server"], "example.com")
        self.assertEqual(nodes[0]["port"], 443)
        self.assertEqual(nodes[1]["server"], "example.org")
        self.assertEqual(nodes[1]["port"], 443)
        self.assertIn("trojan://", normalized_content)

    def test_parse_nodes_supports_base64_encoded_yaml(self) -> None:
        yaml_text = (
            "proxies:\n"
            "  - name: 香港01\n"
            "    type: ss\n"
            "    server: hk.example.com\n"
            "    port: 443\n"
            "  - name: 日本01\n"
            "    type: trojan\n"
            "    server: jp.example.com\n"
            "    port: 443\n"
        )
        encoded = base64.b64encode(yaml_text.encode("utf-8")).decode("ascii")

        nodes, content_format, _, normalized_content = self.parser._parse_nodes(encoded)

        self.assertEqual(content_format, "yaml")
        self.assertEqual(len(nodes), 2)
        self.assertEqual(nodes[0]["name"], "香港01")
        self.assertEqual(nodes[1]["protocol"], "trojan")
        self.assertIn("proxies:", normalized_content)


if __name__ == "__main__":
    unittest.main()
