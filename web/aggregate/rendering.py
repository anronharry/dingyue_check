"""Rendering and snapshot helpers for owner aggregate subscriptions."""

from __future__ import annotations

import base64
import time
from typing import Any

import yaml  # type: ignore[import-untyped]

from core.converters.ss_converter import SSNodeConverter
from web.aggregate.node_cleaning import (
    _clamp_health_score,
    _is_aggregate_health_evicted,
    _is_aggregate_health_stable,
    _node_quality_key,
    _normalize_aggregate_proxy,
)

DIRECT_GROUP = "🎯 全球直连"
SELECT_GROUP = "🚀 节点选择"
AUTO_GROUP = "♻ 自动选择"
DEFAULT_MIXED_PORT = 7890
AUTO_TEST_INTERVAL_SECONDS = 300
AUTO_TEST_TOLERANCE_MS = 50
TOP_SOURCE_LIMIT = 10


def _build_proxy_groups(proxy_names: list[str]) -> list[dict[str, Any]]:
    selector_list = [AUTO_GROUP, DIRECT_GROUP, *proxy_names]
    return [
        {"name": SELECT_GROUP, "type": "select", "proxies": selector_list},
        {
            "name": AUTO_GROUP,
            "type": "url-test",
            "url": "http://www.gstatic.com/generate_204",
            "interval": AUTO_TEST_INTERVAL_SECONDS,
            "tolerance": AUTO_TEST_TOLERANCE_MS,
            "proxies": proxy_names or [DIRECT_GROUP],
        },
        {"name": DIRECT_GROUP, "type": "select", "proxies": ["DIRECT"]},
    ]


def _init_source_stat(row: dict[str, Any] | None = None) -> dict[str, Any]:
    base = dict(row or {})
    defaults = {
        "subscriptions": 0,
        "eligible_subscriptions": 0,
        "parsed_ok": 0,
        "parsed_failed": 0,
        "timed_out": 0,
        "parsed_nodes": 0,
        "candidate_nodes": 0,
        "quick_alive": 0,
        "verified_alive": 0,
        "stable_nodes": 0,
        "published_nodes": 0,
        "reputation_score": 0,
    }
    for key, value in defaults.items():
        base[key] = int(base.get(key, value) or value)
    return base


def _apply_source_counts(
    source_stats: dict[str, dict[str, Any]], field: str, counts: dict[str, int]
) -> None:
    for source, value in counts.items():
        row = _init_source_stat(source_stats.get(source))
        row[field] = row.get(field, 0) + int(value or 0)
        source_stats[source] = row


def _finalize_source_snapshot(source_stats: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source, raw in source_stats.items():
        row = _init_source_stat(raw)
        score = (
            row["parsed_ok"] * 8
            + row["parsed_nodes"]
            + row["quick_alive"] * 3
            + row["verified_alive"] * 6
            + row["stable_nodes"] * 8
            + row["published_nodes"] * 5
            - row["parsed_failed"] * 6
            - row["timed_out"] * 4
        )
        row["source"] = source
        row["reputation_score"] = _clamp_health_score(score)
        rows.append(row)
    rows.sort(
        key=lambda item: (
            -int(item.get("reputation_score", 0) or 0),
            -int(item.get("published_nodes", 0) or 0),
            item["source"],
        )
    )
    return rows[:TOP_SOURCE_LIMIT]


def _render_clash_yaml(nodes: list[dict[str, Any]]) -> tuple[str, int]:
    proxies = _unique_proxies(nodes)
    proxy_names = [proxy["name"] for proxy in proxies]
    config = {
        "mixed-port": DEFAULT_MIXED_PORT,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "info",
        "profile": {"store-selected": True, "store-fake-ip": True},
        "proxies": proxies,
        "proxy-groups": _build_proxy_groups(proxy_names),
        "rules": [
            f"DOMAIN-SUFFIX,google.com,{SELECT_GROUP}",
            f"DOMAIN-KEYWORD,telegram,{SELECT_GROUP}",
            "GEOIP,CN,DIRECT",
            f"MATCH,{SELECT_GROUP}",
        ],
    }
    return yaml.safe_dump(config, allow_unicode=True, sort_keys=False), len(proxies)


def _unique_proxies(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    proxies: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int, str]] = set()
    for row in nodes:
        proxy = _normalize_aggregate_proxy(row)
        if proxy is None:
            continue
        key = (
            str(proxy["type"]),
            str(proxy["server"]),
            int(proxy["port"]),
            str(proxy.get("uuid") or proxy.get("password") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        proxies.append(proxy)
    proxies.sort(key=_node_quality_key)
    return proxies


def _render_raw_lines(nodes: list[dict[str, Any]]) -> tuple[str, int]:
    converter = SSNodeConverter()
    lines: list[str] = []
    seen: set[str] = set()
    for node in nodes:
        raw = _node_raw_url(converter, node)
        if not raw or raw in seen:
            continue
        seen.add(raw)
        lines.append(raw)
    return "\n".join(lines), len(lines)


def _node_raw_url(converter: SSNodeConverter, node: dict[str, Any]) -> str:
    raw = str(node.get("raw", "") or "").strip()
    if raw:
        return raw
    try:
        return str(converter.build_url(node) or "").strip()
    except Exception:
        return ""


def _render_base64(nodes: list[dict[str, Any]]) -> tuple[str, int]:
    raw_text, count = _render_raw_lines(nodes)
    payload = base64.b64encode(raw_text.encode("utf-8")).decode("ascii") if raw_text else ""
    return payload, count


def _build_pool_snapshot(
    stats: dict[str, Any],
    cache_rows: dict[str, Any],
    source_rows: list[dict[str, Any]],
    previous_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cache_stats = _cache_stats(cache_rows)
    snapshot = {
        **cache_stats,
        "cache_hits": int(stats.get("cache_hits", 0) or 0),
        "tested_nodes": int(stats.get("tested_nodes", 0) or 0),
        "verify_attempted": int(stats.get("verify_attempted", 0) or 0),
        "verify_alive": int(stats.get("verify_alive", 0) or 0),
        "stable_pool_nodes": int(stats.get("stable_pool_nodes", 0) or 0),
        "published_nodes": int(stats.get("published_nodes", 0) or 0),
        "promoted_stable_nodes": int(stats.get("promoted_stable_nodes", 0) or 0),
        "evicted_nodes": int(stats.get("evicted_nodes", 0) or 0),
        "verify_mode": str(stats.get("verify_mode", "disabled") or "disabled"),
        "timings_ms": dict(stats.get("timings_ms", {}) or {}),
        "layer_counts": dict(stats.get("layer_counts", {}) or {}),
        "top_sources": source_rows,
    }
    snapshot["delta"] = _build_snapshot_delta(snapshot, dict(previous_snapshot or {}))
    return snapshot


def _cache_stats(cache_rows: dict[str, Any]) -> dict[str, Any]:
    total_cached = alive_cached = stable_cached = evicted_cached = health_total = 0
    for row in cache_rows.values():
        if not isinstance(row, dict):
            continue
        total_cached += 1
        health_total += int(row.get("health_score", 0) or 0)
        alive_cached += int(row.get("status") == "alive")
        stable_cached += int(_is_aggregate_health_stable(row))
        evicted_cached += int(_is_aggregate_health_evicted(row))
    return {
        "cached_nodes": total_cached,
        "cached_alive_nodes": alive_cached,
        "stable_cached_nodes": stable_cached,
        "evicted_cached_nodes": evicted_cached,
        "average_health_score": round(health_total / total_cached, 1) if total_cached else 0.0,
    }


def _build_snapshot_delta(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, int]:
    keys = ("published_nodes", "stable_pool_nodes", "cached_nodes", "verify_alive", "evicted_nodes")
    return {key: int(current.get(key, 0) or 0) - int(previous.get(key, 0) or 0) for key in keys}


def _format_timing_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))
