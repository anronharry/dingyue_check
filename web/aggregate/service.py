"""Default owner aggregate service wiring."""

from __future__ import annotations

from typing import Any

from web.aggregate import health_pipeline as _health_pipeline
from web.aggregate.builder import _build_owner_aggregate_bundle as _build_bundle
from web.aggregate.collector import (
    _collect_owner_aggregate_nodes as _collect_nodes,
    _collect_owner_eligible_links as _collect_links,
    _collect_owner_eligible_nodes as _collect_eligible_nodes,
    _compute_owner_fingerprint,
    _extract_protocol_links_from_text,
    _is_subscription_eligible,
)
from web.aggregate.mihomo_verify import _verify_aggregate_nodes_with_mihomo as _default_verify_nodes
from web.aggregate.state import OwnerAggregateState


async def _verify_aggregate_nodes_with_mihomo(
    nodes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return await _default_verify_nodes(nodes)


async def _quick_filter_aggregate_nodes(
    runtime: Any,
    nodes: list[dict[str, Any]],
    *,
    state: OwnerAggregateState | None = None,
    source_seed: dict[str, int] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    original = _health_pipeline._verify_aggregate_nodes_with_mihomo
    _health_pipeline._verify_aggregate_nodes_with_mihomo = _verify_aggregate_nodes_with_mihomo
    try:
        return await _health_pipeline._quick_filter_aggregate_nodes(
            runtime, nodes, state=state, source_seed=source_seed
        )
    finally:
        _health_pipeline._verify_aggregate_nodes_with_mihomo = original


async def _collect_owner_aggregate_nodes(
    runtime: Any,
    *,
    state: OwnerAggregateState | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return await _collect_nodes(runtime, state=state, quick_filter=_quick_filter_aggregate_nodes)


async def _build_owner_aggregate_bundle(
    runtime: Any,
    *,
    state: OwnerAggregateState | None = None,
) -> dict[str, Any]:
    return await _build_bundle(runtime, state=state, collect_nodes=_collect_owner_aggregate_nodes)


async def _collect_owner_eligible_nodes(
    runtime: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return await _collect_eligible_nodes(runtime, quick_filter=_quick_filter_aggregate_nodes)


async def _collect_owner_eligible_links(runtime: Any) -> tuple[list[str], dict[str, Any]]:
    return await _collect_links(runtime, quick_filter=_quick_filter_aggregate_nodes)


__all__ = [
    "_build_owner_aggregate_bundle",
    "_collect_owner_aggregate_nodes",
    "_collect_owner_eligible_links",
    "_collect_owner_eligible_nodes",
    "_compute_owner_fingerprint",
    "_extract_protocol_links_from_text",
    "_is_subscription_eligible",
    "_quick_filter_aggregate_nodes",
    "_verify_aggregate_nodes_with_mihomo",
]
