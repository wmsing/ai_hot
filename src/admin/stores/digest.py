"""Digest 归档 CRUD（按日 en/zh 配对）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from src.digest import write_digest_preserving_indices
from src.digest_days import day_paths, day_write_paths, list_digest_days
from src.models import DigestDocument, DigestItem
from src.site_parse import parse_digest_markdown
from src.speak_fingerprint import invalidate_archive_item_audio


@dataclass(frozen=True)
class MergedDigestItem:
    index: int
    title_en: str
    title_zh: str
    url: str
    source: str
    published: str
    score_line: str
    summary_en: str
    summary_zh: str
    speak_en: str
    speak_zh: str
    tag: str = ""
    image_url: str = ""


@dataclass(frozen=True)
class DigestDayView:
    day: date
    generated_at: str
    items: list[MergedDigestItem]


def has_adhd_summary(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return False
    markers = (
        "一句话总结",
        "One-liner",
        "🔥 核心亮点",
        "🔥 Key takeaways",
    )
    return any(marker in cleaned for marker in markers)


def list_days(content_dir: Path) -> list[date]:
    return [day_files.day for day_files in list_digest_days(content_dir)]


def _load_doc(path: Path | None) -> DigestDocument | None:
    if path is None or not path.is_file():
        return None
    return parse_digest_markdown(path.read_text(encoding="utf-8"))


def _items_by_index(doc: DigestDocument | None) -> dict[int, DigestItem]:
    if doc is None:
        return {}
    return {item.index: item for item in doc.items}


def _merge_item(
    index: int, en: DigestItem | None, zh: DigestItem | None
) -> MergedDigestItem:
    en_item = en or DigestItem(index=index, title="", url="", source="")
    zh_item = zh or DigestItem(index=index, title="", url="", source="")
    return MergedDigestItem(
        index=index,
        title_en=en_item.title,
        title_zh=zh_item.title,
        url=en_item.url or zh_item.url,
        source=en_item.source or zh_item.source,
        published=en_item.published or zh_item.published,
        score_line=en_item.score_line or zh_item.score_line,
        summary_en=en_item.summary,
        summary_zh=zh_item.summary,
        speak_en=en_item.speak_summary,
        speak_zh=zh_item.speak_summary,
        tag=en_item.tag or zh_item.tag,
        image_url=en_item.image_url or zh_item.image_url,
    )


def get_day(content_dir: Path, day: date) -> DigestDayView:
    paths = day_paths(content_dir, day)
    en_doc = _load_doc(paths.en)
    zh_doc = _load_doc(paths.zh)
    if en_doc is None and zh_doc is None:
        raise FileNotFoundError(f"no digest for {day.isoformat()}")
    generated_at = ""
    if en_doc and en_doc.generated_at.strip():
        generated_at = en_doc.generated_at.strip()
    elif zh_doc and zh_doc.generated_at.strip():
        generated_at = zh_doc.generated_at.strip()
    indices = sorted(set(_items_by_index(en_doc)) | set(_items_by_index(zh_doc)))
    en_map = _items_by_index(en_doc)
    zh_map = _items_by_index(zh_doc)
    items = [_merge_item(idx, en_map.get(idx), zh_map.get(idx)) for idx in indices]
    return DigestDayView(day=day, generated_at=generated_at, items=items)


def _next_index(en_doc: DigestDocument | None, zh_doc: DigestDocument | None) -> int:
    indices = set(_items_by_index(en_doc)) | set(_items_by_index(zh_doc))
    return (max(indices) if indices else 0) + 1


def _write_lang(
    path: Path,
    doc: DigestDocument | None,
    items: list[DigestItem],
    *,
    generated_at: str,
) -> None:
    write_digest_preserving_indices(path, items, generated_at=generated_at)


def add_item(
    content_dir: Path,
    day: date,
    *,
    title_en: str,
    title_zh: str,
    url: str,
    source: str = "manual",
    published: str = "",
    score_line: str = "",
    summary_en: str = "",
    summary_zh: str = "",
    speak_en: str = "",
    speak_zh: str = "",
    tag: str = "",
    image_url: str = "",
) -> MergedDigestItem:
    paths = day_write_paths(content_dir, day)
    en_doc = _load_doc(paths.en)
    zh_doc = _load_doc(paths.zh)
    if en_doc is None and zh_doc is None:
        generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    else:
        generated_at = (
            (en_doc.generated_at if en_doc else "")
            or (zh_doc.generated_at if zh_doc else "")
            or datetime.now(timezone.utc).isoformat(timespec="seconds")
        ).strip()
    index = _next_index(en_doc, zh_doc)
    shared = {
        "url": url,
        "source": source,
        "published": published,
        "score_line": score_line,
        "tag": tag,
        "image_url": image_url,
    }
    en_item = DigestItem(
        index=index,
        title=title_en,
        summary=summary_en,
        speak_summary=speak_en,
        **shared,
    )
    zh_item = DigestItem(
        index=index,
        title=title_zh or title_en,
        summary=summary_zh,
        speak_summary=speak_zh,
        **shared,
    )
    en_items = list(_items_by_index(en_doc).values()) + [en_item]
    zh_items = list(_items_by_index(zh_doc).values()) + [zh_item]
    paths.en.parent.mkdir(parents=True, exist_ok=True)
    _write_lang(paths.en, en_doc, en_items, generated_at=generated_at)
    _write_lang(paths.zh, zh_doc, zh_items, generated_at=generated_at)
    return _merge_item(index, en_item, zh_item)


def update_item(
    content_dir: Path,
    day: date,
    index: int,
    *,
    title_en: str | None = None,
    title_zh: str | None = None,
    url: str | None = None,
    source: str | None = None,
    published: str | None = None,
    score_line: str | None = None,
    summary_en: str | None = None,
    summary_zh: str | None = None,
    speak_en: str | None = None,
    speak_zh: str | None = None,
    tag: str | None = None,
    image_url: str | None = None,
) -> MergedDigestItem:
    paths = day_paths(content_dir, day)
    if paths.en is None and paths.zh is None:
        raise FileNotFoundError(f"no digest for {day.isoformat()}")
    en_doc = _load_doc(paths.en)
    zh_doc = _load_doc(paths.zh)
    en_map = _items_by_index(en_doc)
    zh_map = _items_by_index(zh_doc)
    if index not in en_map and index not in zh_map:
        raise ValueError(f"index not found: {index}")
    generated_at = (
        (en_doc.generated_at if en_doc else "")
        or (zh_doc.generated_at if zh_doc else "")
        or datetime.now(timezone.utc).isoformat(timespec="seconds")
    ).strip()

    def _patch(item: DigestItem, lang: str) -> DigestItem:
        updates: dict[str, str] = {}
        if lang == "en" and title_en is not None:
            updates["title"] = title_en
        if lang == "zh" and title_zh is not None:
            updates["title"] = title_zh
        if url is not None:
            updates["url"] = url
        if source is not None:
            updates["source"] = source
        if published is not None:
            updates["published"] = published
        if score_line is not None:
            updates["score_line"] = score_line
        if lang == "en" and summary_en is not None:
            updates["summary"] = summary_en
        if lang == "zh" and summary_zh is not None:
            updates["summary"] = summary_zh
        if lang == "en" and speak_en is not None:
            updates["speak_summary"] = speak_en
        if lang == "zh" and speak_zh is not None:
            updates["speak_summary"] = speak_zh
        if tag is not None:
            updates["tag"] = tag
        if image_url is not None:
            updates["image_url"] = image_url
        return item.model_copy(update=updates)

    en_item = _patch(
        en_map.get(index, DigestItem(index=index, title="", url="", source="")),
        "en",
    )
    zh_item = _patch(
        zh_map.get(index, DigestItem(index=index, title="", url="", source="")),
        "zh",
    )
    en_map[index] = en_item
    zh_map[index] = zh_item
    write_paths = day_write_paths(content_dir, day)
    if paths.en is not None or en_map:
        _write_lang(
            write_paths.en,
            en_doc,
            sorted(en_map.values(), key=lambda it: it.index),
            generated_at=generated_at,
        )
    if paths.zh is not None or zh_map:
        _write_lang(
            write_paths.zh,
            zh_doc,
            sorted(zh_map.values(), key=lambda it: it.index),
            generated_at=generated_at,
        )
    content_fields = (
        title_en,
        summary_en,
        summary_zh,
        speak_en,
        speak_zh,
    )
    if any(v is not None for v in content_fields):
        invalidate_archive_item_audio(
            content_dir.parent / "audio",
            day=day,
            index=index,
        )
    return _merge_item(index, en_item, zh_item)


def delete_item(content_dir: Path, day: date, index: int) -> None:
    paths = day_paths(content_dir, day)
    if paths.en is None and paths.zh is None:
        raise FileNotFoundError(f"no digest for {day.isoformat()}")
    en_doc = _load_doc(paths.en)
    zh_doc = _load_doc(paths.zh)
    en_map = _items_by_index(en_doc)
    zh_map = _items_by_index(zh_doc)
    if index not in en_map and index not in zh_map:
        raise ValueError(f"index not found: {index}")
    en_map.pop(index, None)
    zh_map.pop(index, None)
    generated_at = (
        (en_doc.generated_at if en_doc else "")
        or (zh_doc.generated_at if zh_doc else "")
        or datetime.now(timezone.utc).isoformat(timespec="seconds")
    ).strip()
    write_paths = day_write_paths(content_dir, day)
    if paths.en is not None:
        _write_lang(
            write_paths.en,
            en_doc,
            sorted(en_map.values(), key=lambda it: it.index),
            generated_at=generated_at,
        )
    if paths.zh is not None:
        _write_lang(
            write_paths.zh,
            zh_doc,
            sorted(zh_map.values(), key=lambda it: it.index),
            generated_at=generated_at,
        )


def item_url(content_dir: Path, day: date, index: int) -> str:
    view = get_day(content_dir, day)
    for item in view.items:
        if item.index == index:
            if not item.url.strip():
                raise ValueError(f"item {index} has no url")
            return item.url
    raise ValueError(f"index not found: {index}")
