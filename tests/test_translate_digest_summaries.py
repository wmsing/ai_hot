"""Digest 摘要批量翻译。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.models import AppConfig, LlmRuntime, OllamaConfig, PathsConfig


def test_translate_digest_day_summaries_updates_missing_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.admin.services.translate import translate_digest_day_summaries
    from src.admin.stores import digest as digest_store

    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    digests_dir = tmp_path / "digests"
    digests_dir.mkdir(parents=True)
    day = date(2026, 9, 13)
    digest_store.add_item(
        digests_dir,
        day,
        title_en="Item A",
        title_zh="条目 A",
        url="https://example.com/a",
        source="manual",
        summary_en="Needs translation",
        summary_zh="",
    )
    digest_store.add_item(
        digests_dir,
        day,
        title_en="Item B",
        title_zh="条目 B",
        url="https://example.com/b",
        source="manual",
        summary_en="Already done",
        summary_zh="已有中文摘要",
    )
    cfg = AppConfig(
        paths=PathsConfig(content_digests_dir=str(digests_dir)),
        ollama=OllamaConfig(model="qwen3.5:9b"),
    )
    runtime = LlmRuntime(
        provider="ollama",
        model="qwen3.5:9b",
        base_url="http://127.0.0.1:11434",
        timeout_seconds=1,
        api_key="",
    )

    def _fake_translate(summary: str, llm: LlmRuntime, chat=None) -> str:
        if summary == "Needs translation":
            return "需要翻译"
        raise AssertionError(f"unexpected summary: {summary}")

    monkeypatch.setattr(
        "src.admin.services.translate.resolve_provider",
        lambda llm_flag, config: "ollama",
    )
    monkeypatch.setattr(
        "src.admin.services.translate.build_llm_runtime",
        lambda *args, **kwargs: runtime,
    )
    monkeypatch.setattr(
        "src.admin.services.translate.translate_summary_to_zh",
        _fake_translate,
    )

    result = translate_digest_day_summaries(cfg, day=day)
    assert result["changed"] == 1
    view = digest_store.get_day(digests_dir, day)
    by_url = {item.url: item for item in view.items}
    assert by_url["https://example.com/a"].summary_zh == "需要翻译"
    assert by_url["https://example.com/b"].summary_zh == "已有中文摘要"
