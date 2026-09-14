"""ADHD 摘要结构整理（不截断正文）。"""

from __future__ import annotations

from src.deep_summarize import (
    _retidy_existing_adhd_pair,
    is_adhd_summary,
    tidy_adhd_summary,
)
from src.models import HotItem


def test_tidy_splits_inline_highlights_header() -> None:
    raw = (
        "⚡️ 一句话总结\n"
        "⚡️ 北卡罗来纳大学获资助。 🔥 核心亮点 团队将开发自适应 AI。\n\n"
        "🔥 核心亮点\n"
        "🚀 第一条\n"
        "📐 第二条\n"
    )
    out = tidy_adhd_summary(raw, lang="zh")
    assert out.startswith("一句话\n")
    assert "\n\n亮点\n" in out
    assert "团队将开发自适应 AI" in out
    assert "…" not in out
    assert is_adhd_summary(out, lang="zh")


def test_tidy_preserves_long_text() -> None:
    long_one = "字" * 120
    raw = f"⚡️ 一句话总结\n{long_one}\n\n🔥 核心亮点\n✅ ok\n"
    out = tidy_adhd_summary(raw, lang="zh")
    assert long_one in out
    assert "…" not in out


def test_tidy_strips_emoji_from_bullets() -> None:
    raw = (
        "一句话\n"
        "北卡获资助。\n\n"
        "亮点\n"
        "🚀 第一条\n"
        "📐 第二条\n"
        "🧪 第三条\n"
    )
    out = tidy_adhd_summary(raw, lang="zh")
    assert "🚀" not in out
    assert "第一条" in out


def test_retidy_existing_pair_strips_emoji() -> None:
    zh_old = (
        "⚡️ 一句话总结\n"
        "商汤获双 5A 认证🏆。\n\n"
        "🔥 核心亮点\n"
        "✅ 第一条 🚀\n"
        "✅ 第二条\n"
        "✅ 第三条\n"
    )
    en = HotItem(source="rss:x", title="EN", url="https://example.com/a", summary="plain")
    zh = HotItem(source="rss:x", title="ZH", url="https://example.com/a", summary=zh_old)
    pair = _retidy_existing_adhd_pair(en, zh)
    assert pair is not None
    assert pair[1] is not None
    assert "🏆" not in pair[1]
    assert "🚀" not in pair[1]
    assert pair[1].startswith("一句话\n")


def test_tidy_en_canonical_headings() -> None:
    raw = (
        "⚡️ One-liner\n"
        "NSF funds adaptive STEM tools.\n\n"
        "🔥 Key takeaways\n"
        "🚀 First\n"
        "📐 Second\n"
        "🧪 Third\n"
    )
    out = tidy_adhd_summary(raw, lang="en")
    assert out.startswith("One line\n")
    assert "\n\nHighlights\n" in out
    assert is_adhd_summary(out, lang="en")
