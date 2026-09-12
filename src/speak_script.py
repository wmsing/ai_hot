"""把 DigestDocument 编成口播稿：标题 → 摘要。"""

from __future__ import annotations

from typing import Literal

from src.models import DigestDocument, DigestItem

_END_PUNCT = "。！？；.!?;"
SpeakLang = Literal["en", "zh"]


def _ensure_sentence_end(text: str, *, lang: SpeakLang = "zh") -> str:
    """末尾无句末标点则补句号。"""
    cleaned = text.strip()
    if not cleaned:
        return cleaned
    if cleaned[-1] in _END_PUNCT:
        return cleaned
    return cleaned + ("." if lang == "en" else "。")


def format_item_speak(item: DigestItem, *, lang: SpeakLang = "zh") -> str:
    """单条口播：标题。\\n朗读版优先，否则摘要（可缺）；不读序号。"""
    lines = [_ensure_sentence_end(item.title, lang=lang)]
    body = item.speak_summary.strip() or item.summary.strip()
    if body and body.lower() != "n/a":
        lines.append(_ensure_sentence_end(body, lang=lang))
    return "\n".join(lines)


def format_speak_document(doc: DigestDocument, *, lang: SpeakLang = "zh") -> str:
    """全文口播稿：开场 + 各条（空行分隔）。"""
    n = len(doc.items)
    if lang == "en":
        intro = f"Today's AI highlights: {n} items."
    else:
        intro = f"今日 AI 热点共 {n} 条。"
    blocks = [intro]
    for item in doc.items:
        blocks.append(format_item_speak(item, lang=lang))
    return "\n\n".join(blocks) + ("\n" if blocks else "")
