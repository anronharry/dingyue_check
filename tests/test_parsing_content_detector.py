from __future__ import annotations

import base64
import unittest

from core.parsing.content_detector import (
    detect_subscription_content,
    is_pseudo_200_response,
    normalize_subscription_text,
    sanitize_base64_candidate,
    try_decode_subscription_base64,
)


def _yaml_detector(content: str) -> bool:
    return "proxies:" in content and "name:" in content


class ParsingContentDetectorTest(unittest.TestCase):
    def test_detects_direct_protocol(self) -> None:
        self.assertEqual(
            detect_subscription_content("trojan://p@example.com:443#JP", _yaml_detector),
            "direct-protocol",
        )

    def test_detects_yaml_payload(self) -> None:
        content = "proxies:\n  - name: HK\n    type: trojan\n"
        self.assertEqual(detect_subscription_content(content, _yaml_detector), "yaml")

    def test_decodes_base64_payload(self) -> None:
        raw = "vmess://eyJwcyI6IkhLMDEifQ=="
        encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
        self.assertEqual(detect_subscription_content(encoded, _yaml_detector), "base64")
        self.assertEqual(try_decode_subscription_base64(encoded, yaml_detector=_yaml_detector), raw)

    def test_rejects_noisy_base64_candidate(self) -> None:
        self.assertEqual(sanitize_base64_candidate("not base64 !!! ###"), "")

    def test_normalizes_bom_and_nul_bytes(self) -> None:
        self.assertEqual(normalize_subscription_text("\ufeff\x00  ss://abc  \x00"), "ss://abc")

    def test_detects_pseudo_200_html_error(self) -> None:
        html = "<html><body>forbidden by firewall</body></html>"
        self.assertTrue(is_pseudo_200_response(html, {"content-type": "text/html"}))


if __name__ == "__main__":
    unittest.main()
