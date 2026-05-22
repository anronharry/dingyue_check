"""Owner aggregate subscription collection helpers."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Any, Awaitable, Callable

from web.aggregate.lifecycle import _aggregate_node_health_state
from web.aggregate.node_cleaning import (
    _apply_source_label_to_node,
    _build_source_seed_scores,
    _nodes_from_parse_result,
    _source_label_from_url,
    _source_sort_key,
)
from web.aggregate.rendering import (
    _build_pool_snapshot,
    _finalize_source_snapshot,
    _format_timing_ms,
    _init_source_stat,
    _render_raw_lines,
)
from web.aggregate.state import OwnerAggregateState
from web.constants import AGG_PARSE_CONCURRENCY, AGG_PARSE_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

QuickFilter = Callable[
    [Any, list[dict[str, Any]]],
    Awaitable[tuple[list[dict[str, Any]], dict[str, Any]]],
]


def _is_subscription_eligible(data: dict[str, Any], *, now: datetime) -> bool:
    if str(data.get("last_check_status", "")).lower() != "success":
        return False
    total = data.get("total")
    remaining = data.get("remaining")
    if (
        isinstance(total, (int, float))
        and total > 0
        and isinstance(remaining, (int, float))
        and remaining <= 0
    ):
        return False
    expire_text = str(data.get("expire_time", "") or "").strip()
    if not expire_text:
        return True
    try:
        expire_at = datetime.strptime(expire_text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return True
    return expire_at > now


async def _collect_owner_aggregate_nodes(
    runtime: Any,
    *,
    state: OwnerAggregateState | None = None,
    quick_filter: Callable[..., Awaitable[tuple[list[dict[str, Any]], dict[str, Any]]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started_at = time.perf_counter()
    subs = await _owner_subscriptions(runtime)
    if not subs:
        return [], _empty_collect_stats(0)
    eligible_subs = _eligible_subscriptions(subs)
    if not eligible_subs:
        return [], _empty_collect_stats(len(subs))
    active_state = state or _aggregate_node_health_state()
    previous_snapshot = await _previous_pool_snapshot(active_state)
    source_stats = _seed_source_stats(subs, eligible_subs)
    source_seed = _build_source_seed_scores(previous_snapshot)
    collected, parse_stats = await _parse_eligible_subscriptions(
        runtime, eligible_subs, source_stats
    )
    collected.sort(key=lambda node: _source_sort_key(node, source_seed))
    filtered, filter_stats = await quick_filter(
        runtime, collected, state=active_state, source_seed=source_seed
    )
    top_sources = _finalize_top_sources(source_stats, filter_stats)
    stats = _build_collect_stats(
        subs,
        eligible_subs,
        parse_stats=parse_stats,
        filter_stats=filter_stats,
        started_at=started_at,
        top_sources=top_sources,
    )
    stats["pool_snapshot"] = _build_pool_snapshot(
        stats, await active_state.read_node_health(), top_sources, previous_snapshot
    )
    return filtered, stats


async def _collect_owner_eligible_nodes(
    runtime: Any,
    *,
    quick_filter: Callable[..., Awaitable[tuple[list[dict[str, Any]], dict[str, Any]]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return await _collect_owner_aggregate_nodes(runtime, quick_filter=quick_filter)


async def _collect_owner_eligible_links(
    runtime: Any,
    *,
    quick_filter: Callable[..., Awaitable[tuple[list[dict[str, Any]], dict[str, Any]]]],
) -> tuple[list[str], dict[str, Any]]:
    nodes, stats = await _collect_owner_aggregate_nodes(runtime, quick_filter=quick_filter)
    raw_text, _count = _render_raw_lines(nodes)
    return [line.strip() for line in raw_text.splitlines() if line.strip()], stats


async def _compute_owner_fingerprint(runtime: Any) -> str:
    subs = await _owner_subscriptions(runtime)
    rows = [
        _fingerprint_row(url, data) for url, data in sorted(subs.items(), key=lambda item: item[0])
    ]
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def _extract_protocol_links_from_text(text: str) -> list[str]:
    if not text:
        return []
    schemes = (
        "vmess://",
        "vless://",
        "trojan://",
        "ss://",
        "ssr://",
        "hysteria://",
        "hysteria2://",
        "tuic://",
    )
    seen: set[str] = set()
    links: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line and line.startswith(schemes) and line not in seen:
            seen.add(line)
            links.append(line)
    return links


async def _owner_subscriptions(runtime: Any) -> dict[str, dict[str, Any]]:
    owner_id = int(runtime.admin_service.owner_id)
    rows = await asyncio.to_thread(runtime.get_storage().get_by_user, owner_id)
    return {str(url): dict(data) for url, data in rows.items()}


def _empty_collect_stats(total_subscriptions: int) -> dict[str, Any]:
    return {
        "total_subscriptions": total_subscriptions,
        "eligible_subscriptions": 0,
        "parsed_ok": 0,
        "parsed_failed": 0,
        "timed_out": 0,
    }


def _eligible_subscriptions(subs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    now = datetime.now()
    return {url: data for url, data in subs.items() if _is_subscription_eligible(data, now=now)}


async def _previous_pool_snapshot(state: OwnerAggregateState) -> dict[str, Any]:
    previous_meta = await state.read_meta()
    return dict(previous_meta.get("pool_snapshot", {}) or {})


def _seed_source_stats(
    subs: dict[str, dict[str, Any]], eligible_subs: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    source_stats: dict[str, dict[str, Any]] = {}
    for url in subs.keys():
        source = _source_label_from_url(url)
        row = _init_source_stat(source_stats.get(source))
        row["subscriptions"] += 1
        if url in eligible_subs:
            row["eligible_subscriptions"] += 1
        source_stats[source] = row
    return source_stats


async def _parse_eligible_subscriptions(
    runtime: Any,
    eligible_subs: dict[str, dict[str, Any]],
    source_stats: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    parser_instance = await runtime.get_parser()
    collected_nodes: list[dict[str, Any]] = []
    parse_stats = {"parsed_ok": 0, "parsed_failed": 0, "timed_out": 0}
    semaphore = asyncio.Semaphore(AGG_PARSE_CONCURRENCY)
    tasks = [
        _parse_one_subscription(
            parser_instance, url, semaphore, collected_nodes, source_stats, parse_stats
        )
        for url in eligible_subs.keys()
    ]
    await asyncio.gather(*tasks)
    return collected_nodes, parse_stats


async def _parse_one_subscription(
    parser_instance: Any,
    url: str,
    semaphore: asyncio.Semaphore,
    collected_nodes: list[dict[str, Any]],
    source_stats: dict[str, dict[str, Any]],
    parse_stats: dict[str, int],
) -> None:
    async with semaphore:
        try:
            result = await asyncio.wait_for(
                parser_instance.parse(url), timeout=AGG_PARSE_TIMEOUT_SECONDS
            )
            _record_parse_success(url, result, collected_nodes, source_stats, parse_stats)
        except asyncio.TimeoutError:
            _record_parse_failure(url, source_stats, parse_stats, timed_out=True)
            logger.warning("aggregate parse timeout url=%s", url)
        except Exception as exc:
            _record_parse_failure(url, source_stats, parse_stats, timed_out=False)
            logger.warning("aggregate parse failed url=%s err=%s", url, exc)


def _record_parse_success(
    url: str,
    result: dict[str, Any],
    collected_nodes: list[dict[str, Any]],
    source_stats: dict[str, dict[str, Any]],
    parse_stats: dict[str, int],
) -> None:
    source = _source_label_from_url(url)
    source_name = str(result.get("name", "") or "").strip()
    parsed_nodes = 0
    for node in _nodes_from_parse_result(result):
        collected_nodes.append(_apply_source_label_to_node(node, url, source_name))
        parsed_nodes += 1
    row = _init_source_stat(source_stats.get(source))
    row["parsed_ok"] += 1
    row["parsed_nodes"] += parsed_nodes
    source_stats[source] = row
    parse_stats["parsed_ok"] += 1


def _record_parse_failure(
    url: str,
    source_stats: dict[str, dict[str, Any]],
    parse_stats: dict[str, int],
    *,
    timed_out: bool,
) -> None:
    source = _source_label_from_url(url)
    row = _init_source_stat(source_stats.get(source))
    row["parsed_failed"] += 1
    if timed_out:
        row["timed_out"] += 1
        parse_stats["timed_out"] += 1
    source_stats[source] = row
    parse_stats["parsed_failed"] += 1


def _finalize_top_sources(
    source_stats: dict[str, dict[str, Any]], filter_stats: dict[str, Any]
) -> list[dict[str, Any]]:
    for row in list(filter_stats.get("top_sources", []) or []):
        if isinstance(row, dict):
            _merge_filter_source_row(source_stats, row)
    return _finalize_source_snapshot(source_stats)


def _merge_filter_source_row(source_stats: dict[str, dict[str, Any]], row: dict[str, Any]) -> None:
    source = str(row.get("source", "") or "").strip().lower()
    if not source:
        return
    merged = _init_source_stat(source_stats.get(source))
    for key in (
        "candidate_nodes",
        "quick_alive",
        "verified_alive",
        "stable_nodes",
        "published_nodes",
    ):
        merged[key] = int(row.get(key, 0) or 0)
    source_stats[source] = merged


def _build_collect_stats(
    subs: dict[str, dict[str, Any]],
    eligible_subs: dict[str, dict[str, Any]],
    *,
    parse_stats: dict[str, int],
    filter_stats: dict[str, Any],
    started_at: float,
    top_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    stats = {
        "total_subscriptions": len(subs),
        "eligible_subscriptions": len(eligible_subs),
        **parse_stats,
        **filter_stats,
    }
    stats["timings_ms"] = dict(filter_stats.get("timings_ms", {}) or {})
    stats["timings_ms"]["parse"] = _format_timing_ms(started_at)
    stats["timings_ms"]["collect_total"] = _format_timing_ms(started_at)
    stats["top_sources"] = top_sources
    return stats


def _fingerprint_row(url: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "url": url,
        "updated_at": data.get("updated_at"),
        "last_check_status": data.get("last_check_status"),
        "expire_time": data.get("expire_time"),
        "remaining": data.get("remaining"),
    }
