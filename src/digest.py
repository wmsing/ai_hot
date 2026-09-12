"""生成给人看的 digest.md（UTC 当日累计）。"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from src.models import DigestItem, HotItem
from src.ollama_client import is_junk_summary
from src.site_parse import parse_digest_markdown
from src.timeutil import format_published, parse_published

_SCORE_RE = re.compile(
    r"score=(?P<score>n/a|\d+)(?:\s*\|\s*comments=(?P<comments>n/a|\d+))?",
    re.IGNORECASE,
)
_COMMENTS_ONLY_RE = re.compile(r"^comments=(?P<comments>\d+)$", re.IGNORECASE)

_EMPTY_SUMMARIES = frozenset(
    {
        "",
        "n/a",
        "(none)",
        "none",
        "无内容",
        "暂无",
        "暂无内容",
        "无",
    }
)


def has_usable_digest_summary(summary: str | None, *, title: str = "") -> bool:
    """是否有可收录/展示的摘要（空、n/a、无内容、junk 均否）。"""
    cleaned = " ".join((summary or "").split()).strip()
    if cleaned.casefold() in _EMPTY_SUMMARIES:
        return False
    if cleaned in {"无内容", "暂无", "暂无内容", "无"}:
        return False
    if is_junk_summary(cleaned, title=title):
        return False
    return True


def same_utc_day(generated_at: datetime, now: datetime) -> bool:
    """是否同属一个 UTC 日历日。"""
    a = generated_at.astimezone(timezone.utc).date()
    b = now.astimezone(timezone.utc).date()
    return a == b


def merge_by_url(existing: list[HotItem], new: list[HotItem]) -> list[HotItem]:
    """保序合并：已有在前，新 URL 追加；重复 URL 跳过。"""
    seen = {item.url for item in existing}
    out = list(existing)
    for item in new:
        if item.url in seen:
            continue
        seen.add(item.url)
        out.append(item)
    return out


def load_hot_items(path: str | Path) -> tuple[datetime | None, list[HotItem]]:
    """从已有 digest.md 解析 (generated_at, items)；文件不存在或无法解析则空。"""
    out = Path(path)
    if not out.is_file():
        return None, []
    text = out.read_text(encoding="utf-8")
    if not text.strip():
        return None, []
    return parse_hot_items(text)


def parse_hot_items(text: str) -> tuple[datetime | None, list[HotItem]]:
    """从 digest Markdown 文本解析 (generated_at, items)。"""
    if not text.strip():
        return None, []
    doc = parse_digest_markdown(text)
    generated_at = _parse_generated_at(doc.generated_at)
    items = [_digest_item_to_hot(item) for item in doc.items]
    return generated_at, items


def format_score_line(score: int | None, comments: int | None) -> str | None:
    """有分数/评论才返回展示行；全空则 None。"""
    bits: list[str] = []
    if score is not None:
        bits.append(f"score={score}")
    if comments is not None:
        bits.append(f"comments={comments}")
    if not bits:
        return None
    return " | ".join(bits)


def format_digest_markdown(
    items: list[HotItem],
    *,
    generated_at: datetime,
) -> str:
    """格式化 digest Markdown（不写盘）。"""
    lines = [
        "# ai_hot digest",
        "",
        f"Generated (UTC): {generated_at.isoformat(timespec='seconds')}",
        f"Selected: {len(items)}",
        "",
    ]
    if not items:
        lines.append("_No items for this UTC day yet._")
        lines.append("")
    else:
        for idx, item in enumerate(items, start=1):
            summary = item.summary.strip() if item.summary else "n/a"
            block = [
                f"## {idx}. {item.title}",
                "",
                f"- source: `{item.source}`",
                f"- url: {item.url}",
            ]
            published = format_published(item.published_at)
            if published != "n/a":
                block.append(f"- published: {published}")
            score_line = format_score_line(item.score, item.comments)
            if score_line is not None:
                block.append(f"- {score_line}")
            if item.image_url and item.image_url.strip():
                block.append(f"- image: {item.image_url.strip()}")
            tag = (item.tag or "").strip()
            if tag:
                block.append(f"- tag: {tag}")
            _extend_field(block, "summary", summary)
            speak = (item.speak_summary or "").strip()
            if speak:
                _extend_field(block, "speak", speak)
            block.append("")
            lines.extend(block)
    return "\n".join(lines)


def _extend_field(block: list[str], key: str, value: str) -> None:
    """写入可能多行的 - key: 字段（首行带键，续行无前缀）。"""
    parts = value.splitlines() or [""]
    block.append(f"- {key}: {parts[0]}")
    for cont in parts[1:]:
        block.append(cont)


def write_digest(
    path: str | Path,
    items: list[HotItem],
    *,
    generated_at: datetime,
) -> None:
    """写入 digest（整文件重写；调用方负责当日累计合并）。不写 why。"""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        format_digest_markdown(items, generated_at=generated_at),
        encoding="utf-8",
    )


def write_digest_preserving_indices(
    path: str | Path,
    items: list[DigestItem],
    *,
    generated_at: str,
) -> None:
    """按 DigestItem.index 写回（可留号洞），避免打乱已有口播序号。"""
    lines = [
        "# ai_hot digest",
        "",
        f"Generated (UTC): {generated_at}",
        f"Selected: {len(items)}",
        "",
    ]
    if not items:
        lines.append("_No items for this UTC day yet._")
        lines.append("")
    else:
        for item in items:
            summary = item.summary.strip() if item.summary else "n/a"
            block = [
                f"## {item.index}. {item.title}",
                "",
                f"- source: `{item.source}`",
                f"- url: {item.url}",
            ]
            if item.published.strip():
                block.append(f"- published: {item.published.strip()}")
            if item.score_line.strip():
                block.append(f"- {item.score_line.strip()}")
            if item.image_url.strip():
                block.append(f"- image: {item.image_url.strip()}")
            if item.tag.strip():
                block.append(f"- tag: {item.tag.strip()}")
            _extend_field(block, "summary", summary)
            speak = item.speak_summary.strip()
            if speak:
                _extend_field(block, "speak", speak)
            block.append("")
            lines.extend(block)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")


def prune_empty_summaries(path: str | Path) -> int:
    """从已有 digest 去掉无可用摘要条目；保留原序号。返回删除条数。"""
    out = Path(path)
    if not out.is_file():
        return 0
    doc = parse_digest_markdown(out.read_text(encoding="utf-8"))
    kept = [
        item
        for item in doc.items
        if has_usable_digest_summary(item.summary, title=item.title)
    ]
    dropped = len(doc.items) - len(kept)
    if dropped <= 0:
        return 0
    generated = doc.generated_at.strip() or datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )
    write_digest_preserving_indices(out, kept, generated_at=generated)
    return dropped


def _parse_generated_at(raw: str) -> datetime | None:
    text = raw.strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _digest_item_to_hot(item: DigestItem) -> HotItem:
    score, comments = _parse_score_line(item.score_line)
    published_at = parse_published(item.published)
    summary = item.summary.strip()
    cleaned = " ".join(summary.split()).strip()
    # 占位空摘要清空；junk 原文保留，供 resummarize 识别重写
    if cleaned.casefold() in _EMPTY_SUMMARIES:
        summary_out: str | None = None
    else:
        summary_out = summary
    return HotItem(
        source=item.source,
        title=item.title,
        url=item.url,
        score=score,
        comments=comments,
        summary=summary_out,
        speak_summary=item.speak_summary.strip() or None,
        image_url=item.image_url.strip() or None,
        published_at=published_at,
        tag=(item.tag or "").strip(),
        reason=item.reason,
    )


def _parse_score_line(raw: str) -> tuple[int | None, int | None]:
    text = raw.strip()
    if not text:
        return None, None
    match = _SCORE_RE.search(text)
    if match:
        score_s = match.group("score")
        comments_s = match.group("comments")
        score = None if score_s is None or score_s.lower() == "n/a" else int(score_s)
        comments = (
            None
            if comments_s is None or comments_s.lower() == "n/a"
            else int(comments_s)
        )
        return score, comments
    only = _COMMENTS_ONLY_RE.match(text)
    if only:
        return None, int(only.group("comments"))
    return None, None
