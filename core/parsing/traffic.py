"""Traffic metadata parsing for subscription responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any


TRAFFIC_HEADER = "subscription-userinfo"
TRAFFIC_WARNING_HEADER = "x-traffic-warning"
TRAFFIC_COUNTER_FIELDS = {"upload", "download", "total"}


def parse_traffic_info(headers: dict[str, str]) -> dict[str, Any]:
    traffic_info: dict[str, Any] = {}
    userinfo = str(headers.get(TRAFFIC_HEADER, "") or "")
    if not userinfo:
        return _traffic_warning(headers)
    for part in userinfo.split(";"):
        _parse_userinfo_part(part, traffic_info)
    _attach_usage_totals(traffic_info)
    return traffic_info


def _traffic_warning(headers: dict[str, str]) -> dict[str, Any]:
    warning = str(headers.get(TRAFFIC_WARNING_HEADER, "") or "").strip()
    if not warning:
        return {}
    return {"_traffic_warning": warning}


def _parse_userinfo_part(part: str, traffic_info: dict[str, Any]) -> None:
    item = part.strip()
    if "=" not in item:
        return
    key, value = item.split("=", 1)
    key = key.strip()
    value = value.strip()
    if key in TRAFFIC_COUNTER_FIELDS:
        traffic_info[key] = int(value)
    elif key == "expire":
        _parse_expire_time(value, traffic_info)


def _parse_expire_time(value: str, traffic_info: dict[str, Any]) -> None:
    try:
        traffic_info["expire_time"] = datetime.fromtimestamp(int(value)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except Exception:
        return


def _attach_usage_totals(traffic_info: dict[str, Any]) -> None:
    if "upload" in traffic_info and "download" in traffic_info:
        traffic_info["used"] = traffic_info["upload"] + traffic_info["download"]
    if "total" not in traffic_info or "used" not in traffic_info:
        return
    traffic_info["remaining"] = traffic_info["total"] - traffic_info["used"]
    if traffic_info["total"] > 0:
        traffic_info["usage_percent"] = (traffic_info["used"] / traffic_info["total"]) * 100


__all__ = ["parse_traffic_info"]
