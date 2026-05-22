"""Audit-focused Web Admin API handlers."""

from __future__ import annotations

import asyncio
import csv
import html as html_lib
import io
import json
import re
from datetime import datetime, timedelta
from typing import Any

from aiohttp import web

from web.admin.users_api import _json_error, _parse_limit, _parse_positive_int
from web.constants import ALLOW_HEADER_TOKEN_KEY, COOKIE_SECURE_KEY, RUNTIME_KEY


def _parse_datetime_text(value: str | None) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _format_identity(runtime: Any, uid: int | None) -> str:
    return runtime.user_profile_service.format_user_identity(uid)


def _plain_identity_text(value: Any) -> str:
    raw = html_lib.unescape(str(value or ""))
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw or "-"


def _brief_identity_text(value: Any) -> str:
    text = _plain_identity_text(value)
    text = re.sub(r"\(\d{5,}\)", "", text).strip()
    text = text.lstrip("@").strip()
    text = re.sub(r"\s+", " ", text).strip()
    return text or "-"


async def _collect_check_rows_async(
    runtime: Any,
    *,
    mode: str,
    page: int = 1,
    limit: int,
    query_text: str = "",
    source: str = "",
    user_id: int | None = None,
    dt_from: datetime | None = None,
    dt_to: datetime | None = None,
) -> dict[str, Any]:
    q_text = query_text.strip().lower()
    src = source.strip().lower()

    def predicate(row):
        uid = row.get("user_id")
        if user_id is not None and uid != user_id:
            return False
        row_source = str(row.get("source", ""))
        if src and src not in row_source.lower():
            return False
        ts = _parse_datetime_text(row.get("ts"))
        if dt_from and (ts is None or ts < dt_from):
            return False
        if dt_to and (ts is None or ts > dt_to):
            return False
        if q_text:
            identity = _format_identity(runtime, uid if isinstance(uid, int) else None)
            urls = [str(u) for u in (row.get("urls") or []) if str(u).strip()]
            haystack = " ".join([identity, row_source, " ".join(urls), str(uid or "")]).lower()
            if q_text not in haystack:
                return False
        return True

    data = await runtime.usage_audit_service.aquery_records(
        owner_id=runtime.admin_service.owner_id,
        mode=mode,
        page=page,
        page_size=limit,
        predicate=predicate,
    )
    rows = []
    for row in data["records"]:
        uid = row.get("user_id")
        rows.append(
            {
                "user_id": uid if isinstance(uid, int) else 0,
                "identity": _format_identity(runtime, uid if isinstance(uid, int) else None),
                "ts": row.get("ts", "-"),
                "source": str(row.get("source", "")),
                "url_count": len(row.get("urls") or []),
                "urls": row.get("urls") or [],
            }
        )
    return {
        "mode": data["mode"],
        "total": data["total"],
        "total_pages": data["total_pages"],
        "rows": rows,
    }


async def _audit_summary(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    mode = request.query.get("mode", "others").strip().lower()
    if mode not in {"others", "owner", "all"}:
        return _json_error("invalid_mode", status=400)
    try:
        data = await asyncio.to_thread(runtime.admin_service.get_usage_audit_summary, mode=mode)
        return web.json_response({"ok": True, "data": data})
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def _recent_checks(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    mode = request.query.get("mode", "others").strip().lower()
    if mode not in {"others", "owner", "all"}:
        return _json_error("invalid_mode", status=400)
    page, err = _parse_positive_int(request, "page", 1, 1, 10000)
    if err is not None:
        return err
    limit, err = _parse_limit(request, default=20, maximum=200)
    if err is not None:
        return err
    raw_uid = request.query.get("user_id", "").strip()
    user_id: int | None = None
    if raw_uid:
        try:
            user_id = int(raw_uid)
        except ValueError:
            return _json_error("invalid_user_id", status=400)
    try:
        data = await _collect_check_rows_async(
            runtime,
            mode=mode,
            page=page,
            limit=limit,
            query_text=request.query.get("q", ""),
            source=request.query.get("source", ""),
            user_id=user_id,
            dt_from=_parse_datetime_text(request.query.get("from")),
            dt_to=_parse_datetime_text(request.query.get("to")),
        )
        return web.json_response({"ok": True, "data": data})
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def _audit_alerts(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    hf_threshold, err = _parse_positive_int(request, "high_freq_threshold", 12, 1, 500)
    if err is not None:
        return err
    url_threshold, err = _parse_positive_int(request, "high_url_threshold", 40, 1, 2000)
    if err is not None:
        return err
    cutoff = datetime.now() - timedelta(hours=24)

    def is_recent(row: dict[str, Any]) -> bool:
        ts = _parse_datetime_text(row.get("ts"))
        return ts is not None and ts >= cutoff

    raw = await runtime.usage_audit_service.aquery_records(
        owner_id=runtime.admin_service.owner_id,
        mode="all",
        page=1,
        page_size=2000,
        predicate=is_recent,
    )
    rows = _alert_rows(runtime, raw.get("records", []))
    alerts = _security_alerts(request, runtime)
    alerts.extend(_usage_alerts(rows, hf_threshold=hf_threshold, url_threshold=url_threshold))
    return web.json_response(
        {"ok": True, "data": {"window_hours": 24, "alerts": alerts, "recent_check_rows": len(rows)}}
    )


def _alert_rows(runtime: Any, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in records:
        uid = row.get("user_id")
        rows.append(
            {
                "user_id": uid if isinstance(uid, int) else 0,
                "identity": _plain_identity_text(
                    _format_identity(runtime, uid if isinstance(uid, int) else None)
                ),
                "url_count": len(row.get("urls") or []),
            }
        )
    return rows


def _security_alerts(request: web.Request, runtime: Any) -> list[dict[str, Any]]:
    alerts = []
    if runtime.access_service.is_allow_all_users_enabled():
        alerts.append(
            {
                "severity": "high",
                "title": "公开访问已开启",
                "detail": "当前 allow_all_users=true，建议仅临时使用。",
            }
        )
    if request.app[ALLOW_HEADER_TOKEN_KEY]:
        alerts.append(
            {
                "severity": "medium",
                "title": "Header Token 已开启",
                "detail": "建议仅在必须的自动化场景开启。",
            }
        )
    if not request.app[COOKIE_SECURE_KEY]:
        alerts.append(
            {
                "severity": "medium",
                "title": "Cookie Secure 未开启",
                "detail": "HTTPS 场景建议启用 WEB_ADMIN_COOKIE_SECURE=true。",
            }
        )
    return alerts


def _usage_alerts(
    rows: list[dict[str, Any]], *, hf_threshold: int, url_threshold: int
) -> list[dict[str, Any]]:
    bucket: dict[int, dict[str, Any]] = {}
    for row in rows:
        uid = int(row.get("user_id", 0) or 0)
        item = bucket.setdefault(
            uid,
            {"checks": 0, "urls": 0, "identity": _brief_identity_text(row.get("identity", "-"))},
        )
        item["checks"] += 1
        item["urls"] += int(row.get("url_count", 0) or 0)
    alerts = []
    for uid, item in sorted(bucket.items(), key=lambda x: (-x[1]["checks"], -x[1]["urls"]))[:20]:
        if item["checks"] >= hf_threshold:
            alerts.append(
                {
                    "severity": "medium",
                    "title": "高频检测用户",
                    "detail": f"{item['identity']} 24h 检测 {item['checks']} 次。",
                    "uid": uid,
                }
            )
        if item["urls"] >= url_threshold:
            alerts.append(
                {
                    "severity": "medium",
                    "title": "高 URL 量用户",
                    "detail": f"{item['identity']} 24h 检测 URL 共 {item['urls']} 个。",
                    "uid": uid,
                }
            )
    return alerts


async def _build_export_rows(
    runtime: Any, request: web.Request
) -> tuple[list[dict[str, Any]], web.Response | None]:
    mode = request.query.get("mode", "others").strip().lower()
    if mode not in {"others", "owner", "all"}:
        return [], _json_error("invalid_mode", status=400)
    limit, err = _parse_limit(request, default=300, maximum=2000)
    if err is not None:
        return [], err
    raw_uid = request.query.get("user_id", "").strip()
    user_id = int(raw_uid) if raw_uid.isdigit() else None
    if raw_uid and user_id is None:
        return [], _json_error("invalid_user_id", status=400)
    data = await _collect_check_rows_async(
        runtime,
        mode=mode,
        limit=limit,
        query_text=request.query.get("q", ""),
        source=request.query.get("source", ""),
        user_id=user_id,
        dt_from=_parse_datetime_text(request.query.get("from")),
        dt_to=_parse_datetime_text(request.query.get("to")),
    )
    return data.get("rows", []), None


def _render_audit_csv(rows: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["user_id", "identity", "ts", "source", "url_count", "urls"])
    for row in rows:
        writer.writerow(
            [
                row.get("user_id", 0),
                row.get("identity", "-"),
                row.get("ts", "-"),
                row.get("source", "-"),
                row.get("url_count", 0),
                "\n".join(row.get("urls", [])),
            ]
        )
    return output.getvalue()


async def _audit_export(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    fmt = request.query.get("format", "csv").strip().lower()
    rows, err = await _build_export_rows(runtime, request)
    if err is not None:
        return err
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if fmt == "json":
        body = await asyncio.to_thread(json.dumps, rows, ensure_ascii=False, indent=2)
        return web.Response(
            text=body,
            content_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="audit_checks_{ts}.json"'},
        )
    if fmt != "csv":
        return _json_error("invalid_format", status=400)
    csv_text = await asyncio.to_thread(_render_audit_csv, rows)
    return web.Response(
        text=csv_text,
        content_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="audit_checks_{ts}.csv"'},
    )
