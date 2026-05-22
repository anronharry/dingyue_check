from __future__ import annotations

import unittest
from unittest.mock import patch

from core.parsing.node_stats import analyze_nodes, match_country_by_keyword


class ParsingNodeStatsTest(unittest.IsolatedAsyncioTestCase):
    def test_match_country_by_keyword(self) -> None:
        self.assertEqual(match_country_by_keyword("HK premium 01"), "香港")
        self.assertEqual(match_country_by_keyword("Japan Tokyo"), "日本")
        self.assertEqual(match_country_by_keyword("unknown node"), "其他")

    async def test_analyze_nodes_without_geo_lookup(self) -> None:
        nodes = [
            {"name": "HK 01", "protocol": "trojan"},
            {"name": "JP 01", "protocol": "vmess"},
            {"name": "US 01", "protocol": "trojan"},
        ]
        with patch("app.config.ENABLE_GEO_LOOKUP", False):
            result = await analyze_nodes(nodes)
        self.assertEqual(result["protocols"], {"trojan": 2, "vmess": 1})
        self.assertEqual(result["countries"], {"香港": 1, "日本": 1, "美国": 1})
        self.assertEqual(result["locations"], [])


if __name__ == "__main__":
    unittest.main()
