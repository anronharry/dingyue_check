from __future__ import annotations

import unittest
from types import SimpleNamespace

from services.document_service import DocumentService


class DocumentServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_analyze_node_text_attaches_quick_check_summary(self):
        async def analyze_nodes(nodes):
            return {
                "countries": {"香港": len(nodes)},
                "protocols": {"vmess": len(nodes)},
            }

        async def get_parser():
            return SimpleNamespace(_analyze_nodes=analyze_nodes)

        async def quick_ping_runner(nodes, concurrency=20, timeout=1.5):
            self.assertEqual(concurrency, 20)
            self.assertEqual(timeout, 1.5)
            return 1, len(nodes), nodes[:1]

        service = DocumentService(
            get_parser=get_parser,
            get_storage=lambda: None,
            logger=SimpleNamespace(warning=lambda *args, **kwargs: None),
            export_cache_service=None,
            quick_ping_runner=quick_ping_runner,
        )

        text = (
            "vmess://eyJhZGQiOiIxLjEuMS4xIiwicG9ydCI6IjQ0MyIsImlkIjoiMTExMTExMTEtMTExMS0xMTExLTExMTEtMTExMTExMTExMTExIiwicHMiOiJISzAxIn0=\n"
            "trojan://password@2.2.2.2:443#JP01"
        )
        result = await service.analyze_node_text(text=text)

        self.assertIsNotNone(result)
        self.assertEqual(result["node_count"], 2)
        self.assertEqual(len(result["_normalized_nodes"]), 2)
        self.assertEqual(result["_content_format"], "text")
        self.assertEqual(result["quick_check"]["tested"], 2)
        self.assertEqual(result["quick_check"]["alive"], 1)
        self.assertEqual(result["quick_check"]["dead"], 1)
        self.assertEqual(result["quick_check"]["skipped"], 0)

    async def test_analyze_document_nodes_marks_skipped_when_nodes_not_testable(self):
        async def analyze_nodes(nodes):
            return {
                "countries": {"未知": len(nodes)},
                "protocols": {"ss": len(nodes)},
            }

        async def get_parser():
            return SimpleNamespace(_analyze_nodes=analyze_nodes)

        async def quick_ping_runner(nodes, concurrency=20, timeout=1.5):
            return 0, len(nodes), []

        service = DocumentService(
            get_parser=get_parser,
            get_storage=lambda: None,
            logger=SimpleNamespace(warning=lambda *args, **kwargs: None),
            export_cache_service=None,
            quick_ping_runner=quick_ping_runner,
        )

        content = b"ss://YWVzLTI1Ni1nY206cGFzc0BleGFtcGxlLmNvbTo0NDM=#HK01"
        result = await service.analyze_document_nodes(
            file_name="nodes.txt",
            file_type="txt",
            content_bytes=content,
        )

        self.assertIsNotNone(result)
        self.assertIn("quick_check", result)
        self.assertIn("tested", result["quick_check"])

    async def test_analyze_document_nodes_saves_owner_scoped_cache_from_normalized_result(self):
        saved = []

        async def analyze_nodes(nodes):
            return {
                "countries": {"香港": len(nodes)},
                "protocols": {"vmess": len(nodes)},
            }

        async def get_parser():
            return SimpleNamespace(_analyze_nodes=analyze_nodes)

        cache_service = SimpleNamespace(
            save_subscription_cache=lambda **kwargs: saved.append(kwargs),
        )
        service = DocumentService(
            get_parser=get_parser,
            get_storage=lambda: None,
            logger=SimpleNamespace(warning=lambda *args, **kwargs: None),
            export_cache_service=cache_service,
            quick_ping_runner=None,
        )

        content = b"vmess://eyJhZGQiOiIxLjEuMS4xIiwicG9ydCI6IjQ0MyIsImlkIjoiMTExMTExMTEtMTExMS0xMTExLTExMTEtMTExMTExMTExMTExIiwicHMiOiJISzAxIn0="
        result = await service.analyze_document_nodes(
            file_name="nodes.txt",
            file_type="txt",
            content_bytes=content,
            owner_uid=42,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["_content_format"], "txt")
        self.assertEqual(len(result["_normalized_nodes"]), 1)
        self.assertEqual(result["_normalized_nodes"][0]["server"], "1.1.1.1")
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["owner_uid"], 42)
        self.assertEqual(saved[0]["source"], "document:nodes.txt")
        self.assertIs(saved[0]["result"], result)

    async def test_hysteria_family_and_tuic_nodes_become_testable(self):
        async def analyze_nodes(nodes):
            return {
                "countries": {"未知": len(nodes)},
                "protocols": {node["protocol"]: 1 for node in nodes},
            }

        async def get_parser():
            return SimpleNamespace(_analyze_nodes=analyze_nodes)

        async def quick_ping_runner(nodes, concurrency=20, timeout=1.5):
            self.assertEqual(len(nodes), 3)
            return 2, len(nodes), nodes[:2]

        service = DocumentService(
            get_parser=get_parser,
            get_storage=lambda: None,
            logger=SimpleNamespace(warning=lambda *args, **kwargs: None),
            export_cache_service=None,
            quick_ping_runner=quick_ping_runner,
        )

        text = "\n".join(
            [
                "hysteria://example.com:443?peer=demo#HY1",
                "hysteria2://password@example.org:8443#HY2",
                "tuic://uuid:password@tuic.example.net:443#TUIC1",
            ]
        )
        result = await service.analyze_node_text(text=text)

        self.assertIsNotNone(result)
        self.assertEqual(result["quick_check"]["tested"], 3)
        self.assertEqual(result["quick_check"]["skipped"], 0)
        self.assertEqual(result["_normalized_nodes"][0]["server"], "example.com")
        self.assertEqual(result["_normalized_nodes"][1]["port"], 8443)
        self.assertEqual(result["_normalized_nodes"][2]["server"], "tuic.example.net")


if __name__ == "__main__":
    unittest.main()
