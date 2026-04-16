"""Document parsing and import workflows."""
from __future__ import annotations

import asyncio
import os
from collections import Counter
from datetime import datetime

from core.file_handler import FileHandler


class DocumentService:
    def __init__(
        self,
        *,
        get_parser,
        get_storage,
        logger,
        export_cache_service=None,
        quick_ping_runner=None,
        subscription_check_service=None,
    ):
        self.get_parser = get_parser
        self.get_storage = get_storage
        self.logger = logger
        self.export_cache_service = export_cache_service
        self.quick_ping_runner = quick_ping_runner
        self.subscription_check_service = subscription_check_service

    async def import_json(self, *, content_bytes: bytes) -> int:
        loop = asyncio.get_event_loop()
        os.makedirs("data", exist_ok=True)
        import_file = os.path.join("data", f"import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        with open(import_file, "wb") as handle:
            handle.write(content_bytes)
        try:
            return await loop.run_in_executor(None, self.get_storage().import_from_file, import_file)
        finally:
            try:
                await loop.run_in_executor(None, os.remove, import_file)
            except OSError:
                self.logger.warning("删除导入临时文件失败: %s", import_file)

    async def parse_subscription_urls(self, *, subscription_urls: list[str], owner_uid: int) -> list[dict]:
        if not self.subscription_check_service:
            raise RuntimeError("subscription_check_service is required for parse_subscription_urls")
        return await self.subscription_check_service.parse_subscription_urls(
            subscription_urls=subscription_urls,
            owner_uid=owner_uid,
        )

    async def analyze_document_nodes(
        self,
        *,
        file_name: str,
        file_type: str,
        content_bytes: bytes,
        owner_uid: int = 0,
    ) -> dict | None:
        if file_type == "txt":
            nodes = FileHandler.parse_txt_file(content_bytes)
        elif file_type == "yaml":
            nodes = FileHandler.parse_yaml_file(content_bytes)
        else:
            return None
        if not nodes:
            return None

        parser_instance = await self.get_parser()
        node_stats = await parser_instance._analyze_nodes(nodes)
        raw_text = content_bytes.decode("utf-8", errors="ignore")
        result = {
            "name": f"{file_name} (节点列表)",
            "node_count": len(nodes),
            "node_stats": node_stats,
            "_raw_nodes": list(nodes),
            "_normalized_nodes": list(nodes),
            "_raw_content": raw_text,
            "_content_format": file_type,
        }
        await self._attach_quick_check_summary(result)

        if self.export_cache_service:
            source = f"document:{file_name}"
            self.export_cache_service.save_subscription_cache(
                owner_uid=owner_uid,
                source=source,
                result=result,
            )
        return result

    async def analyze_node_text(self, *, text: str) -> dict | None:
        nodes = FileHandler.parse_txt_file(text.encode("utf-8"))
        if not nodes:
            return None

        parser_instance = await self.get_parser()
        node_stats = await parser_instance._analyze_nodes(nodes)
        result = {
            "name": "节点列表",
            "node_count": len(nodes),
            "node_stats": node_stats,
            "_raw_nodes": list(nodes),
            "_normalized_nodes": list(nodes),
            "_raw_content": text,
            "_content_format": "text",
        }
        await self._attach_quick_check_summary(result)
        return result

    @staticmethod
    def extract_subscription_urls(*, content_bytes: bytes) -> list[str]:
        return FileHandler.extract_subscription_urls(content_bytes)

    async def _attach_quick_check_summary(self, result: dict) -> None:
        if not self.quick_ping_runner:
            return

        nodes = list(result.get("_normalized_nodes") or result.get("_raw_nodes") or [])
        if not nodes:
            return

        testable_nodes = [node for node in nodes if node.get("server") and node.get("port")]
        skipped_nodes = [node for node in nodes if node not in testable_nodes]
        skipped_count = len(skipped_nodes)
        skipped_protocols = Counter(
            str(node.get("protocol") or node.get("type") or "unknown").lower()
            for node in skipped_nodes
        )
        if not testable_nodes:
            if skipped_count:
                result["quick_check"] = {
                    "tested": 0,
                    "alive": 0,
                    "dead": 0,
                    "skipped": skipped_count,
                    "sampled": False,
                    "skipped_protocols": dict(skipped_protocols),
                }
            return

        sample_limit = 80
        sampled_nodes = testable_nodes[:sample_limit]
        sampled = len(testable_nodes) > sample_limit
        try:
            alive_count, tested_count, alive_nodes = await self.quick_ping_runner(
                sampled_nodes,
                concurrency=20,
                timeout=1.5,
            )
        except Exception as exc:
            self.logger.warning("节点快速连通性检测失败: %s", exc)
            return

        result["quick_check"] = {
            "tested": tested_count,
            "alive": alive_count,
            "dead": max(0, tested_count - alive_count),
            "skipped": skipped_count + max(0, len(testable_nodes) - tested_count),
            "sampled": sampled,
        }
        if alive_nodes:
            result["quick_check"]["latency_top"] = [
                {
                    "name": str(item.get("name", "Unknown")),
                    "latency": float(item.get("latency", 0.0)),
                    "type": str(item.get("type", "unknown")).lower(),
                }
                for item in alive_nodes[:5]
            ]
        if skipped_protocols:
            result["quick_check"]["skipped_protocols"] = dict(skipped_protocols)
