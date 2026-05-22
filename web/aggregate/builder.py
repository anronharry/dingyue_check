"""Owner aggregate subscription bundle builder."""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

import yaml  # type: ignore[import-untyped]

from web.aggregate.lifecycle import _aggregate_node_health_state
from web.aggregate.rendering import (
    _build_pool_snapshot,
    _build_proxy_groups,
    _format_timing_ms,
    _render_base64,
    _render_clash_yaml,
    _render_raw_lines,
)
from web.aggregate.state import OwnerAggregateState

CollectNodes = Callable[..., Awaitable[tuple[list[dict[str, Any]], dict[str, Any]]]]


async def _build_owner_aggregate_bundle(
    runtime: Any,
    *,
    state: OwnerAggregateState | None = None,
    collect_nodes: CollectNodes,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    active_state = state or _aggregate_node_health_state()
    collected_nodes, stats = await collect_nodes(runtime, state=active_state)
    render_started = time.perf_counter()
    if not collected_nodes:
        return await _empty_bundle(
            active_state, stats, started_at=started_at, render_started=render_started
        )
    yaml_content, count = _render_clash_yaml(collected_nodes)
    raw_content, _raw_count = _render_raw_lines(collected_nodes)
    base64_content, _base64_count = _render_base64(collected_nodes)
    await _attach_render_stats(
        active_state, stats, started_at=started_at, render_started=render_started
    )
    return {
        "yaml": yaml_content,
        "raw": raw_content,
        "base64": base64_content,
        "node_count": count,
        "stats": stats,
    }


async def _empty_bundle(
    state: OwnerAggregateState,
    stats: dict[str, Any],
    *,
    started_at: float,
    render_started: float,
) -> dict[str, Any]:
    yaml_content = yaml.safe_dump(
        {"proxies": [], "proxy-groups": _build_proxy_groups([]), "rules": ["MATCH,DIRECT"]},
        allow_unicode=True,
        sort_keys=False,
    )
    await _attach_render_stats(state, stats, started_at=started_at, render_started=render_started)
    return {"yaml": yaml_content, "raw": "", "base64": "", "node_count": 0, "stats": stats}


async def _attach_render_stats(
    state: OwnerAggregateState,
    stats: dict[str, Any],
    *,
    started_at: float,
    render_started: float,
) -> None:
    stats["timings_ms"] = dict(stats.get("timings_ms", {}) or {})
    stats["timings_ms"]["render"] = _format_timing_ms(render_started)
    stats["timings_ms"]["build_total"] = _format_timing_ms(started_at)
    meta = await state.read_meta()
    stats["pool_snapshot"] = _build_pool_snapshot(
        stats,
        await state.read_node_health(),
        stats.get("top_sources", []),
        dict(meta.get("pool_snapshot", {}) or {}),
    )
