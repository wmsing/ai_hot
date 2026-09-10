"""生成给人看的 digest.md。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.models import HotItem
from src.timeutil import format_published


def write_digest(
    path: str | Path,
    items: list[HotItem],
    *,
    generated_at: datetime,
) -> None:
    """覆盖写入 digest。"""
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
        lines.append("_No new items passed filters this run._")
        lines.append("")
    else:
        for idx, item in enumerate(items, start=1):
            if item.score is not None:
                score_bit = f"score={item.score}"
            else:
                score_bit = "score=n/a"
            if item.comments is not None:
                comments_bit = f"comments={item.comments}"
            else:
                comments_bit = "comments=n/a"
            summary = item.summary.strip() if item.summary else "n/a"
            lines.extend(
                [
                    f"## {idx}. {item.title}",
                    "",
                    f"- source: `{item.source}`",
                    f"- url: {item.url}",
                    f"- published: {format_published(item.published_at)}",
                    f"- {score_bit} | {comments_bit}",
                    f"- summary: {summary}",
                    f"- why: {item.reason}",
                    "",
                ]
            )
    out.write_text("\n".join(lines), encoding="utf-8")
