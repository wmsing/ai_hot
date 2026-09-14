"""Digest 按发布日浏览。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from src.admin.services.digest_timeline import (
    list_published_days,
    rows_for_published_day,
    rows_for_recent_published_days,
)
from src.admin.stores import digest as digest_store


def test_timeline_groups_by_published_day(tmp_path: Path) -> None:
    digests_dir = tmp_path / "digests"
    digests_dir.mkdir(parents=True)
    day = date(2026, 9, 13)
    digest_store.add_item(
        digests_dir,
        day,
        title_en="Published on 13th",
        title_zh="十三日发布",
        url="https://example.com/a",
        source="manual",
        published="2026-09-13 00:00 UTC",
        summary_en="English summary with enough text.",
        summary_zh="中文摘要足够长。",
    )
    digest_store.add_item(
        digests_dir,
        day,
        title_en="Published on 12th",
        title_zh="十二日发布",
        url="https://example.com/b",
        source="manual",
        published="2026-09-12 20:00 UTC",
        summary_en="Another English summary here.",
        summary_zh="另一条中文摘要。",
    )

    days = list_published_days(digests_dir)
    assert date(2026, 9, 13) in days
    assert date(2026, 9, 12) in days
    rows_13 = rows_for_published_day(digests_dir, date(2026, 9, 13))
    assert len(rows_13) == 1
    assert rows_13[0].item.url == "https://example.com/a"
    assert rows_13[0].archive_day == day


def test_recent_published_days_limits_distinct_days(tmp_path: Path) -> None:
    digests_dir = tmp_path / "digests"
    digests_dir.mkdir(parents=True)
    archive = date(2026, 9, 10)
    for offset, pub in enumerate(
        (
            "2026-09-10 12:00 UTC",
            "2026-09-09 12:00 UTC",
            "2026-09-08 12:00 UTC",
            "2026-09-07 12:00 UTC",
            "2026-09-06 12:00 UTC",
            "2026-09-05 12:00 UTC",
        )
    ):
        digest_store.add_item(
            digests_dir,
            archive,
            title_en=f"Item {offset}",
            title_zh=f"条目 {offset}",
            url=f"https://example.com/{offset}",
            source="manual",
            published=pub,
            summary_en="English summary with enough text.",
            summary_zh="中文摘要足够长。",
        )

    days, rows = rows_for_recent_published_days(digests_dir, limit=5)
    assert len(days) == 5
    assert date(2026, 9, 5) not in days
    assert len(rows) == 5
