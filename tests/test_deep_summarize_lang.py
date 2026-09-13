"""ADHD 按语种生成。"""

from __future__ import annotations

from src.models import HotTopicSnapshotItem


def test_hot_topic_needs_adhd_respects_lang() -> None:
    from src.deep_summarize import (
        _hot_topic_has_adhd_en,
        _hot_topic_has_adhd_zh,
        _hot_topic_needs_adhd,
    )

    item = HotTopicSnapshotItem(
        heat=1.0,
        source="hn",
        title="Example",
        url="https://example.com/x",
        summary_zh="⚡️ 一句话总结\n测试\n\n🔥 核心亮点\n✅ ok\n",
        summary_en="",
    )
    assert _hot_topic_has_adhd_zh(item) is True
    assert _hot_topic_has_adhd_en(item) is False
    assert _hot_topic_needs_adhd(item, "zh", force=False) is False
    assert _hot_topic_needs_adhd(item, "en", force=False) is True


def test_summarize_adhd_pair_zh_only() -> None:
    from src import deep_summarize as mod
    from src.models import LlmRuntime

    runtime = LlmRuntime(
        provider="ollama",
        model="test",
        base_url="http://127.0.0.1:11434",
        timeout_seconds=1,
        api_key="",
    )
    calls: list[str] = []

    def _fake_fetch(client: object, url: str, *, max_chars: int = 8000) -> str:
        return "Article body about a new model release."

    def _fake_chat(*, system: str, user: str, llm: LlmRuntime) -> str:
        calls.append(system)
        if "核心亮点" in system:
            return "⚡️ 一句话总结\n中文摘要。\n\n🔥 核心亮点\n✅ ok\n"
        raise AssertionError("EN prompt should not run for lang=zh")

    pair = mod.summarize_adhd_pair(
        title="Title",
        url="https://example.com/x",
        source="hn",
        llm=runtime,
        http=object(),  # type: ignore[arg-type]
        fetch_body=_fake_fetch,
        chat=_fake_chat,
        lang="zh",
    )
    assert pair[0] is None
    assert "中文摘要" in (pair[1] or "")
    assert len(calls) == 1
