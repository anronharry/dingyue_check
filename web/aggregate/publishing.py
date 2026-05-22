"""Publish-pool selection helpers for owner aggregate nodes."""

from __future__ import annotations

from typing import Any

from web.aggregate.node_cleaning import (
    _aggregate_node_cache_key,
    _aggregate_server_bucket,
    _aggregate_source_bucket,
    _dedupe_aggregate_nodes,
    _is_aggregate_health_evicted,
    _rank_health_row,
)
from web.constants import (
    AGG_NODE_PUBLISH_LIMIT,
    AGG_NODE_VERIFY_LIMIT,
    AGG_POOL_STABLE_RATIO,
    AGG_POOL_WARM_RATIO,
    AGG_PUBLISH_SERVER_LIMIT,
    AGG_PUBLISH_SOURCE_LIMIT,
    AGG_STABLE_REVERIFY_LIMIT,
)


def _record_health_update(
    updates: dict[str, Any],
    stats: dict[str, Any],
    key: str,
    next_row: dict[str, Any],
    previous: dict[str, Any] | None,
) -> None:
    updates[key] = next_row
    was_stable = bool((previous or {}).get("stable"))
    is_stable = bool(next_row.get("stable"))
    if is_stable and not was_stable:
        stats["promoted_stable_nodes"] = int(stats.get("promoted_stable_nodes", 0) or 0) + 1
    was_evicted = _is_aggregate_health_evicted(previous or {})
    is_evicted = _is_aggregate_health_evicted(next_row)
    if is_evicted and not was_evicted:
        stats["evicted_nodes"] = int(stats.get("evicted_nodes", 0) or 0) + 1


def _sort_nodes_by_health(
    nodes: list[dict[str, Any]], cache_rows: dict[str, Any]
) -> list[dict[str, Any]]:
    return sorted(nodes, key=lambda node: _rank_health_row(node, cache_rows))


def _select_verify_input(
    stable_verified_alive: list[dict[str, Any]],
    quick_pool: list[dict[str, Any]],
    cache_rows: dict[str, Any],
) -> list[dict[str, Any]]:
    if len(stable_verified_alive) >= AGG_NODE_PUBLISH_LIMIT:
        return []
    stable_keys = {_aggregate_node_cache_key(item) for item in stable_verified_alive}
    stable_recheck = sorted(
        stable_verified_alive,
        key=lambda node: int(
            (cache_rows.get(_aggregate_node_cache_key(node)) or {}).get("checked_at", 0) or 0
        ),
    )[:AGG_STABLE_REVERIFY_LIMIT]
    fresh_candidates = [
        node for node in quick_pool if _aggregate_node_cache_key(node) not in stable_keys
    ]
    merged = _dedupe_aggregate_nodes(stable_recheck + fresh_candidates)
    return merged[: max(0, AGG_NODE_VERIFY_LIMIT)]


def _bucket_publish_targets() -> tuple[int, int, int]:
    stable_target = max(0, int(AGG_NODE_PUBLISH_LIMIT * AGG_POOL_STABLE_RATIO / 100))
    warm_target = max(0, int(AGG_NODE_PUBLISH_LIMIT * AGG_POOL_WARM_RATIO / 100))
    fresh_target = max(0, AGG_NODE_PUBLISH_LIMIT - stable_target - warm_target)
    return stable_target, warm_target, fresh_target


def _append_diverse_nodes(
    selected: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    *,
    limit: int,
    per_source: dict[str, int],
    per_server: dict[str, int],
) -> None:
    if limit <= 0:
        return
    for node in nodes:
        if len(selected) >= limit:
            return
        source = _aggregate_source_bucket(node)
        server = _aggregate_server_bucket(node)
        if per_source.get(source, 0) >= AGG_PUBLISH_SOURCE_LIMIT:
            continue
        if per_server.get(server, 0) >= AGG_PUBLISH_SERVER_LIMIT:
            continue
        if node in selected:
            continue
        per_source[source] = per_source.get(source, 0) + 1
        per_server[server] = per_server.get(server, 0) + 1
        selected.append(node)


def _build_layered_published_pool(
    stable_nodes: list[dict[str, Any]],
    warm_nodes: list[dict[str, Any]],
    fresh_nodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    stable_target, warm_target, fresh_target = _bucket_publish_targets()
    selected: list[dict[str, Any]] = []
    per_source: dict[str, int] = {}
    per_server: dict[str, int] = {}
    _append_diverse_nodes(
        selected, stable_nodes, limit=stable_target, per_source=per_source, per_server=per_server
    )
    _append_diverse_nodes(
        selected,
        warm_nodes,
        limit=stable_target + warm_target,
        per_source=per_source,
        per_server=per_server,
    )
    _append_diverse_nodes(
        selected,
        fresh_nodes,
        limit=stable_target + warm_target + fresh_target,
        per_source=per_source,
        per_server=per_server,
    )
    if len(selected) < AGG_NODE_PUBLISH_LIMIT:
        remainder = [
            node for node in stable_nodes + warm_nodes + fresh_nodes if node not in selected
        ]
        _append_diverse_nodes(
            selected,
            remainder,
            limit=AGG_NODE_PUBLISH_LIMIT,
            per_source=per_source,
            per_server=per_server,
        )
    return selected[:AGG_NODE_PUBLISH_LIMIT]
