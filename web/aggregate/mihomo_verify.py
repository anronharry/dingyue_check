"""Mihomo-backed verification for owner aggregate nodes."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from web.constants import AGG_NODE_VERIFY_ENABLED, AGG_NODE_VERIFY_LIMIT, AGG_NODE_VERIFY_TIMEOUT_MS


async def _verify_aggregate_nodes_with_mihomo(
    nodes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stats = {"verify_attempted": 0, "verify_alive": 0, "verify_mode": "disabled"}
    if not AGG_NODE_VERIFY_ENABLED or not nodes:
        return [], stats
    stats["verify_mode"] = "preparing"
    try:
        from core.plugins.mihomo_engine import MihomoEngine
    except Exception:
        stats["verify_mode"] = "unavailable"
        return [], stats
    engine = MihomoEngine()
    if not await engine.prepare():
        stats["verify_mode"] = "prepare_failed"
        return [], stats
    return await _run_mihomo_verification(engine, nodes, stats)


async def _run_mihomo_verification(
    engine: Any, nodes: list[dict[str, Any]], stats: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from app import config as _cfg

    stats["verify_mode"] = "running"
    verify_nodes = list(nodes[:AGG_NODE_VERIFY_LIMIT])
    stats["verify_attempted"] = len(verify_nodes)
    results: list[dict[str, Any]] = []
    try:
        timeout = aiohttp.ClientTimeout(total=max(20, AGG_NODE_VERIFY_TIMEOUT_MS / 1000 + 8))
        connector = aiohttp.TCPConnector(ssl=_cfg.VERIFY_SSL, limit=max(1, _cfg.NODE_TEST_WORKERS))
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            if not await engine.start(verify_nodes, _cfg.API_PORT, session):
                stats["verify_mode"] = "start_failed"
                return [], stats
            sem = asyncio.Semaphore(max(1, _cfg.NODE_TEST_WORKERS))
            tasks = [
                asyncio.create_task(
                    engine.async_test_node(
                        node["name"], AGG_NODE_VERIFY_TIMEOUT_MS, _cfg.TEST_URL, session, sem
                    )
                )
                for node in verify_nodes
            ]
            for future in asyncio.as_completed(tasks):
                results.append(await future)
    finally:
        engine.stop()
    verified = _verified_nodes(verify_nodes, results)
    stats["verify_alive"] = len(verified)
    stats["verify_mode"] = "ok"
    return verified, stats


def _verified_nodes(
    verify_nodes: list[dict[str, Any]], results: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    alive_names = {
        str(row.get("name", "") or "")
        for row in results
        if row.get("status") == "valid" and float(row.get("delay", -1) or -1) > 0
    }
    verified: list[dict[str, Any]] = []
    for node in verify_nodes:
        if node.get("name") not in alive_names:
            continue
        matched = next((row for row in results if row.get("name") == node.get("name")), None)
        next_node = dict(node)
        if matched:
            next_node["latency"] = float(matched.get("delay", 0.0) or 0.0)
        verified.append(next_node)
    return verified
