"""把 DigestDocument 编成口播稿：标题 → 摘要。"""

from __future__ import annotations

from src.models import DigestDocument, DigestItem

_END_PUNCT = "。！？；.!?;"


def _ensure_sentence_end(text: str) -> str:
    """末尾无句末标点则补「。」。"""
    cleaned = text.strip()
    if not cleaned:
        return cleaned
    if cleaned[-1] in _END_PUNCT:
        return cleaned
    return cleaned + "。"


def format_item_speak(item: DigestItem) -> str:
    """单条口播：标题。\\n摘要（可缺）；不读序号。"""
    lines = [_ensure_sentence_end(item.title)]
    summary = item.summary.strip()
    if summary and summary.lower() != "n/a":
        lines.append(_ensure_sentence_end(summary))
    return "\n".join(lines)


def format_speak_document(doc: DigestDocument) -> str:
    """全文口播稿：开场 + 各条（空行分隔）。"""
    n = len(doc.items)
    blocks = [f"今日 AI 热点共 {n} 条。"]
    for item in doc.items:
        blocks.append(format_item_speak(item))
    return "\n\n".join(blocks) + ("\n" if blocks else "")
