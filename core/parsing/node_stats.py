"""Node protocol and location statistics for parsed subscriptions."""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

from app import config
from core import node_extractor as ip_extractor
from core.geo_service import GeoLocationService


COUNTRY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "香港": ("香港", "HK", "Hong Kong", "Hongkong"),
    "台湾": ("台湾", "TW", "Taiwan"),
    "日本": ("日本", "JP", "Japan"),
    "美国": ("美国", "US", "USA", "America"),
    "新加坡": ("新加坡", "SG", "Singapore"),
    "韩国": ("韩国", "KR", "Korea"),
}
UNKNOWN_COUNTRY = "其他"
UNKNOWN_DETAIL_VALUE = "未知"
UNKNOWN_FLAG = "🌐"
MAX_LOCATION_DETAILS_PER_COUNTRY = 3


async def analyze_nodes(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    protocol_stats = _protocol_stats(nodes)
    if not config.ENABLE_GEO_LOOKUP:
        countries = [match_country_by_keyword(str(node.get("name", ""))) for node in nodes]
        return {"protocols": protocol_stats, "countries": dict(Counter(countries)), "locations": []}
    return await _analyze_with_geo(nodes, protocol_stats)


def match_country_by_keyword(node_name: str) -> str:
    for country, keywords in COUNTRY_KEYWORDS.items():
        if any(keyword in node_name for keyword in keywords):
            return country
    return UNKNOWN_COUNTRY


def _protocol_stats(nodes: list[dict[str, Any]]) -> dict[str, int]:
    protocols = [str(node.get("protocol", "unknown")) for node in nodes]
    return dict(Counter(protocols))


async def _analyze_with_geo(
    nodes: list[dict[str, Any]], protocol_stats: dict[str, int]
) -> dict[str, Any]:
    geo_client = GeoLocationService()
    node_ip_pairs = _node_ip_pairs(nodes)
    geo_results = await _query_geo_locations(geo_client, node_ip_pairs)
    countries, locations = _build_location_stats(geo_client, node_ip_pairs, geo_results)
    return {
        "protocols": protocol_stats,
        "countries": dict(Counter(countries)),
        "locations": locations,
    }


def _node_ip_pairs(nodes: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str | None]]:
    pairs: list[tuple[dict[str, Any], str | None]] = []
    for node in nodes:
        ip = ip_extractor.NodeIPExtractor.extract_ip(node)
        valid_ip = ip if ip and ip_extractor.NodeIPExtractor.is_valid_ip(ip) else None
        pairs.append((node, valid_ip))
    return pairs


async def _query_geo_locations(
    geo_client: GeoLocationService,
    node_ip_pairs: list[tuple[dict[str, Any], str | None]],
) -> dict[str, Any | None]:
    geo_nodes = [(node, ip) for node, ip in node_ip_pairs if ip is not None][
        : config.MAX_GEO_QUERIES
    ]
    if not geo_nodes:
        return {}
    unique_ips = list({ip for _, ip in geo_nodes})
    results = await asyncio.gather(
        *[geo_client.get_location(ip) for ip in unique_ips], return_exceptions=True
    )
    return {
        ip: None if isinstance(result, Exception) else result
        for ip, result in zip(unique_ips, results)
    }


def _build_location_stats(
    geo_client: GeoLocationService,
    node_ip_pairs: list[tuple[dict[str, Any], str | None]],
    geo_results: dict[str, Any | None],
) -> tuple[list[str], list[dict[str, Any]]]:
    countries: list[str] = []
    locations: list[dict[str, Any]] = []
    detail_count: Counter[str] = Counter()
    geo_query_used = 0
    for node, ip in node_ip_pairs:
        country, detail = _node_location_detail(geo_client, node, ip, geo_results, geo_query_used)
        if ip and geo_query_used < config.MAX_GEO_QUERIES:
            geo_query_used += 1
        countries.append(country)
        if detail and detail_count[country] < MAX_LOCATION_DETAILS_PER_COUNTRY:
            locations.append(detail)
            detail_count[country] += 1
    return countries, locations


def _node_location_detail(
    geo_client: GeoLocationService,
    node: dict[str, Any],
    ip: str | None,
    geo_results: dict[str, Any | None],
    geo_query_used: int,
) -> tuple[str, dict[str, Any]]:
    if ip and geo_query_used < config.MAX_GEO_QUERIES:
        location = geo_results.get(ip)
        if location:
            country = str(location["country"])
            return country, _geo_detail(geo_client, node, location)
    country = match_country_by_keyword(str(node.get("name", "")))
    return country, _fallback_detail(node, country)


def _geo_detail(
    geo_client: GeoLocationService, node: dict[str, Any], location: dict[str, Any]
) -> dict[str, Any]:
    country_code = str(location["country_code"])
    return {
        "name": node.get("name", UNKNOWN_DETAIL_VALUE),
        "country": location["country"],
        "city": location["city"],
        "isp": location["isp"],
        "country_code": country_code,
        "flag": geo_client.get_country_flag(country_code),
    }


def _fallback_detail(node: dict[str, Any], country: str) -> dict[str, Any]:
    return {
        "name": node.get("name", UNKNOWN_DETAIL_VALUE),
        "country": country,
        "city": UNKNOWN_DETAIL_VALUE,
        "isp": UNKNOWN_DETAIL_VALUE,
        "country_code": "",
        "flag": UNKNOWN_FLAG,
    }


__all__ = ["analyze_nodes", "match_country_by_keyword"]
