"""Digest 标题批量翻译。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.models import AppConfig, LlmRuntime, OllamaConfig, PathsConfig


def test_translate_digest_day_titles_updates_missing_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.admin.services.translate import translate_digest_day_titles
    from src.admin.stores import digest as digest_store

    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    digests_dir = tmp_path / "digests"
    digests_dir.mkdir(parents=True)
    day = date(2026, 9, 13)
    digest_store.add_item(
        digests_dir,
        day,
        title_en="Needs translation",
        title_zh="",
        url="https://example.com/a",
        source="manual",
    )
    digest_store.add_item(
        digests_dir,
        day,
        title_en="Already done",
        title_zh="已有中文",
        url="https://example.com/b",
        source="manual",
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

    def _fake_translate(title: str, llm: LlmRuntime, chat=None) -> str:
        if title == "Needs translation":
            return "需要翻译"
        raise AssertionError(f"unexpected title: {title}")

    monkeypatch.setattr(
        "src.admin.services.translate.resolve_provider",
        lambda llm_flag, config: "ollama",
    )
    monkeypatch.setattr(
        "src.admin.services.translate.build_llm_runtime",
        lambda *args, **kwargs: runtime,
    )
    monkeypatch.setattr(
        "src.admin.services.translate.translate_title_to_zh",
        _fake_translate,
    )

    result = translate_digest_day_titles(cfg, day=day)
    assert result["changed"] == 1
    view = digest_store.get_day(digests_dir, day)
    by_url = {item.url: item for item in view.items}
    assert by_url["https://example.com/a"].title_zh == "需要翻译"
    assert by_url["https://example.com/b"].title_zh == "已有中文"
