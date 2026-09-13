"""热搜标题批量翻译。"""

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


def test_translate_hot_topic_titles_updates_missing_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src import deep_summarize as mod
    from src.hot_topics_probe import load_hot_topics_snapshot, save_hot_topics_snapshot

    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    snap_path = tmp_path / "latest.json"
    save_hot_topics_snapshot(
        snap_path,
        [
            (
                9.0,
                HotItem(
                    source="hn",
                    title="Needs translation",
                    url="https://example.com/a",
                    reason="hn",
                ),
            ),
            (
                8.0,
                HotItem(
                    source="hn",
                    title="已有中文",
                    url="https://example.com/b",
                    reason="hn",
                ),
            ),
        ],
    )
    loaded = load_hot_topics_snapshot(snap_path)
    assert loaded is not None
    loaded.items[1] = loaded.items[1].model_copy(update={"title_zh": "已有中文"})
    snap_path.write_text(loaded.model_dump_json(indent=2), encoding="utf-8")

    cfg = AppConfig(
        paths=PathsConfig(hot_topics_path=str(snap_path)),
        ollama=OllamaConfig(model="qwen3.5:9b"),
        hot_topics=HotTopicsConfig(),
    )
    runtime = LlmRuntime(
        provider="ollama",
        model="qwen3.5:9b",
        base_url="http://127.0.0.1:11434",
        timeout_seconds=1,
        api_key="",
    )

    def _fake_chat(*, system: str, user: str, llm: LlmRuntime) -> str:
        assert "标题翻译" in system
        if user == "Needs translation":
            return "需要翻译"
        raise AssertionError(f"unexpected title: {user}")

    out_path, changed = mod.translate_hot_topic_titles(
        cfg,
        snapshot_path=snap_path,
        runtime=runtime,
        chat=_fake_chat,
    )
    assert changed == 1
    assert out_path == snap_path
    after = load_hot_topics_snapshot(snap_path)
    assert after is not None
    assert after.items[0].title_zh == "需要翻译"
    assert after.items[1].title_zh == "已有中文"
