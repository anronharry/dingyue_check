"""
IP 地理位置查询服务。

使用 ip-api.com 免费接口查询 IP 归属地，并带本地缓存。
"""
from __future__ import annotations


import atexit
import json
import logging
import os
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class GeoLocationService:
    """IP 地理位置查询服务，带本地缓存和连接池。"""

    _instance = None
    _cache_file = os.path.join("data", "geo_cache.json")

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GeoLocationService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized") and self._initialized:
            return

        self.api_url = "http://ip-api.com/json/{}"
        self.session = None

        os.makedirs(os.path.dirname(self._cache_file), exist_ok=True)

        self.cache: Dict[str, Dict] = {}
        self._cache_dirty = False
        self._cache_new_entries = 0
        self._last_cache_save = time.monotonic()
        self._load_cache()

        atexit.register(lambda: self._maybe_persist_cache(force=True))
        self._initialized = True

    def _load_cache(self):
        """从本地文件加载缓存。"""
        if os.path.exists(self._cache_file):
            try:
                with open(self._cache_file, "r", encoding="utf-8") as f:
                    self.cache = json.load(f)
                    logger.info(f"成功加载 {len(self.cache)} 条 IP 缓存。")
            except Exception as e:
                logger.error(f"加载 IP 缓存失败: {e}")
                self.cache = {}

    def _save_cache(self):
        """保存缓存到本地文件。"""
        try:
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
                logger.debug(f"已保存 IP 缓存（{len(self.cache)} 条）。")
        except Exception as e:
            logger.error(f"保存 IP 缓存失败: {e}")

    def _maybe_persist_cache(self, force: bool = False):
        """按批次或时间保存缓存，避免每次查询都写盘。"""
        if not self._cache_dirty:
            return

        should_save = force or self._cache_new_entries >= 20 or (time.monotonic() - self._last_cache_save) >= 30
        if not should_save:
            return

        self._save_cache()
        self._cache_dirty = False
        self._cache_new_entries = 0
        self._last_cache_save = time.monotonic()

    async def get_location(self, ip: str) -> Optional[Dict]:
        """
        异步查询 IP 地理位置。

        返回值格式:
        {'country', 'city', 'isp', 'country_code'}
        """
        if not ip or ip == "unknown":
            return None

        if ip in self.cache:
            return self.cache[ip]

        if self.session is None:
            import aiohttp

            connector = aiohttp.TCPConnector(limit=5)
            self.session = aiohttp.ClientSession(connector=connector)

        try:
            from utils.retry_utils import async_retry_on_failure

            @async_retry_on_failure(max_retries=2, initial_delay=0.5)
            async def _fetch():
                async with self.session.get(self.api_url.format(ip), timeout=5) as resp:
                    resp.raise_for_status()
                    return await resp.json()

            data = await _fetch()

            if data.get("status") == "success":
                location = {
                    "country": data.get("country", "未知"),
                    "city": data.get("city", "未知"),
                    "isp": data.get("isp", "未知"),
                    "country_code": data.get("countryCode", ""),
                }
                self.cache[ip] = location
                self._cache_dirty = True
                self._cache_new_entries += 1
                self._maybe_persist_cache()
                return location

            logger.warning(f"IP 查询失败: {ip} - {data.get('message')}")
            return None
        except Exception as e:
            logger.error(f"查询 IP 地理位置失败 {ip}: {e}")
            return None

    async def close(self):
        """关闭地理位置查询服务的连接池。"""
        if self.session is not None:
            await self.session.close()
            self.session = None

    def get_country_flag(self, country_code: str) -> str:
        """根据国家代码返回旗帜 emoji。"""
        if not country_code or len(country_code) != 2:
            return "🌐"

        code_points = [ord(c) + 127397 for c in country_code.upper()]
        return "".join(chr(c) for c in code_points)
