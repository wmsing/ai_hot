"""生成给人看的 digest.md（UTC 当日累计）。"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from src.models import DigestItem, HotItem
from src.site_parse import parse_digest_markdown
from src.timeutil import format_published, parse_published

_SCORE_RE = re.compile(
    r"score=(?P<score>n/a|\d+)(?:\s*\|\s*comments=(?P<comments>n/a|\d+))?",
    re.IGNORECASE,
)
_COMMENTS_ONLY_RE = re.compile(r"^comments=(?P<comments>\d+)$", re.IGNORECASE)


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


def write_digest(
    path: str | Path,
    items: list[HotItem],
    *,
    generated_at: datetime,
) -> None:
    """写入 digest（整文件重写；调用方负责当日累计合并）。不写 why。"""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
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
            block.extend(
                [
                    f"- summary: {summary}",
                    "",
                ]
            )
            lines.extend(block)
    out.write_text("\n".join(lines), encoding="utf-8")


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
    if summary.lower() in {"", "n/a"}:
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
        image_url=item.image_url.strip() or None,
        published_at=published_at,
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
