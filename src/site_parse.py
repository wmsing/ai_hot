"""解析 out/digest*.md（英/中字段标签）为 DigestDocument。"""

from __future__ import annotations

import re

from src.models import DigestDocument, DigestItem

_HEADING_RE = re.compile(r"^##\s+(\d+)\.\s+(.*)\s*$")
_META_RE = re.compile(r"^-\s*([^：:]+)[：:]\s*(.*)\s*$")
_SCORE_LINE_RE = re.compile(r"^-\s*(score=.+)$", re.IGNORECASE)
_SCORE_LINE_ZH_RE = re.compile(r"^-\s*(评分=.+)$")

_FIELD_MAP = {
    "source": "source",
    "url": "url",
    "published": "published",
    "summary": "summary",
    "why": "reason",
    "affiliate": "affiliate_url",
    "image": "image_url",
    "来源": "source",
    "链接": "url",
    "发布时间": "published",
    "摘要": "summary",
    "原因": "reason",
    "联盟链接": "affiliate_url",
    "图片": "image_url",
    "封面": "image_url",
}


def parse_digest_markdown(text: str) -> DigestDocument:
    """容错解析 digest markdown；缺字段时留空。"""
    lines = text.splitlines()
    title = ""
    generated_at = ""
    selected: int | None = None
    items: list[DigestItem] = []
    current: dict[str, str | int] | None = None

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        items.append(
            DigestItem(
                index=int(current["index"]),
                title=str(current.get("title", "")),
                source=_strip_ticks(str(current.get("source", ""))),
                url=str(current.get("url", "")),
                published=str(current.get("published", "")),
                score_line=str(current.get("score_line", "")),
                summary=str(current.get("summary", "")),
                reason=str(current.get("reason", "")),
                affiliate_url=str(current.get("affiliate_url", "")).strip(),
                image_url=str(current.get("image_url", "")).strip(),
            )
        )
        current = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# ") and not line.startswith("## "):
            title = line[2:].strip()
            continue
        if line.lower().startswith("generated (utc):"):
            generated_at = line.split(":", 1)[1].strip()
            continue
        if line.startswith("生成时间"):
            generated_at = line.split("：", 1)[-1].split(":", 1)[-1].strip()
            continue
        if line.lower().startswith("selected:"):
            selected = _parse_int(line.split(":", 1)[1].strip())
            continue
        if line.startswith("精选"):
            selected = _parse_int(line.split("：", 1)[-1].split(":", 1)[-1].strip())
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush()
            current = {
                "index": int(heading.group(1)),
                "title": heading.group(2).strip(),
            }
            continue

        if current is None:
            continue

        score_m = _SCORE_LINE_RE.match(line) or _SCORE_LINE_ZH_RE.match(line)
        if score_m:
            current["score_line"] = score_m.group(1).strip()
            continue

        meta = _META_RE.match(line)
        if not meta:
            continue
        key = meta.group(1).strip()
        value = meta.group(2).strip()
        field = _FIELD_MAP.get(key) or _FIELD_MAP.get(key.lower())
        if field is not None:
            current[field] = value

    flush()
    if selected is None:
        selected = len(items)
    return DigestDocument(
        title=title,
        generated_at=generated_at,
        selected=selected,
        items=items,
    )


def _strip_ticks(value: str) -> str:
    if len(value) >= 2 and value.startswith("`") and value.endswith("`"):
        return value[1:-1]
    return value


def _parse_int(value: str) -> int | None:
    try:
        return int(value.strip())
    except ValueError:
        return None
