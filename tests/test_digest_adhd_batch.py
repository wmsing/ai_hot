"""Digest ADHD 批量生成逐条落盘。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.models import AppConfig, PathsConfig


def test_generate_digest_adhd_batch_runs_per_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.admin.services.adhd import generate_digest_adhd_batch
    from src.admin.stores import digest as digest_store

    digests_dir = tmp_path / "digests"
    digests_dir.mkdir(parents=True)
    day = date(2026, 9, 13)
    first = digest_store.add_item(
        digests_dir,
        day,
        title_en="First",
        title_zh="第一条",
        url="https://example.com/a",
        source="manual",
        summary_en="old en a",
        summary_zh="旧摘要 A",
    )
    second = digest_store.add_item(
        digests_dir,
        day,
        title_en="Second",
        title_zh="第二条",
        url="https://example.com/b",
        source="manual",
        summary_en="old en b",
        summary_zh="旧摘要 B",
    )
    cfg = AppConfig(paths=PathsConfig(content_digests_dir=str(digests_dir)))
    calls: list[str] = []
    invalidated: list[int] = []

    def _fake_deep_summarize(
        config: AppConfig,
        *,
        urls: list[str],
        input_path: str | Path | None = None,
        input_zh_path: str | Path | None = None,
        llm_flag: str | None = None,
        should_stop=None,
    ) -> tuple[Path, Path, int, str | None]:
        calls.extend(urls)
        return Path(input_path or ""), Path(input_zh_path or ""), 1, "llm"

    def _fake_invalidate(
        config: AppConfig,
        *,
        day: date,
        indices: list[int],
    ) -> None:
        invalidated.extend(indices)

    monkeypatch.setattr(
        "src.admin.services.adhd.deep_summarize_digest",
        _fake_deep_summarize,
    )
    monkeypatch.setattr(
        "src.admin.services.adhd.invalidate_digest_audio",
        _fake_invalidate,
    )

    result = generate_digest_adhd_batch(
        cfg,
        day=day,
        indices=[first.index, second.index],
    )
    assert result["changed"] == 2
    assert calls == ["https://example.com/a", "https://example.com/b"]
    assert invalidated == [first.index, second.index]


def test_generate_digest_adhd_batch_stops_between_urls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.admin.services.adhd import generate_digest_adhd_batch
    from src.admin.stores import digest as digest_store

    digests_dir = tmp_path / "digests"
    digests_dir.mkdir(parents=True)
    day = date(2026, 9, 13)
    first = digest_store.add_item(
        digests_dir,
        day,
        title_en="First",
        title_zh="第一条",
        url="https://example.com/a",
        source="manual",
    )
    second = digest_store.add_item(
        digests_dir,
        day,
        title_en="Second",
        title_zh="第二条",
        url="https://example.com/b",
        source="manual",
    )
    cfg = AppConfig(paths=PathsConfig(content_digests_dir=str(digests_dir)))
    calls: list[str] = []
    stop_after = {"n": 0}

    def _fake_deep_summarize(
        config: AppConfig,
        *,
        urls: list[str],
        input_path: str | Path | None = None,
        input_zh_path: str | Path | None = None,
        llm_flag: str | None = None,
        should_stop=None,
    ) -> tuple[Path, Path, int, str | None]:
        calls.extend(urls)
        return Path(input_path or ""), Path(input_zh_path or ""), 1, "llm"

    def _should_stop() -> bool:
        stop_after["n"] += 1
        return stop_after["n"] > 1

    monkeypatch.setattr(
        "src.admin.services.adhd.deep_summarize_digest",
        _fake_deep_summarize,
    )
    monkeypatch.setattr(
        "src.admin.services.adhd.invalidate_digest_audio",
        lambda *args, **kwargs: None,
    )

    result = generate_digest_adhd_batch(
        cfg,
        day=day,
        indices=[first.index, second.index],
        should_stop=_should_stop,
    )
    assert result["changed"] == 1
    assert calls == ["https://example.com/a"]
