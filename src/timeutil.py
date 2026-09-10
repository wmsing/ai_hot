"""发布时间解析与格式化。"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from time import struct_time
from typing import Any

_HOUR_UTC_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})\s+(\d{2}):00\s+UTC$",
    re.IGNORECASE,
)


def format_published(value: datetime | None) -> str:
    """只保留到 UTC 小时，例如 2026-09-10 01:00 UTC。"""
    if value is None:
        return "n/a"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    utc = value.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return utc.strftime("%Y-%m-%d %H:00 UTC")


def parse_published(raw: str) -> datetime | None:
    """解析 digest 里的 published（新小时格式或旧 ISO）。"""
    text = raw.strip()
    if not text or text.lower() == "n/a":
        return None
    hour_m = _HOUR_UTC_RE.match(text)
    if hour_m:
        try:
            return datetime(
                int(hour_m.group(1)[0:4]),
                int(hour_m.group(1)[5:7]),
                int(hour_m.group(1)[8:10]),
                int(hour_m.group(2)),
                tzinfo=timezone.utc,
            )
        except ValueError:
            return None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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
