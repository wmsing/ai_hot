"""Admin 拉取数据。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.models import AppConfig, PathsConfig


def test_run_pull_data_probe_digest_and_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.admin.services.probe import run_pull_data

    hot_path = tmp_path / "hot_topics" / "latest.json"
    digests_dir = tmp_path / "digests"
    out_en = tmp_path / "out" / "digest.md"
    out_zh = tmp_path / "out" / "digest.zh.md"
    digests_dir.mkdir(parents=True)
    out_en.parent.mkdir(parents=True)
    out_en.write_text("# digest\n", encoding="utf-8")
    cfg = AppConfig(
        paths=PathsConfig(
            hot_topics_path=str(hot_path),
            content_digests_dir=str(digests_dir),
            digest_path=str(out_en),
            digest_zh_path=str(out_zh),
        )
    )

    monkeypatch.setattr(
        "src.admin.services.probe.run_probe",
        lambda config: [(1.0, object())],
    )
    monkeypatch.setattr(
        "src.admin.services.probe.save_hot_topics_snapshot",
        lambda path, ranked: None,
    )
    monkeypatch.setattr(
        "src.admin.services.probe.run_once",
        lambda config, **kwargs: [object(), object()],
    )
    monkeypatch.setattr(
        "src.admin.services.probe.archive_digests",
        lambda **kwargs: [digests_dir / "2026-09-13.en.md"],
    )

    result = run_pull_data(cfg)
    assert result["hot_topics_count"] == 1
    assert result["digest_selected"] == 2
    assert result["archived"] == [str(digests_dir / "2026-09-13.en.md")]
