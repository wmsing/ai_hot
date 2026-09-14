"""热搜 ADHD 逐条落盘与可停止。"""

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


def _save_two_items(snap_path: Path) -> tuple[str, str]:
    from src.hot_topics_probe import save_hot_topics_snapshot

    url_a = "https://example.com/a"
    url_b = "https://example.com/b"
    save_hot_topics_snapshot(
        snap_path,
        [
            (
                9.0,
                HotItem(source="hn", title="Story A", url=url_a, reason="hn"),
            ),
            (
                8.0,
                HotItem(source="hn", title="Story B", url=url_b, reason="hn"),
            ),
        ],
    )
    return url_a, url_b


def test_deep_summarize_hot_topics_persists_before_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src import deep_summarize as mod
    from src.hot_topics_probe import load_hot_topics_snapshot

    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    snap_path = tmp_path / "latest.json"
    url_a, url_b = _save_two_items(snap_path)
    cfg = AppConfig(
        paths=PathsConfig(hot_topics_path=str(snap_path)),
        ollama=OllamaConfig(model="qwen3.5:9b"),
        hot_topics=HotTopicsConfig(deep_summarize_top_n=0),
    )
    runtime = LlmRuntime(
        provider="ollama",
        model="qwen3.5:9b",
        base_url="http://127.0.0.1:11434",
        timeout_seconds=1,
        api_key="",
    )
    adhd_done = 0

    def _fake_fetch(client: object, url: str, *, max_chars: int = 8000) -> str:
        return f"Body for {url}"

    def _fake_chat(*, system: str, user: str, llm: LlmRuntime) -> str:
        nonlocal adhd_done
        if "One line" in system and "Highlights" in system:
            adhd_done += 1
            return "⚡️ One-liner\nSummary.\n\n🔥 Key takeaways\n🚀 ok\n"
        raise AssertionError(f"unexpected prompt: {system[:40]}")

    def _stop_after_first() -> bool:
        return adhd_done >= 1

    _, changed = mod.deep_summarize_hot_topics(
        cfg,
        snapshot_path=snap_path,
        runtime=runtime,
        client=object(),  # type: ignore[arg-type]
        fetch_body=_fake_fetch,
        chat=_fake_chat,
        lang="en",
        should_stop=_stop_after_first,
    )
    assert changed == 1
    loaded = load_hot_topics_snapshot(snap_path)
    assert loaded is not None
    by_url = {item.url: item for item in loaded.items}
    assert "One line" in (by_url[url_a].summary_en or "")
    assert not (by_url[url_b].summary_en or "").strip()
