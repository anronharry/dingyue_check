from __future__ import annotations
# -*- coding: utf-8 -*-
import asyncio
import aiohttp
from typing import List, Dict, Any

class BaseTestEngine:
    """
    代理节点测速引擎基类。
    实现此基类以支持不同的底层测速引擎（例如 Mihomo、v2ray-core、xray-core 等）。
    """
    
    @property
    def engine_name(self) -> str:
        return "BaseEngine"

    def prepare(self) -> bool:
        """
        测速前的准备工作。
        如：检查环境、下载最新二进制包、清理残留进程等。
        返回 True 表示准备成功，False 失败。
        """
        raise NotImplementedError

    def start(self, nodes: List[Dict[str, Any]], port: int) -> bool:
        """
        启动测速内核。
        :param nodes: 待测速的节点列表
        :param port: 本地 API 监听端口或其它形式的控制端口
        :return: 启动是否成功
        """
        raise NotImplementedError

    def stop(self) -> None:
        """
        停止测速内核并清理相关资源。
        """
        raise NotImplementedError

    async def async_test_node(self, node_name: str, timeout_ms: int, test_url: str, session: aiohttp.ClientSession, sem: asyncio.Semaphore) -> Dict[str, Any]:
        """
        并发进行单节点连通性测试。
        :return: 约定格式的字典 {"name": 节点名, "status": "valid"|"error", "delay": 延迟(整数)或没有, "error": 报错简述}
        """
        raise NotImplementedError

