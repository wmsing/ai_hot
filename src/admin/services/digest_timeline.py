"""Admin Digest 按发布日（与首页时间线一致）浏览。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from src.admin.stores import digest as digest_store
from src.digest import has_usable_digest_summary
from src.digest_days import list_digest_days
from src.models import DigestItem
from src.normalize import normalize_url
from src.timeutil import parse_published


@dataclass(frozen=True)
class TimelineDigestRow:
    published_day: date
    archive_day: date
    item: digest_store.MergedDigestItem


def _published_day(published: str, archive_day: date) -> date:
    dt = parse_published(published)
    if dt is not None:
        return dt.astimezone(timezone.utc).date()
    return archive_day


def _sort_ts(item: DigestItem, archive_day: date) -> float:
    dt = parse_published(item.published)
    if dt is not None:
        return dt.timestamp()
    fallback = datetime(
        archive_day.year,
        archive_day.month,
        archive_day.day,
        tzinfo=timezone.utc,
    )
    return fallback.timestamp()


def _to_digest_item(merged: digest_store.MergedDigestItem, *, lang: str) -> DigestItem:
    if lang == "zh":
        return DigestItem(
            index=merged.index,
            title=merged.title_zh or merged.title_en,
            source=merged.source,
            url=merged.url,
            published=merged.published,
            score_line=merged.score_line,
            summary=merged.summary_zh,
            speak_summary=merged.speak_zh,
            tag=merged.tag,
            image_url=merged.image_url,
        )
    return DigestItem(
        index=merged.index,
        title=merged.title_en,
        source=merged.source,
        url=merged.url,
        published=merged.published,
        score_line=merged.score_line,
        summary=merged.summary_en,
        speak_summary=merged.speak_en,
        tag=merged.tag,
        image_url=merged.image_url,
    )


def build_timeline_rows(content_dir: Path) -> list[TimelineDigestRow]:
    """跨归档合并：与首页相同 URL 去重 + 可展示摘要过滤；按 published 分组。"""
    by_url: dict[str, tuple[float, TimelineDigestRow]] = {}
    orphans: list[tuple[float, TimelineDigestRow]] = []
    for day_files in list_digest_days(content_dir):
        try:
            view = digest_store.get_day(content_dir, day_files.day)
        except FileNotFoundError:
            continue
        for merged in view.items:
            en_item = _to_digest_item(merged, lang="en")
            zh_item = _to_digest_item(merged, lang="zh")
            if not has_usable_digest_summary(
                en_item.summary, title=en_item.title
            ) and not has_usable_digest_summary(zh_item.summary, title=zh_item.title):
                continue
            ts = max(_sort_ts(en_item, day_files.day), _sort_ts(zh_item, day_files.day))
            published_day = _published_day(merged.published, day_files.day)
            row = TimelineDigestRow(
                published_day=published_day,
                archive_day=day_files.day,
                item=merged,
            )
            url = merged.url.strip()
            if not url:
                orphans.append((ts, row))
                continue
            key = normalize_url(url)
            prev = by_url.get(key)
            if prev is None or ts > prev[0]:
                by_url[key] = (ts, row)
    ranked = list(by_url.values()) + orphans
    ranked.sort(key=lambda pair: (-pair[0], pair[1].item.url))
    return [row for _, row in ranked]


def list_published_days(content_dir: Path) -> list[date]:
    days = {row.published_day for row in build_timeline_rows(content_dir)}
    return sorted(days, reverse=True)


def rows_for_published_day(
    content_dir: Path,
    published_day: date,
) -> list[TimelineDigestRow]:
    return [
        row
        for row in build_timeline_rows(content_dir)
        if row.published_day == published_day
    ]


RECENT_PUBLISHED_DAYS_DEFAULT = 5


def rows_for_recent_published_days(
    content_dir: Path,
    *,
    limit: int = RECENT_PUBLISHED_DAYS_DEFAULT,
) -> tuple[list[date], list[TimelineDigestRow]]:
    """最近 N 个发布日内的全部时间线条目（与首页展示范围一致）。"""
    if limit < 1:
        raise ValueError("limit must be >= 1")
    days = list_published_days(content_dir)[:limit]
    day_set = set(days)
    rows = [
        row
        for row in build_timeline_rows(content_dir)
        if row.published_day in day_set
    ]
    return days, rows
