from __future__ import annotations

import unittest

from core.parsing.traffic import parse_traffic_info


class ParsingTrafficTest(unittest.TestCase):
    def test_missing_header_returns_empty_payload(self) -> None:
        self.assertEqual(parse_traffic_info({}), {})

    def test_missing_header_preserves_explicit_warning(self) -> None:
        result = parse_traffic_info({"x-traffic-warning": "missing subscription-userinfo"})
        self.assertEqual(result, {"_traffic_warning": "missing subscription-userinfo"})

    def test_full_userinfo_fields_are_parsed(self) -> None:
        result = parse_traffic_info(
            {"subscription-userinfo": "upload=10; download=20; total=100; expire=2000000000"}
        )
        self.assertEqual(result["upload"], 10)
        self.assertEqual(result["download"], 20)
        self.assertEqual(result["total"], 100)
        self.assertEqual(result["used"], 30)
        self.assertEqual(result["remaining"], 70)
        self.assertEqual(result["usage_percent"], 30)
        self.assertEqual(result["expire_time"], "2033-05-18 11:33:20")

    def test_partial_userinfo_keeps_available_fields(self) -> None:
        result = parse_traffic_info({"subscription-userinfo": "download=20; total=100"})
        self.assertEqual(result, {"download": 20, "total": 100})

    def test_malformed_counter_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            parse_traffic_info({"subscription-userinfo": "upload=bad"})


if __name__ == "__main__":
    unittest.main()
