"""本地 content 静态构建（不拉取热搜）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.models import AppConfig, PathsConfig, SiteConfig


def test_build_site_from_content_skips_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.site_build import build_site_from_content

    content = tmp_path / "content"
    digests = content / "digests"
    hot = content / "hot_topics"
    arena = content / "arena"
    public = tmp_path / "public"
    for d in (digests, hot, arena, public):
        d.mkdir(parents=True)

    day = "2026-09-13"
    (digests / f"{day}.en.md").write_text(
        f"""# ai_hot digest

Generated (UTC): 2026-09-13T10:00:00+00:00
Selected: 1

## 1. Local build

- source: `manual`
- url: https://example.com/local
- summary: keep me
""",
        encoding="utf-8",
    )
    (hot / "latest.json").write_text(
        """{
  "generated_at": "2026-09-13T10:00:00Z",
  "items": [{
    "heat": 1.0,
    "source": "manual",
    "title": "Saved title",
    "url": "https://example.com/hot",
    "title_zh": "保留中文",
    "sources": [],
    "reason": "test"
  }]
}""",
        encoding="utf-8",
    )

    def _fail_probe(*args: object, **kwargs: object) -> object:
        raise AssertionError("run_probe should not run in build_site_from_content")

    monkeypatch.setattr("src.hot_topics_probe.run_probe", _fail_probe)

    cfg = AppConfig(
        paths=PathsConfig(
            content_digests_dir=str(digests),
            hot_topics_path=str(hot / "latest.json"),
            arena_cache_dir=str(arena),
            site_output_dir=str(public),
        ),
        site=SiteConfig(base_url="https://example.com"),
    )
    out = build_site_from_content(cfg)
    assert out == public
    assert (public / "index.html").is_file()
    html = (public / "index.html").read_text(encoding="utf-8")
    assert "Local build" in html
    hot_zh = (public / "zh" / "hot.html").read_text(encoding="utf-8")
    assert "保留中文" in hot_zh
