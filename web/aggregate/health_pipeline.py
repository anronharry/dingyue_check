"""Health filtering and publish-pool selection for owner aggregate nodes."""

from __future__ import annotations

import logging
import time
from typing import Any

from web.aggregate.lifecycle import _aggregate_node_health_state
from web.aggregate.mihomo_verify import _verify_aggregate_nodes_with_mihomo
from web.aggregate.node_cleaning import (
    _aggregate_node_cache_key,
    _count_nodes_by_source,
    _dedupe_aggregate_nodes,
    _is_aggregate_health_evicted,
    _is_aggregate_health_stable,
    _limit_published_aggregate_nodes,
    _load_cached_aggregate_health,
    _mark_aggregate_health,
    _merge_cached_aggregate_health,
    _select_aggregate_candidates,
)
from web.aggregate.publishing import (
    _build_layered_published_pool,
    _record_health_update,
    _select_verify_input,
    _sort_nodes_by_health,
)
from web.aggregate.rendering import (
    _apply_source_counts,
    _build_pool_snapshot,
    _finalize_source_snapshot,
    _format_timing_ms,
)
from web.aggregate.state import OwnerAggregateState
from web.constants import (
    AGG_NODE_TEST_CONCURRENCY,
    AGG_NODE_TEST_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


async def _quick_filter_aggregate_nodes(
    runtime: Any,
    nodes: list[dict[str, Any]],
    *,
    state: OwnerAggregateState | None = None,
    source_seed: dict[str, int] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stats = _initial_filter_stats(len(nodes))
    deduped = _dedupe_aggregate_nodes(nodes)
    stats["deduped_nodes"] = len(deduped)
    candidates = _select_aggregate_candidates(deduped, source_seed)
    stats["candidate_nodes"] = len(candidates)
    stats["sampled_nodes"] = len(candidates) < len(deduped)
    state = state or _aggregate_node_health_state()
    cache_rows = await state.read_node_health()
    buckets = _split_cached_candidates(candidates, cache_rows, int(time.time()), stats)
    runner = getattr(getattr(runtime, "document_service", None), "quick_ping_runner", None)
    if not callable(runner) or not candidates:
        return _cached_only_result(buckets, candidates, cache_rows, stats)
    return await _filter_with_connectivity(runner, state, cache_rows, buckets, candidates, stats)


def _initial_filter_stats(node_count: int) -> dict[str, Any]:
    return {
        "collected_nodes": node_count,
        "deduped_nodes": 0,
        "candidate_nodes": 0,
        "tested_nodes": 0,
        "alive_nodes": 0,
        "published_nodes": 0,
        "sampled_nodes": False,
        "connectivity_filter_enabled": False,
        "cache_hits": 0,
        "cache_quick_alive": 0,
        "cache_verify_alive": 0,
        "cache_stable_alive": 0,
        "verify_attempted": 0,
        "verify_alive": 0,
        "verify_mode": "disabled",
        "stable_pool_nodes": 0,
        "promoted_stable_nodes": 0,
        "evicted_nodes": 0,
        "timings_ms": {},
    }


def _split_cached_candidates(
    candidates: list[dict[str, Any]], cache_rows: dict[str, Any], now_ts: int, stats: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {
        "stable": [],
        "verified": [],
        "quick": [],
        "pending": [],
    }
    for row in candidates:
        cached = _load_cached_aggregate_health(cache_rows, row, now_ts=now_ts)
        if not cached:
            buckets["pending"].append(row)
            continue
        stats["cache_hits"] += 1
        if _append_cached_alive(row, cached, buckets, stats):
            continue
        if cached.get("status") == "dead" and _is_aggregate_health_evicted(cached):
            continue
        buckets["pending"].append(row)
    stats["stable_pool_nodes"] = len(buckets["stable"])
    return buckets


def _append_cached_alive(
    row: dict[str, Any],
    cached: dict[str, Any],
    buckets: dict[str, list[dict[str, Any]]],
    stats: dict[str, Any],
) -> bool:
    if cached.get("status") != "alive":
        return False
    item = dict(row)
    item["latency"] = float(cached.get("latency", 0.0) or 0.0)
    if cached.get("mode") == "verify":
        if _is_aggregate_health_stable(cached):
            buckets["stable"].append(item)
            stats["cache_stable_alive"] += 1
        else:
            buckets["verified"].append(item)
            stats["cache_verify_alive"] += 1
        return True
    if cached.get("mode") == "quick":
        buckets["quick"].append(item)
        stats["cache_quick_alive"] += 1
        return True
    return False


def _cached_only_result(
    buckets: dict[str, list[dict[str, Any]]],
    candidates: list[dict[str, Any]],
    cache_rows: dict[str, Any],
    stats: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    published = _limit_published_aggregate_nodes(
        buckets["stable"] + buckets["verified"] + buckets["quick"] + buckets["pending"]
    )
    stats["published_nodes"] = len(published)
    stats["layer_counts"] = {
        "stable": len(buckets["stable"]),
        "warm": len(buckets["verified"]),
        "fresh": len(buckets["quick"]) + len(buckets["pending"]),
    }
    source_stats: dict[str, dict[str, Any]] = {}
    _apply_source_counts(source_stats, "candidate_nodes", _count_nodes_by_source(candidates))
    _apply_source_counts(source_stats, "published_nodes", _count_nodes_by_source(published))
    stats["top_sources"] = _finalize_source_snapshot(source_stats)
    stats["pool_snapshot"] = _build_pool_snapshot(stats, cache_rows, stats["top_sources"])
    return published, stats


async def _filter_with_connectivity(
    runner: Any,
    state: OwnerAggregateState,
    cache_rows: dict[str, Any],
    buckets: dict[str, list[dict[str, Any]]],
    candidates: list[dict[str, Any]],
    stats: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stats["connectivity_filter_enabled"] = True
    updates: dict[str, Any] = {}
    newly_quick_alive = await _run_quick_ping(
        runner, buckets["pending"], cache_rows, updates, stats
    )
    quick_pool = _dedupe_aggregate_nodes(
        buckets["stable"] + buckets["verified"] + buckets["quick"] + newly_quick_alive
    )
    verify_input = _select_verify_input(buckets["stable"], quick_pool, cache_rows)
    verified_nodes, verify_stats = await _run_verify_stage(verify_input, cache_rows, updates, stats)
    if updates:
        cache_rows = _merge_cached_aggregate_health(cache_rows, updates, now_ts=int(time.time()))
        await state.write_node_health(cache_rows)
    stable_fallback = _stable_fallback(quick_pool, cache_rows)
    warm_nodes = _sort_nodes_by_health(
        _dedupe_aggregate_nodes(buckets["verified"] + verified_nodes), cache_rows
    )
    verified_keys = {_aggregate_node_cache_key(node): node for node in verified_nodes}
    fresh_nodes = _sort_nodes_by_health(
        _dedupe_aggregate_nodes(
            [node for node in quick_pool if _aggregate_node_cache_key(node) not in verified_keys]
        ),
        cache_rows,
    )
    published = _publish_from_layers(
        stable_fallback,
        warm_nodes,
        fresh_nodes,
        candidates,
        quick_pool,
        verified_nodes,
        stats,
        cache_rows,
    )
    stats.update(verify_stats)
    return published, stats


async def _run_quick_ping(
    runner: Any,
    pending_nodes: list[dict[str, Any]],
    cache_rows: dict[str, Any],
    updates: dict[str, Any],
    stats: dict[str, Any],
) -> list[dict[str, Any]]:
    if not pending_nodes:
        return []
    quick_started = time.perf_counter()
    alive_count, tested_count, alive_rows = await runner(
        pending_nodes, concurrency=AGG_NODE_TEST_CONCURRENCY, timeout=AGG_NODE_TEST_TIMEOUT_SECONDS
    )
    stats["timings_ms"]["quick_filter"] = _format_timing_ms(quick_started)
    stats["tested_nodes"] = int(tested_count or 0)
    stats["alive_nodes"] = int(alive_count or 0)
    alive_keys = {
        _aggregate_node_cache_key(dict(item.get("raw_node") or {})): float(
            item.get("latency", 0.0) or 0.0
        )
        for item in alive_rows
    }
    newly_alive: list[dict[str, Any]] = []
    for node in pending_nodes:
        key = _aggregate_node_cache_key(node)
        previous = cache_rows.get(key) if isinstance(cache_rows.get(key), dict) else None
        latency = alive_keys.get(key)
        if latency is None:
            _record_health_update(
                updates,
                stats,
                key,
                _mark_aggregate_health("quick", "dead", previous=previous),
                previous,
            )
            continue
        row = dict(node)
        row["latency"] = float(latency)
        newly_alive.append(row)
        _record_health_update(
            updates,
            stats,
            key,
            _mark_aggregate_health("quick", "alive", latency=latency, previous=previous),
            previous,
        )
    return newly_alive


async def _run_verify_stage(
    verify_input: list[dict[str, Any]],
    cache_rows: dict[str, Any],
    updates: dict[str, Any],
    stats: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    verify_started = time.perf_counter()
    verified_nodes, verify_stats = await _verify_aggregate_nodes_with_mihomo(verify_input)
    stats["timings_ms"]["verify_filter"] = _format_timing_ms(verify_started)
    stats.update(verify_stats)
    verified_keys = {_aggregate_node_cache_key(node): node for node in verified_nodes}
    for node in verify_input:
        key = _aggregate_node_cache_key(node)
        previous = cache_rows.get(key) if isinstance(cache_rows.get(key), dict) else None
        if key in verified_keys:
            latency = float(verified_keys[key].get("latency", 0.0) or 0.0)
            _record_health_update(
                updates,
                stats,
                key,
                _mark_aggregate_health("verify", "alive", latency=latency, previous=previous),
                previous,
            )
        elif verify_stats.get("verify_mode") == "ok":
            _record_health_update(
                updates,
                stats,
                key,
                _mark_aggregate_health("verify", "dead", previous=previous),
                previous,
            )
    return verified_nodes, verify_stats


def _stable_fallback(
    quick_pool: list[dict[str, Any]], cache_rows: dict[str, Any]
) -> list[dict[str, Any]]:
    stable_nodes = []
    for node in quick_pool:
        key = _aggregate_node_cache_key(node)
        row = cache_rows.get(key)
        if (
            isinstance(row, dict)
            and row.get("status") == "alive"
            and _is_aggregate_health_stable(row)
        ):
            item = dict(node)
            item["latency"] = float(row.get("latency", item.get("latency", 0.0)) or 0.0)
            stable_nodes.append(item)
    return _sort_nodes_by_health(_dedupe_aggregate_nodes(stable_nodes), cache_rows)


def _publish_from_layers(
    stable: list[dict[str, Any]],
    warm: list[dict[str, Any]],
    fresh: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    quick_pool: list[dict[str, Any]],
    verified: list[dict[str, Any]],
    stats: dict[str, Any],
    cache_rows: dict[str, Any],
) -> list[dict[str, Any]]:
    stats["stable_pool_nodes"] = len(stable)
    stats["layer_counts"] = {"stable": len(stable), "warm": len(warm), "fresh": len(fresh)}
    published = _build_layered_published_pool(stable, warm, fresh)
    stats["published_nodes"] = len(published)
    source_stats: dict[str, dict[str, Any]] = {}
    _apply_source_counts(source_stats, "candidate_nodes", _count_nodes_by_source(candidates))
    _apply_source_counts(source_stats, "quick_alive", _count_nodes_by_source(quick_pool))
    _apply_source_counts(source_stats, "verified_alive", _count_nodes_by_source(verified))
    _apply_source_counts(source_stats, "stable_nodes", _count_nodes_by_source(stable))
    _apply_source_counts(source_stats, "published_nodes", _count_nodes_by_source(published))
    stats["top_sources"] = _finalize_source_snapshot(source_stats)
    stats["pool_snapshot"] = _build_pool_snapshot(stats, cache_rows, stats["top_sources"])
    return published
