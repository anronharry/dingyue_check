from __future__ import annotations

import asyncio
import time
import logging
from typing import List, Tuple, Dict
import urllib.parse

from typing import List, Tuple, Dict, Any

logger = logging.getLogger(__name__)

async def _ping_tcp(host: str, port: int, timeout: float = 3.0) -> float:
    """真实 TCP 连接测速"""
    start = time.time()
    try:
        # 尝试建立 TCP 连接
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), 
            timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return (time.time() - start) * 1000 # 毫秒
    except Exception:
        return -1

async def test_node(node: Dict[str, Any], timeout: float = 3.0) -> Tuple[Dict[str, Any], float]:
    """测速单个节点"""
    address = node.get('server') or node.get('address')
    port = node.get('port')
    if not address or not port:
        return node, -1
        
    latency = await _ping_tcp(address, int(port), timeout)
    return node, latency

async def ping_all_nodes(nodes: List[Dict[str, Any]], concurrency: int = 50, timeout: float = 3.0) -> Tuple[int, int, List[Dict]]:
    """
    并发测速所有节点
    Args:
        nodes: 节点字典列表
        concurrency: 最大并发连接数
        timeout: 每个连接的超时时间
    Returns:
        (存活数量, 总数量, 存活节点详情列表带延迟)
    """
    if not nodes:
        return 0, 0, []
        
    semaphore = asyncio.Semaphore(concurrency)
    
    async def _worker(node):
        async with semaphore:
            return await test_node(node, timeout)
            
    tasks = [_worker(node) for node in nodes]
    results = await asyncio.gather(*tasks)
    
    alive_nodes = []
    for node, latency in results:
        if latency > 0:
            alive_nodes.append({
                'name': node.get('name', 'Unknown'),
                'address': node.get('server') or node.get('address', 'Unknown'),
                'port': node.get('port', 0),
                'type': node.get('type') or node.get('protocol', 'Unknown'),
                'latency': round(latency, 2),
                'raw_node': node
            })
            
    # 按延迟排序
    alive_nodes.sort(key=lambda x: x['latency'])
    return len(alive_nodes), len(nodes), alive_nodes
