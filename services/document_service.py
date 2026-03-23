"""Document parsing and import workflows."""
from __future__ import annotations


import asyncio
import os
from datetime import datetime

from core.file_handler import FileHandler


class DocumentService:
    def __init__(self, *, get_parser, get_storage, logger):
        self.get_parser = get_parser
        self.get_storage = get_storage
        self.logger = logger

    async def import_json(self, *, content_bytes: bytes) -> int:
        loop = asyncio.get_event_loop()
        os.makedirs("data", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        import_file = os.path.join("data", f"import_{timestamp}.json")

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
        store = self.get_storage()
        store.begin_batch()
        semaphore = asyncio.Semaphore(20)

        async def parse_one(index: int, url: str) -> dict:
            async with semaphore:
                try:
                    parser_instance = await self.get_parser()
                    result = await parser_instance.parse(url)
                    store.add_or_update(url, result, user_id=owner_uid)
                    return {"index": index, "url": url, "data": result, "status": "success"}
                except Exception as exc:
                    self.logger.error("订阅解析失败 %s: %s", url, exc)
                    return {"index": index, "url": url, "error": str(exc), "status": "failed"}

        try:
            tasks = [parse_one(index, url) for index, url in enumerate(subscription_urls, 1)]
            return await asyncio.gather(*tasks)
        finally:
            store.end_batch(save=True)

    async def analyze_document_nodes(self, *, file_name: str, file_type: str, content_bytes: bytes) -> dict | None:
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
        return {
            "name": f"{file_name} (节点列表)",
            "node_count": len(nodes),
            "node_stats": node_stats,
        }

    async def analyze_node_text(self, *, text: str) -> dict | None:
        nodes = FileHandler.parse_txt_file(text.encode("utf-8"))
        if not nodes:
            return None

        parser_instance = await self.get_parser()
        node_stats = await parser_instance._analyze_nodes(nodes)
        return {
            "name": "节点列表",
            "node_count": len(nodes),
            "node_stats": node_stats,
        }

    @staticmethod
    def extract_subscription_urls(*, content_bytes: bytes) -> list[str]:
        return FileHandler.extract_subscription_urls(content_bytes)
