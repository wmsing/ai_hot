"""发布时间解析与格式化。"""

from __future__ import annotations

from datetime import datetime, timezone
from time import struct_time
from typing import Any


def format_published(value: datetime | None) -> str:
    if value is None:
        return "n/a"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def from_unix(ts: Any) -> datetime | None:
    try:
        seconds = int(ts)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def from_struct_time(st: Any) -> datetime | None:
    if not isinstance(st, struct_time):
        return None
    try:
        return datetime(
            st.tm_year,
            st.tm_mon,
            st.tm_mday,
            st.tm_hour,
            st.tm_min,
            st.tm_sec,
            tzinfo=timezone.utc,
        )
    except (ValueError, OverflowError):
        return None


def from_rss_entry(entry: Any) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = from_struct_time(getattr(entry, attr, None))
        if parsed is not None:
            return parsed
    return None
