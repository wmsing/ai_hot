"""把今日热搜条目复制到 Digest 归档。"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from src.admin.stores import digest as digest_store
from src.admin.stores import hot_topics as hot_topics_store
from src.digest import format_score_line
from src.models import AppConfig, HotTopicSnapshotItem
from src.normalize import normalize_url
from src.textutil import contains_cjk, speak_plain
from src.timeutil import format_published


def _hot_source(item: HotTopicSnapshotItem) -> str:
    bits: list[str] = []
    if item.source.strip():
        bits.append(item.source.strip())
    for source in item.sources:
        cleaned = source.strip()
        if cleaned and cleaned not in bits:
            bits.append(cleaned)
    return " · ".join(bits) if bits else "hot_topics"


def _hot_summaries(item: HotTopicSnapshotItem) -> tuple[str, str]:
    summary_en = (item.summary_en or "").strip()
    summary_zh = (item.summary_zh or "").strip()
    fallback = (item.summary or "").strip()
    if not summary_en and fallback and digest_store.has_adhd_summary(fallback):
        if "One-liner" in fallback or "Key takeaways" in fallback:
            summary_en = fallback
    if not summary_zh and fallback and digest_store.has_adhd_summary(fallback):
        if "一句话总结" in fallback or "核心亮点" in fallback:
            summary_zh = fallback
    if not summary_zh and not summary_en and fallback:
        if contains_cjk(fallback):
            summary_zh = fallback
        else:
            summary_en = fallback
    return summary_en, summary_zh


def hot_topic_has_adhd(item: HotTopicSnapshotItem) -> bool:
    summary_en, summary_zh = _hot_summaries(item)
    return digest_store.has_adhd_summary(summary_en) or digest_store.has_adhd_summary(
        summary_zh
    )


def build_hot_topics_url_index(
    hot_path: Path,
) -> dict[str, HotTopicSnapshotItem]:
    snapshot = hot_topics_store.load_snapshot(hot_path)
    return {
        normalize_url(item.url): item for item in snapshot.items if item.url.strip()
    }


def match_hot_topic_for_digest(
    digest_item: digest_store.MergedDigestItem,
    hot_item: HotTopicSnapshotItem | None,
) -> tuple[bool, bool]:
    """按 URL 匹配热搜；返回 (hot_topic_match, can_copy_hot_adhd)。"""
    if hot_item is None:
        return False, False
    digest_has = digest_store.has_adhd_summary(
        digest_item.summary_en
    ) or digest_store.has_adhd_summary(digest_item.summary_zh)
    return True, hot_topic_has_adhd(hot_item) and not digest_has


def _find_digest_item_by_url(
    content_dir: Path,
    day: date,
    url: str,
) -> digest_store.MergedDigestItem | None:
    try:
        view = digest_store.get_day(content_dir, day)
    except FileNotFoundError:
        return None
    key = normalize_url(url)
    for item in view.items:
        if normalize_url(item.url) == key:
            return item
    return None


def copy_hot_topic_to_digest(
    config: AppConfig,
    *,
    day: date | None = None,
    url: str,
) -> dict[str, object]:
    """把热搜条目 upsert 到指定日 Digest；默认 UTC 当日。"""
    hot_path = Path(config.paths.hot_topics_path)
    hot_item = hot_topics_store.find_item(hot_path, url)
    if hot_item is None:
        raise ValueError(f"URL not found in hot topics: {url}")

    target_day = day or datetime.now(timezone.utc).date()
    content_dir = Path(config.paths.content_digests_dir)
    title_en = hot_item.title.strip()
    title_zh = (hot_item.title_zh or "").strip()
    summary_en, summary_zh = _hot_summaries(hot_item)
    score_line = format_score_line(hot_item.score, hot_item.comments) or ""
    published = format_published(hot_item.published_at) if hot_item.published_at else ""
    speak_en = speak_plain(summary_en) if summary_en else ""
    speak_zh = speak_plain(summary_zh) if summary_zh else ""
    source = _hot_source(hot_item)

    existing = _find_digest_item_by_url(content_dir, target_day, hot_item.url)
    if existing is None:
        merged = digest_store.add_item(
            content_dir,
            target_day,
            title_en=title_en,
            title_zh=title_zh,
            url=hot_item.url.strip(),
            source=source,
            published=published,
            score_line=score_line,
            summary_en=summary_en,
            summary_zh=summary_zh,
            speak_en=speak_en,
            speak_zh=speak_zh,
        )
        return {
            "day": target_day.isoformat(),
            "index": merged.index,
            "created": True,
            "url": hot_item.url,
        }

    merged = digest_store.update_item(
        content_dir,
        target_day,
        existing.index,
        title_en=title_en,
        title_zh=title_zh or None,
        source=source,
        published=published or None,
        score_line=score_line or None,
        summary_en=summary_en or None,
        summary_zh=summary_zh or None,
        speak_en=speak_en or None,
        speak_zh=speak_zh or None,
    )
    return {
        "day": target_day.isoformat(),
        "index": merged.index,
        "created": False,
        "url": hot_item.url,
    }
