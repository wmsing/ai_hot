"""speak_script 口播文案单测。"""

from __future__ import annotations

from src.models import DigestDocument, DigestItem
from src.speak_script import format_item_speak, format_speak_document


def test_format_item_speak_with_summary() -> None:
    item = DigestItem(
        index=1,
        title="OpenAI Agents API",
        summary="开发者可构建自主代理应用",
    )
    text = format_item_speak(item)
    assert text == "OpenAI Agents API。\n开发者可构建自主代理应用。"
    assert "第" not in text


def test_format_item_speak_skips_empty_and_na_summary() -> None:
    empty = DigestItem(index=2, title="已有句号。", summary="")
    assert format_item_speak(empty) == "已有句号。"
    na = DigestItem(index=3, title="标题", summary="n/a")
    assert format_item_speak(na) == "标题。"


def test_format_speak_document_intro_and_gaps() -> None:
    doc = DigestDocument(
        items=[
            DigestItem(index=1, title="甲", summary="摘要甲"),
            DigestItem(index=2, title="乙。", summary="摘要乙"),
        ]
    )
    text = format_speak_document(doc)
    assert text.startswith("今日 AI 热点共 2 条。\n\n")
    assert "甲。\n摘要甲。" in text
    assert "乙。\n摘要乙。" in text
    assert "第1条" not in text
    assert text.endswith("\n")
