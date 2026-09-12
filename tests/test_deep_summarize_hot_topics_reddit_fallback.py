"""Reddit 热搜：抓页失败时用 probe summary 直译。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.models import (
    AppConfig,
    HotItem,
    LlmRuntime,
    OllamaConfig,
    PathsConfig,
)


def test_deep_summarize_hot_topics_translates_probe_summary_when_fetch_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src import deep_summarize as mod
    from src.hot_topics_probe import load_hot_topics_snapshot, save_hot_topics_snapshot

    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    snap_path = tmp_path / "latest.json"
    url = "https://www.reddit.com/r/LocalLLaMA/comments/abc/example/"
    blurb = "I made this because LLMs feel too polished and verbose."
    save_hot_topics_snapshot(
        snap_path,
        [
            (
                8.0,
                HotItem(
                    source="reddit:LocalLLaMA",
                    title="Humanlike chat model",
                    url=url,
                    summary=blurb,
                    reason="reddit",
                ),
            )
        ],
    )
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

    def _empty_fetch(client: object, u: str, *, max_chars: int = 8000) -> None:
        return None

    def _fake_chat(*, system: str, user: str, llm: LlmRuntime) -> str:
        if "标题翻译" in system:
            return "类人对话模型"
        if "技术资讯翻译" in system:
            assert user == blurb
            return "我觉得 LLM 太 polished、太 verbose。"
        return "bad output"

    _, n = mod.deep_summarize_hot_topics(
        cfg,
        snapshot_path=snap_path,
        runtime=runtime,
        client=object(),  # type: ignore[arg-type]
        fetch_body=_empty_fetch,
        chat=_fake_chat,
    )
    assert n == 2
    loaded = load_hot_topics_snapshot(snap_path)
    assert loaded is not None
    item = loaded.items[0]
    assert item.title_zh == "类人对话模型"
    assert item.summary_en == blurb
    assert "LLM" in (item.summary_zh or "")
