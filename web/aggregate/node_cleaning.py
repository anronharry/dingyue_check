from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any
from urllib.parse import urlparse

from web import constants as c

REQUIRED_PROXY_FIELDS: dict[str, tuple[str, ...]] = {
    "vmess": ("uuid",),
    "vless": ("uuid",),
    "trojan": ("password",),
    "ss": ("cipher", "password"),
    "ssr": ("cipher", "password", "protocol", "obfs"),
    "hysteria2": ("password",),
    "tuic": ("uuid", "password"),
}


def _node_quality_key(node: dict[str, Any]) -> tuple[float, str]:
    latency_raw = node.get("latency") or node.get("delay") or node.get("latency_ms")
    if latency_raw is None:
        latency_raw = 999999.0
    try:
        latency = float(latency_raw)
    except Exception:
        latency = 999999.0
    return latency, str(node.get("name", ""))


def _health_score_step(mode: str, status: str) -> int:
    matrix = {
        ("quick", "alive"): 8,
        ("quick", "dead"): -10,
        ("verify", "alive"): 18,
        ("verify", "dead"): -24,
    }
    return matrix.get((str(mode), str(status)), 0)


def _clamp_health_score(value: int) -> int:
    return max(c.AGG_HEALTH_SCORE_MIN, min(c.AGG_HEALTH_SCORE_MAX, int(value)))


def _build_source_seed_scores(snapshot: dict[str, Any] | None) -> dict[str, int]:
    rows = list((snapshot or {}).get("top_sources", []) or [])
    seeded: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source", "") or "").strip().lower()
        if source:
            seeded[source] = int(row.get("reputation_score", 0) or 0)
    return seeded


def _source_sort_key(node: dict[str, Any], seed_scores: dict[str, int]) -> tuple[int, str, str]:
    source = _aggregate_source_bucket(node)
    return (-int(seed_scores.get(source, 0) or 0), source, str(node.get("name", "") or ""))


def _source_candidate_limit(source: str, seed_scores: dict[str, int]) -> int:
    score = int(seed_scores.get(source, 0) or 0)
    if score >= 85:
        return c.AGG_NODE_SOURCE_LIMIT
    if score >= 60:
        return max(4, c.AGG_NODE_SOURCE_LIMIT - 6)
    if score >= 30:
        return max(3, c.AGG_NODE_SOURCE_LIMIT // 2)
    return max(2, c.AGG_NODE_SOURCE_LIMIT // 3)


def _effective_health_score(row: dict[str, Any] | None, *, now_ts: int) -> int:
    if not isinstance(row, dict):
        return 0
    score = int(row.get("health_score", 0) or 0)
    checked_at = int(row.get("checked_at", 0) or 0)
    if checked_at <= 0:
        return score
    age = max(0, now_ts - checked_at)
    penalty = age // max(1, c.AGG_HEALTH_DECAY_WINDOW_SECONDS)
    return _clamp_health_score(score - int(penalty) * 8)


def _rank_health_row(
    node: dict[str, Any], cache_rows: dict[str, Any]
) -> tuple[int, int, float, str]:
    cached = cache_rows.get(_aggregate_node_cache_key(node))
    if not isinstance(cached, dict):
        return (1, 0, *_node_quality_key(node))
    stable_rank = 0 if _is_aggregate_health_stable(cached) else 1
    score_rank = -_effective_health_score(cached, now_ts=int(time.time()))
    latency_rank = float(cached.get("latency", node.get("latency", 999999.0)) or 999999.0)
    return stable_rank, score_rank, latency_rank, str(node.get("name", "") or "")


def _count_nodes_by_source(nodes: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in nodes:
        source = _aggregate_source_bucket(node)
        counts[source] = counts.get(source, 0) + 1
    return counts


def _aggregate_server_bucket(node: dict[str, Any]) -> str:
    server = str(node.get("server") or node.get("address") or "").strip().lower()
    port = str(node.get("port", "") or "").strip()
    return f"{server}:{port}"


def _normalize_aggregate_proxy(row: dict[str, Any]) -> dict[str, Any] | None:
    ptype = str(row.get("type") or row.get("protocol") or "").strip().lower()
    server = str(row.get("server", "")).strip()
    try:
        port = int(row.get("port", 0) or 0)
    except Exception:
        port = 0
    if not ptype or not server or port <= 0:
        return None
    for field in REQUIRED_PROXY_FIELDS.get(ptype, ()):
        if str(row.get(field, "") or "").strip() == "":
            return None
    proxy = dict(row)
    proxy["name"] = str(row.get("name", "")).strip() or f"{ptype}-{server}:{port}"
    proxy["type"] = ptype
    proxy["server"] = server
    proxy["port"] = port
    return proxy


def _nodes_from_parse_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    primary = result.get("_raw_nodes") or result.get("_normalized_nodes") or []
    if not isinstance(primary, list):
        return []
    return [node for node in primary if isinstance(node, dict)]


def _source_label_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or parsed.path or "").strip()
    except Exception:
        host = ""
    host = host or "unknown"
    host = host.split("@")[-1].split(":")[0].strip() or "unknown"
    return host[:36]


def _source_label_from_name(name: str) -> str:
    label = str(name or "").strip()
    if not label:
        return ""
    return label[:36]


def _apply_source_label_to_node(
    node: dict[str, Any], source_url: str, source_name: str = ""
) -> dict[str, Any]:
    row = dict(node)
    base_name = str(row.get("name", "") or "").strip() or "unnamed"
    source_label = _source_label_from_name(source_name) or _source_label_from_url(source_url)
    tag = f"[src:{source_label}]"
    if tag not in base_name:
        row["name"] = f"{base_name} {tag}"
    return row


def _aggregate_node_key(node: dict[str, Any]) -> tuple[str, str, int, str]:
    ptype = str(node.get("type") or node.get("protocol") or "").strip().lower()
    server = str(node.get("server") or node.get("address") or "").strip().lower()
    try:
        port = int(node.get("port", 0) or 0)
    except Exception:
        port = 0
    auth = str(node.get("uuid") or node.get("password") or node.get("auth-str") or "").strip()
    return ptype, server, port, auth


def _aggregate_node_cache_key(node: dict[str, Any]) -> str:
    payload = json.dumps(_aggregate_node_key(node), ensure_ascii=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _dedupe_aggregate_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, int, str]] = set()
    unique: list[dict[str, Any]] = []
    for row in nodes:
        key = _aggregate_node_key(row)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _aggregate_source_bucket(node: dict[str, Any]) -> str:
    name = str(node.get("name", "") or "")
    match = re.search(r"\[src:([^\]]+)\]", name)
    if match:
        return match.group(1).strip().lower() or "unknown"
    return "unknown"


def _select_aggregate_candidates(
    nodes: list[dict[str, Any]],
    seed_scores: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    per_source: dict[str, int] = {}
    scores = dict(seed_scores or {})
    for row in nodes:
        if len(selected) >= c.AGG_NODE_CANDIDATE_LIMIT:
            break
        bucket = _aggregate_source_bucket(row)
        used = per_source.get(bucket, 0)
        if used >= _source_candidate_limit(bucket, scores):
            continue
        per_source[bucket] = used + 1
        selected.append(row)
    return selected


def _limit_published_aggregate_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    per_source: dict[str, int] = {}
    per_server: dict[str, int] = {}
    for node in nodes:
        if len(selected) >= c.AGG_NODE_PUBLISH_LIMIT:
            break
        source = _aggregate_source_bucket(node)
        server = _aggregate_server_bucket(node)
        if per_source.get(source, 0) >= c.AGG_PUBLISH_SOURCE_LIMIT:
            continue
        if per_server.get(server, 0) >= c.AGG_PUBLISH_SERVER_LIMIT:
            continue
        per_source[source] = per_source.get(source, 0) + 1
        per_server[server] = per_server.get(server, 0) + 1
        selected.append(node)
    return selected


def _load_cached_aggregate_health(
    cache_rows: dict[str, Any],
    node: dict[str, Any],
    *,
    now_ts: int,
) -> dict[str, Any] | None:
    row = cache_rows.get(_aggregate_node_cache_key(node))
    if not isinstance(row, dict):
        return None
    checked_at = int(row.get("checked_at", 0) or 0)
    if checked_at <= 0:
        return None
    mode = str(row.get("mode", "") or "")
    ttl = c.AGG_NODE_VERIFY_TTL_SECONDS if mode == "verify" else c.AGG_NODE_QUICK_TTL_SECONDS
    if now_ts - checked_at > ttl:
        return None
    return row


def _merge_cached_aggregate_health(
    cache_rows: dict[str, Any], updates: dict[str, Any], *, now_ts: int
) -> dict[str, Any]:
    merged = dict(cache_rows or {})
    merged.update(updates or {})
    max_ttl = max(c.AGG_NODE_QUICK_TTL_SECONDS, c.AGG_NODE_VERIFY_TTL_SECONDS)
    fresh: dict[str, Any] = {}
    for key, row in merged.items():
        if not isinstance(row, dict):
            continue
        checked_at = int(row.get("checked_at", 0) or 0)
        if checked_at > 0 and now_ts - checked_at <= max_ttl * 3:
            fresh[key] = row
    return fresh


def _is_aggregate_health_stable(row: dict[str, Any]) -> bool:
    return int(row.get("success_streak", 0) or 0) >= c.AGG_NODE_STABLE_SUCCESS_THRESHOLD


def _is_aggregate_health_evicted(row: dict[str, Any]) -> bool:
    return int(row.get("failure_streak", 0) or 0) >= c.AGG_NODE_EVICT_FAILURE_THRESHOLD


def _mark_aggregate_health(
    mode: str,
    status: str,
    *,
    latency: float | int = 0,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prev_success = int((previous or {}).get("success_streak", 0) or 0)
    prev_failure = int((previous or {}).get("failure_streak", 0) or 0)
    prev_score = int((previous or {}).get("health_score", 0) or 0)
    is_alive = str(status) == "alive"
    success_streak = prev_success + 1 if is_alive else 0
    failure_streak = 0 if is_alive else prev_failure + 1
    score = _clamp_health_score(prev_score + _health_score_step(mode, status))
    return {
        "mode": str(mode),
        "status": str(status),
        "checked_at": int(time.time()),
        "latency": float(latency or 0.0),
        "success_streak": success_streak,
        "failure_streak": failure_streak,
        "health_score": score,
        "stable": success_streak >= c.AGG_NODE_STABLE_SUCCESS_THRESHOLD,
    }
