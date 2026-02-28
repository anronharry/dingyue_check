"""
IP地理位置查询服务
使用 ip-api.com 免费API查询IP地理位置
"""

import requests
import logging
import json
import os
import atexit
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class GeoLocationService:
    """IP地理位置查询服务 (带本地缓存和连接池)"""

    _instance = None
    _cache_file = os.path.join("data", "geo_cache.json")

    def __new__(cls):
        # 单例模式，保证全局共用一个缓存和Session池
        if cls._instance is None:
            cls._instance = super(GeoLocationService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return

        self.api_url = "http://ip-api.com/json/{}"
        self.session = requests.Session()

        # 限制连接池，避免小内存 VPS 过度占用资源
        from requests.adapters import HTTPAdapter
        adapter = HTTPAdapter(pool_connections=5, pool_maxsize=5, max_retries=1)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

        os.makedirs(os.path.dirname(self._cache_file), exist_ok=True)

        self.cache: Dict[str, Dict] = {}
        self._cache_dirty = False
        self._cache_new_entries = 0
        self._last_cache_save = time.monotonic()
        self._load_cache()

        # 进程退出时强制落盘
        atexit.register(lambda: self._maybe_persist_cache(force=True))

        self._initialized = True

    def _load_cache(self):
        """从本地文件加载缓存"""
        if os.path.exists(self._cache_file):
            try:
                with open(self._cache_file, 'r', encoding='utf-8') as f:
                    self.cache = json.load(f)
                    logger.info(f"成功加载 {len(self.cache)} 条 IP 缓存")
            except Exception as e:
                logger.error(f"加载 IP 缓存失败: {e}")
                self.cache = {}

    def _save_cache(self):
        """保存缓存到本地文件"""
        try:
            with open(self._cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
                logger.debug(f"已保存 IP 缓存 ({len(self.cache)} 条)")
        except Exception as e:
            logger.error(f"保存 IP 缓存失败: {e}")

    def _maybe_persist_cache(self, force: bool = False):
        """按批次/时间保存缓存，避免每次查询都写盘。"""
        if not self._cache_dirty:
            return

        should_save = (
            force
            or self._cache_new_entries >= 20
            or (time.monotonic() - self._last_cache_save) >= 30
        )
        if not should_save:
            return

        self._save_cache()
        self._cache_dirty = False
        self._cache_new_entries = 0
        self._last_cache_save = time.monotonic()

    def get_location(self, ip: str) -> Optional[Dict]:
        """
        查询IP地理位置

        Args:
            ip: IP地址

        Returns:
            dict: 地理位置信息 {'country', 'city', 'isp', 'country_code'}
        """
        if not ip or ip == 'unknown':
            return None

        if ip in self.cache:
            return self.cache[ip]

        try:
            response = self.session.get(
                self.api_url.format(ip),
                timeout=5
            )
            data = response.json()

            if data.get('status') == 'success':
                location = {
                    'country': data.get('country', '未知'),
                    'city': data.get('city', '未知'),
                    'isp': data.get('isp', '未知'),
                    'country_code': data.get('countryCode', '')
                }
                self.cache[ip] = location
                self._cache_dirty = True
                self._cache_new_entries += 1
                self._maybe_persist_cache()
                return location

            logger.warning(f"IP查询失败: {ip} - {data.get('message')}")
            return None

        except Exception as e:
            logger.error(f"查询IP地理位置失败 {ip}: {e}")
            return None

    def get_country_flag(self, country_code: str) -> str:
        """
        根据国家代码返回国旗emoji

        Args:
            country_code: 国家代码(如 HK, US)

        Returns:
            str: 国旗emoji
        """
        if not country_code or len(country_code) != 2:
            return '🌐'

        code_points = [ord(c) + 127397 for c in country_code.upper()]
        return ''.join(chr(c) for c in code_points)
