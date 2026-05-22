"""Timezone helpers for user-facing subscription timestamps."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta


DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_FORMAT = "%Y-%m-%d"
BEIJING_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def now_beijing() -> datetime:
    return datetime.now(BEIJING_TZ).replace(tzinfo=None)


def format_beijing(dt: datetime) -> str:
    if dt.tzinfo is not None:
        dt = dt.astimezone(BEIJING_TZ).replace(tzinfo=None)
    return dt.strftime(DATETIME_FORMAT)


def format_beijing_now() -> str:
    return format_beijing(now_beijing())


def format_unix_timestamp_beijing(value: int | str, fmt: str = DATETIME_FORMAT) -> str:
    return datetime.fromtimestamp(int(value), tz=BEIJING_TZ).strftime(fmt)


def format_beijing_timestamp(value: int | str, fmt: str = DATETIME_FORMAT) -> str:
    return format_unix_timestamp_beijing(value, fmt)


def parse_beijing(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, DATETIME_FORMAT)
    except ValueError:
        return None
