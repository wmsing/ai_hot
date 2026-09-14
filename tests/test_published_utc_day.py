"""Digest 巡检：仅收录 UTC 当日发布。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.digest import merge_by_url
from src.models import HotItem
from src.normalize import titles_similar
from src.timeutil import is_published_on_utc_day, published_utc_date


def test_published_utc_date_normalizes_tz() -> None:
    dt = datetime(2026, 9, 14, 8, 30, tzinfo=timezone(timedelta(hours=8)))
    assert published_utc_date(dt) == datetime(2026, 9, 14, tzinfo=timezone.utc).date()


def test_is_published_on_utc_day() -> None:
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    same_day = datetime(2026, 9, 14, 1, 0, tzinfo=timezone.utc)
    prev_day = datetime(2026, 9, 13, 23, 0, tzinfo=timezone.utc)
    assert is_published_on_utc_day(same_day, now=now)
    assert not is_published_on_utc_day(prev_day, now=now)
    assert not is_published_on_utc_day(None, now=now)


def test_titles_similar_ignores_punctuation() -> None:
    assert titles_similar("Hello, World!", "hello world")


def test_merge_by_url_skips_similar_title() -> None:
    existing = [
        HotItem(
            source="hn",
            title="Apple ships M5 MacBook Pro",
            url="https://example.com/a",
            reason="r1",
        ),
    ]
    new = [
        HotItem(
            source="rss:x",
            title="Apple ships M5 MacBook Pro!!!",
            url="https://other.example/b",
            reason="r2",
        ),
        HotItem(
            source="hn",
            title="Brand new story",
            url="https://example.com/c",
            reason="r3",
        ),
    ]
    merged = merge_by_url(existing, new)
    assert len(merged) == 2
    assert merged[0].url == "https://example.com/a"
    assert merged[1].url == "https://example.com/c"
