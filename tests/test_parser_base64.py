from __future__ import annotations

import base64
import unittest

from core.parser import SubscriptionParser


class ParserBase64Test(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = SubscriptionParser()

    def test_parse_nodes_keeps_direct_vmess_without_base64_decode(self) -> None:
        content = "vmess://eyJwcyI6IkhLMDEifQ==\ntrojan://pass@example.com:443#JP"

        nodes, content_format, _, normalized_content, notes = self.parser._parse_nodes(content)

        self.assertEqual(content_format, "text")
        self.assertEqual(len(nodes), 2)
        self.assertIn("direct-protocol", notes)
        self.assertNotIn("base64-decoded", notes)
        self.assertIn("vmess://", normalized_content)

    def test_parse_nodes_keeps_direct_trojan_without_base64_decode(self) -> None:
        content = "trojan://password@example.org:443#jp01"

        nodes, content_format, _, normalized_content, notes = self.parser._parse_nodes(content)

        self.assertEqual(content_format, "text")
        self.assertEqual(len(nodes), 1)
        self.assertIn("direct-protocol", notes)
        self.assertNotIn("base64-decoded", notes)
        self.assertIn("trojan://", normalized_content)

    def test_parse_nodes_supports_base64_encoded_raw_nodes(self) -> None:
        raw_text = (
            "ss://YWVzLTI1Ni1nY206cGFzc0BleGFtcGxlLmNvbTo0NDM=#HK01\n"
            "trojan://password@example.org:443#JP01"
        )
        encoded = base64.b64encode(raw_text.encode("utf-8")).decode("ascii")

        nodes, content_format, _, normalized_content, notes = self.parser._parse_nodes(encoded)

        self.assertEqual(content_format, "text")
        self.assertEqual(len(nodes), 2)
        self.assertIn("base64-decoded", notes)
        self.assertIn("trojan://", normalized_content)

    def test_parse_nodes_returns_empty_for_blank_input(self) -> None:
        nodes, content_format, _, normalized_content, notes = self.parser._parse_nodes("\n\r\t  ")

        self.assertEqual(content_format, "text")
        self.assertEqual(nodes, [])
        self.assertEqual(normalized_content, "")
        self.assertIn("unrecognized-content", notes)

    def test_parse_nodes_rejects_non_base64_plain_text(self) -> None:
        content = "hello world this is not a subscription payload"

        nodes, content_format, _, normalized_content, notes = self.parser._parse_nodes(content)

        self.assertEqual(content_format, "text")
        self.assertEqual(nodes, [])
        self.assertEqual(normalized_content, content)
        self.assertNotIn("base64-decoded", notes)
        self.assertIn("unrecognized-content", notes)

    def test_parse_nodes_supports_urlsafe_missing_padding_and_noise(self) -> None:
        raw_text = "vmess://eyJwcyI6IkhLMDEifQ==\nss://YWVzLTI1Ni1nY206cGFzc0BleGFtcGxlLmNvbTo0NDM=#HK"
        encoded = base64.urlsafe_b64encode(raw_text.encode("utf-8")).decode("ascii").rstrip("=")
        noisy = "\ufeff  " + encoded[:12] + "\n" + encoded[12:] + "$$$\x00"

        nodes, content_format, _, normalized_content, notes = self.parser._parse_nodes(noisy)

        self.assertEqual(content_format, "text")
        self.assertEqual(len(nodes), 2)
        self.assertIn("base64-decoded", notes)
        self.assertIn("vmess://", normalized_content)


if __name__ == "__main__":
    unittest.main()
