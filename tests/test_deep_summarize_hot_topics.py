"""deep_summarize 对热搜快照的 ADHD 精写。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.models import (
    AppConfig,
    HotItem,
    HotTopicsConfig,
    LlmRuntime,
    OllamaConfig,
    PathsConfig,
)


def test_hot_topic_has_adhd_summary_accepts_translated_probe_summary() -> None:
    from src.deep_summarize import _hot_topic_has_adhd_summary
    from src.models import HotTopicSnapshotItem

    item = HotTopicSnapshotItem(
        heat=1.0,
        source="reddit:LocalLLaMA",
        title="Example",
        url="https://example.com/x",
        summary_en="English blurb about a model.",
        summary_zh="关于模型的一段中文简介。",
    )
    assert _hot_topic_has_adhd_summary(item) is True


def test_hot_topic_summary_translate_fallback() -> None:
    from src.deep_summarize import _hot_topic_summary_translate_fallback
    from src.models import HotTopicSnapshotItem, LlmRuntime

    runtime = LlmRuntime(
        provider="ollama",
        model="test",
        base_url="http://127.0.0.1:11434",
        timeout_seconds=1,
        api_key="",
    )
    item = HotTopicSnapshotItem(
        heat=1.0,
        source="reddit:LocalLLaMA",
        title="Example",
        url="https://example.com/x",
        summary="I made this because LLMs feel too polished.",
    )

    def _fake_chat(*, system: str, user: str, llm: LlmRuntime) -> str:
        assert "技术资讯翻译" in system
        return "我觉得 LLM 太 polished 了。"

    out = _hot_topic_summary_translate_fallback(item, runtime, chat=_fake_chat)
    assert out is not None
    assert out["summary_en"] == item.summary
    assert "LLM" in out["summary_zh"]


def test_summarize_adhd_pair_uses_fallback_body() -> None:
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

    def _empty_fetch(client: object, url: str, *, max_chars: int = 8000) -> None:
        return None

    def _fake_chat(*, system: str, user: str, llm: LlmRuntime) -> str:
        calls.append(system)
        if "核心亮点" in system:
            return "⚡️ 一句话总结\nReddit 帖总结。\n\n🔥 核心亮点\n✅ ok\n"
        return "⚡️ One-liner\nReddit post summary.\n\n🔥 Key takeaways\n✅ ok\n"

    pair = mod.summarize_adhd_pair(
        title="Reddit post",
        url="https://www.reddit.com/r/test/comments/abc/x/",
        source="reddit:test",
        llm=runtime,
        http=object(),  # type: ignore[arg-type]
        fetch_body=_empty_fetch,
        chat=_fake_chat,
        fallback_body="Reddit selftext about the model release.",
    )
    assert pair is not None
    assert "一句话总结" in pair[1]
    assert len(calls) == 2


def test_deep_summarize_hot_topics_updates_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src import deep_summarize as mod
    from src.hot_topics_probe import load_hot_topics_snapshot, save_hot_topics_snapshot

    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    snap_path = tmp_path / "latest.json"
    url = "https://example.com/hot"
    save_hot_topics_snapshot(
        snap_path,
        [
            (
                9.0,
                HotItem(
                    source="hn",
                    title="Hot AI story",
                    url=url,
                    score=500,
                    comments=100,
                    reason="hn",
                ),
            )
        ],
    )
    cfg = AppConfig(
        paths=PathsConfig(hot_topics_path=str(snap_path)),
        ollama=OllamaConfig(model="qwen3.5:9b"),
        hot_topics=HotTopicsConfig(deep_summarize_top_n=3),
    )
    runtime = LlmRuntime(
        provider="ollama",
        model="qwen3.5:9b",
        base_url="http://127.0.0.1:11434",
        timeout_seconds=1,
        api_key="",
    )

    def _fake_fetch(client: object, u: str, *, max_chars: int = 8000) -> str:
        assert u == url
        return "Article about a new LLM benchmark. " * 20

    def _fake_chat(*, system: str, user: str, llm: LlmRuntime) -> str:
        if "标题翻译" in system:
            return "热榜 AI 故事"
        if "技术资讯翻译" in system:
            return "关于新模型刷榜的中文简介。"
        if "核心亮点" in system:
            return "⚡️ 一句话总结\n新模型刷榜。\n\n🔥 核心亮点\n🚀 分数更高\n"
        return (
            "⚡️ One-liner\nA new model tops the chart.\n\n"
            "🔥 Key takeaways\n🚀 Higher score\n"
        )

    out_path, n = mod.deep_summarize_hot_topics(
        cfg,
        snapshot_path=snap_path,
        runtime=runtime,
        client=object(),  # type: ignore[arg-type]
        fetch_body=_fake_fetch,
        chat=_fake_chat,
    )
    assert n == 2
    assert out_path == snap_path
    loaded = load_hot_topics_snapshot(snap_path)
    assert loaded is not None
    assert loaded.items[0].summary_zh is not None
    assert "一句话总结" in loaded.items[0].summary_zh
    assert loaded.items[0].summary_en is not None
    assert "One-liner" in loaded.items[0].summary_en
    assert loaded.items[0].title_zh == "热榜 AI 故事"
    assert loaded.items[0].title_zh != "新模型刷榜。"


def test_translate_title_to_zh_skips_cjk() -> None:
    from src.deep_summarize import translate_title_to_zh
    from src.models import LlmRuntime

    runtime = LlmRuntime(
        provider="ollama",
        model="test",
        base_url="http://127.0.0.1:11434",
        timeout_seconds=1,
        api_key="",
    )

    def _fail_chat(**kwargs: object) -> str:
        raise AssertionError("chat should not run for CJK title")

    assert (
        translate_title_to_zh("已是中文标题", runtime, chat=_fail_chat)
        == "已是中文标题"
    )


def test_hot_topic_needs_title_zh_detects_legacy_one_liner() -> None:
    from src.deep_summarize import _hot_topic_needs_title_zh
    from src.models import HotTopicSnapshotItem

    summary_zh = "⚡️ 一句话总结\n新模型刷榜。\n\n🔥 核心亮点\n🚀 分数更高\n"
    legacy = HotTopicSnapshotItem(
        heat=1.0,
        source="hn",
        title="Hot AI story",
        url="https://example.com/hot",
        summary_zh=summary_zh,
        title_zh="新模型刷榜。",
    )
    fixed = legacy.model_copy(update={"title_zh": "热榜 AI 故事"})
    assert _hot_topic_needs_title_zh(legacy) is True
    assert _hot_topic_needs_title_zh(fixed) is False


def test_extract_adhd_one_liner() -> None:
    from src.deep_summarize import extract_adhd_one_liner

    zh = "⚡️ 一句话总结\nAI 数学对齐问题。\n\n🔥 核心亮点\n📐 证明缺口\n"
    assert extract_adhd_one_liner(zh, lang="zh") == "AI 数学对齐问题。"
    en = "⚡️ One-liner\nAI math gap.\n\n🔥 Key takeaways\n📐 Proof issues\n"
    assert extract_adhd_one_liner(en, lang="en") == "AI math gap."


def test_deep_summarize_hot_topics_skips_already_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src import deep_summarize as mod
    from src.hot_topics_probe import load_hot_topics_snapshot, save_hot_topics_snapshot

    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    snap_path = tmp_path / "latest.json"
    url_done = "https://example.com/done"
    url_new = "https://example.com/new"
    save_hot_topics_snapshot(
        snap_path,
        [
            (9.0, HotItem(source="hn", title="Done", url=url_done, reason="hn")),
            (8.0, HotItem(source="hn", title="New", url=url_new, reason="hn")),
        ],
    )
    loaded = load_hot_topics_snapshot(snap_path)
    assert loaded is not None
    done_en = "⚡️ One-liner\nDone.\n\n🔥 Key takeaways\n✅ ok\n"
    done_zh = "⚡️ 一句话总结\n已完成。\n\n🔥 核心亮点\n✅ ok\n"
    loaded = loaded.model_copy(
        update={
            "items": [
                loaded.items[0].model_copy(
                    update={
                        "summary_en": done_en,
                        "summary_zh": done_zh,
                    }
                ),
                loaded.items[1],
            ]
        }
    )
    snap_path.write_text(loaded.model_dump_json(indent=2), encoding="utf-8")

    cfg = AppConfig(
        paths=PathsConfig(hot_topics_path=str(snap_path)),
        ollama=OllamaConfig(model="qwen3.5:9b"),
    )
    runtime = LlmRuntime(
        provider="ollama",
        model="qwen3.5:9b",
        base_url="http://127.0.0.1:11434",
        timeout_seconds=1,
        api_key="",
    )
    calls: list[str] = []

    def _fake_fetch(client: object, u: str, *, max_chars: int = 8000) -> str:
        calls.append(u)
        return "Body " * 50

    def _fake_chat(*, system: str, user: str, llm: LlmRuntime) -> str:
        if "标题翻译" in system:
            return "已完成" if user == "Done" else "新条目标题"
        if "核心亮点" in system:
            return "⚡️ 一句话总结\n新条目。\n\n🔥 核心亮点\n🆕 new\n"
        return "⚡️ One-liner\nNew item.\n\n🔥 Key takeaways\n🆕 new\n"

    _, n = mod.deep_summarize_hot_topics(
        cfg,
        snapshot_path=snap_path,
        runtime=runtime,
        client=object(),  # type: ignore[arg-type]
        fetch_body=_fake_fetch,
        chat=_fake_chat,
    )
    assert n == 3
    assert calls == [url_new]
    again_path, again_n = mod.deep_summarize_hot_topics(
        cfg,
        snapshot_path=snap_path,
        runtime=runtime,
        client=object(),  # type: ignore[arg-type]
        fetch_body=_fake_fetch,
        chat=_fake_chat,
    )
    assert again_n == 0
    assert again_path == snap_path


def test_save_hot_topics_snapshot_preserves_summaries(tmp_path: Path) -> None:
    from src.hot_topics_probe import load_hot_topics_snapshot, save_hot_topics_snapshot

    snap_path = tmp_path / "latest.json"
    url = "https://example.com/keep"
    save_hot_topics_snapshot(
        snap_path,
        [(9.0, HotItem(source="hn", title="Old title", url=url, reason="hn"))],
    )
    loaded = load_hot_topics_snapshot(snap_path)
    assert loaded is not None
    kept_en = "⚡️ One-liner\nKept.\n\n🔥 Key takeaways\n💾 save\n"
    kept_zh = "⚡️ 一句话总结\n保留。\n\n🔥 核心亮点\n💾 留存\n"
    loaded = loaded.model_copy(
        update={
            "items": [
                loaded.items[0].model_copy(
                    update={
                        "summary_en": kept_en,
                        "summary_zh": kept_zh,
                        "title_zh": "保留。",
                    }
                )
            ]
        }
    )
    snap_path.write_text(loaded.model_dump_json(indent=2), encoding="utf-8")

    save_hot_topics_snapshot(
        snap_path,
        [(8.5, HotItem(source="hn", title="New title", url=url, reason="hn"))],
    )
    merged = load_hot_topics_snapshot(snap_path)
    assert merged is not None
    assert merged.items[0].title == "New title"
    assert merged.items[0].heat == 8.5
    assert merged.items[0].summary_en is not None
    assert "One-liner" in merged.items[0].summary_en
    assert merged.items[0].summary_zh is not None
    assert "一句话总结" in merged.items[0].summary_zh
    assert merged.items[0].title_zh == "保留。"
