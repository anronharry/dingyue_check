#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
订阅获取与解析管理器模块
从 node_tester.py 中抽离的 fetch_nodes_from_subscriptions 逻辑。
"""
from __future__ import annotations

import os
import re
import yaml
import urllib3
import aiohttp
import asyncio
from typing import Tuple, List
from colorama import Fore, Style, init

from app import config as _cfg
from core.subscription_checker import try_decode_b64, PROXY_SCHEMES, is_pseudo_200_response
from core.converters.ss_converter import SSNodeConverter
from core.models import ProxyNode, SubFetchResult

init(autoreset=True)
if not _cfg.VERIFY_SSL:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# #6 修复：导入 node_tester 中共享的 print_lock，不再单独定义
from core.node_tester import print_lock


async def async_fetch_nodes_from_subscriptions(target_file: str, client_session: aiohttp.ClientSession = None, status_callback=None) -> Tuple[List[ProxyNode], List[str], List[str]]:
    """
    从文件中的 HTTP/HTTPS 订阅 URL 批量下载并提取节点（单次请求版）

    Returns:
        (all_nodes, invalid_urls, valid_urls)
    """
    HEADERS_CLASH   = {"User-Agent": _cfg.get("UA_CLASH")}
    HEADERS_BROWSER = {"User-Agent": _cfg.get("UA_BROWSER")}

    try:
        with open(target_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except OSError as e:
        print(f"{Fore.RED}❌ 读取文件失败: {e}{Style.RESET_ALL}")
        return [], [], []

    links = list(set(re.findall(r"https?://[^\s<>\"]+", content)))
    if not links:
        print(f"{Fore.RED}❌ 文件中未找到任何 HTTP/HTTPS 订阅链接。{Style.RESET_ALL}")
        return [], [], []

    print(f"\n{Fore.CYAN}🔍 找到 {len(links)} 个订阅链接，正在并发检测并提取节点...{Style.RESET_ALL}")

    own_session = False

    if client_session is None:
        conn = aiohttp.TCPConnector(ssl=_cfg.VERIFY_SSL, limit=_cfg.get("SUB_DOWNLOAD_WORKERS", 30))
        timeout = aiohttp.ClientTimeout(total=_cfg.get("SUB_TIMEOUT", 12))
        client_session = aiohttp.ClientSession(connector=conn, timeout=timeout)
        own_session = True

    async def fetch_and_classify(url: str, sem: asyncio.Semaphore) -> SubFetchResult:
        async with sem:
            try:
                # 初始请求
                async with client_session.get(url, headers=HEADERS_CLASH) as resp:
                    resp_status = resp.status
                    text = await resp.text()
                    headers = resp.headers

                # 若遭拦截，则换浏览器 UA 降级重试 (简易重试)
                if resp_status == 403 or "safeline" in text.lower() or "waf" in text.lower():
                    async with client_session.get(url, headers=HEADERS_BROWSER) as resp2:
                        resp_status = resp2.status
                        text = await resp2.text()
                        headers = resp2.headers

                if resp_status != 200:
                    return {"status": "error", "url": url, "nodes": []}

                userinfo_raw = headers.get("Subscription-Userinfo")
                traffic_info = ""
                if userinfo_raw:
                    info = {}
                    for pair in userinfo_raw.split(";"):
                        if "=" in pair:
                            k, v = pair.strip().split("=", 1)
                            try:
                                info[k] = int(v)
                            except ValueError:
                                info[k] = 0
                    total     = info.get("total", 0)
                    remaining = total - info.get("upload", 0) - info.get("download", 0)
                    if total > 0 and remaining <= 0:
                        return {"status": "expired", "url": url, "nodes": []}
                    elif remaining > 0:
                        def _fmt(s):
                            for u, d in [("TB", 1 << 40), ("GB", 1 << 30), ("MB", 1 << 20)]:
                                if s >= d:
                                    return f"{s/d:.1f}{u}"
                            return f"{s}B"
                        traffic_info = f" 剩余{_fmt(remaining)}"
                    expire = info.get("expire", 0)
                    if expire:
                        from datetime import datetime as _dt
                        try:
                            expire_str = _dt.fromtimestamp(int(expire)).strftime('%Y-%m-%d')
                            traffic_info += f" 到期:{expire_str}"
                        except (ValueError, OSError):
                            pass

                if is_pseudo_200_response(text, headers):
                    return {"status": "invalid", "url": url, "nodes": []}

                source = try_decode_b64(text)
                lines_     = [l.strip() for l in source.splitlines() if l.strip()]
                node_lines = [l for l in lines_ if any(l.startswith(s) for s in PROXY_SCHEMES)]

                if node_lines:
                    return {"status": "valid", "url": url, "nodes": [("raw", l) for l in node_lines]}

                try:
                    data = yaml.safe_load(source)
                    if isinstance(data, dict) and "proxies" in data:
                        clash_nodes = data.get("proxies") or []
                        if len(clash_nodes) > 0:
                            return {"status": "valid", "url": url, "nodes": [("clash", n) for n in clash_nodes]}
                except yaml.YAMLError:
                    pass

                return {"status": "invalid", "url": url, "nodes": []}

            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError):
                return {"status": "error", "url": url, "nodes": []}

    all_raw_nodes: list = []
    invalid_urls:  list = []
    valid_urls:    list = []

    max_concurrent = _cfg.get("SUB_DOWNLOAD_WORKERS", 8)
    sem = asyncio.Semaphore(max_concurrent)

    # #15 修复：抽取公共收集协程，消除 own_session 两分支的重复代码
    async def _collect_results():
        total = len(links)
        processed = 0
        tasks = [asyncio.create_task(fetch_and_classify(url, sem)) for url in links]
        
        for future in asyncio.as_completed(tasks):
            result = await future
            processed += 1
            if result["status"] == "valid":
                all_raw_nodes.extend(result["nodes"])
                valid_urls.append(result["url"])
            else:
                invalid_urls.append(result["url"])
            
            if status_callback and (processed % 5 == 0 or processed == total):
                await status_callback(f"📡 正在拉取订阅: {processed}/{total}...")

    if own_session:
        async with client_session:
            await _collect_results()
    else:
        await _collect_results()

    valid_count = len(links) - len(invalid_urls)
    print(f"\n预检结果: {Fore.GREEN}✅ 有效 {valid_count} 个{Style.RESET_ALL} | "
          f"{Fore.RED}❌ 失效/无效 {len(invalid_urls)} 个{Style.RESET_ALL}")

    if not all_raw_nodes:
        print(f"{Fore.RED}❌ 所有订阅均未返回有效节点。{Style.RESET_ALL}")
        return [], invalid_urls, []

    print(f"\n{Fore.CYAN}🔧 正在解析节点...{Style.RESET_ALL}")
    converter = SSNodeConverter()
    all_nodes = []
    for item in all_raw_nodes:
        kind, data = item
        if kind == "clash":
            all_nodes.append(data)
        else:
            node = None
            if data.startswith("ss://"):
                node = converter.parse_ss_url(data)
            elif data.startswith("vmess://"):
                node = converter.parse_vmess_url(data)
            elif data.startswith("trojan://"):
                node = converter.parse_trojan_url(data)
            elif data.startswith("vless://"):
                node = converter.parse_vless_url(data)
            if node:
                all_nodes.append(node)

    # #5 修复：调用 node_tester._dedup_and_rename 复用去重逻辑，不再各自实现
    from core.node_tester import _dedup_and_rename
    all_nodes = _dedup_and_rename(all_nodes)
    print(f"{Fore.GREEN}✅ 共解析到 {len(all_nodes)} 个节点（来自 {len(valid_urls)} 个有效订阅）{Style.RESET_ALL}")

    return all_nodes, invalid_urls, valid_urls


def fetch_nodes_from_subscriptions(target_file: str, http_session=None) -> Tuple[List[ProxyNode], List[str], List[str]]:
    """
    为了向下兼容其他同步使用 `fetch_nodes_from_subscriptions` 的模块（如 `huyun_converter.py`），这里封装一个同步入口。
    将来如果整个项目彻底异步化，则可移除。
    """
    return asyncio.run(async_fetch_nodes_from_subscriptions(target_file))




