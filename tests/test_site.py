"""site_parse / publish / site_build 单测。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from src.publish import archive_digests
from src.site_build import build_site
from src.site_parse import parse_digest_markdown

_EN_DIGEST = """# ai_hot digest

Generated (UTC): 2026-09-10T05:00:00+00:00
Selected: 1

## 1. Example Title

- source: `hn`
- url: https://example.com/a
- published: 2026-09-10T01:00:00+00:00
- score=120 | comments=30
- summary: Hello summary
- why: hn score>=100
"""

_ZH_DIGEST = """# ai_hot 消息摘要

生成时间（UTC）：2026-09-10T05:00:00+00:00
精选：1

## 1. 示例标题

- 来源：`hn`
- 链接：https://example.com/a
- 发布时间：2026-09-10T01:00:00+00:00
- 评分=120 | 评论数=30
- 摘要：你好摘要
- 原因：HN评分达标
"""


def test_parse_digest_en() -> None:
    doc = parse_digest_markdown(_EN_DIGEST)
    assert doc.selected == 1
    assert doc.generated_at.startswith("2026-09-10")
    assert len(doc.items) == 1
    item = doc.items[0]
    assert item.title == "Example Title"
    assert item.source == "hn"
    assert item.url == "https://example.com/a"
    assert "Hello summary" in item.summary
    assert "score=120" in item.score_line


def test_parse_digest_zh() -> None:
    doc = parse_digest_markdown(_ZH_DIGEST)
    assert doc.selected == 1
    assert len(doc.items) == 1
    item = doc.items[0]
    assert item.title == "示例标题"
    assert item.source == "hn"
    assert item.summary == "你好摘要"
    assert "评分=120" in item.score_line


def test_archive_digests(tmp_path: Path) -> None:
    en = tmp_path / "digest.md"
    zh = tmp_path / "digest.zh.md"
    en.write_text(_EN_DIGEST, encoding="utf-8")
    zh.write_text(_ZH_DIGEST, encoding="utf-8")
    content = tmp_path / "content"
    written = archive_digests(
        digest_en=en,
        digest_zh=zh,
        content_dir=content,
        day=date(2026, 9, 10),
    )
    assert len(written) == 2
    assert (content / "2026-09-10.en.md").is_file()
    assert (content / "2026-09-10.zh.md").is_file()


def test_build_site_outputs(tmp_path: Path) -> None:
    content = tmp_path / "digests"
    content.mkdir()
    (content / "2026-09-09.en.md").write_text(_EN_DIGEST, encoding="utf-8")
    (content / "2026-09-09.zh.md").write_text(_ZH_DIGEST, encoding="utf-8")
    (content / "2026-09-10.en.md").write_text(
        _EN_DIGEST.replace("Example Title", "Newer"),
        encoding="utf-8",
    )
    (content / "2026-09-10.zh.md").write_text(
        _ZH_DIGEST.replace("示例标题", "更新"),
        encoding="utf-8",
    )
    out = tmp_path / "public"
    build_site(content_dir=content, output_dir=out)

    assert (out / "styles.css").is_file()
    assert (out / "index.html").is_file()
    assert (out / "zh" / "index.html").is_file()
    assert (out / "archive" / "index.html").is_file()
    assert (out / "archive" / "2026-09-10" / "index.html").is_file()
    assert (out / "archive" / "2026-09-09" / "index.html").is_file()
    assert (out / "zh" / "archive" / "2026-09-10" / "index.html").is_file()
    assert (out / "disclosure.html").is_file()
    assert (out / "zh" / "disclosure.html").is_file()

    home = (out / "index.html").read_text(encoding="utf-8")
    assert "AI Hot Digest" in home
    assert "Newer" in home
    assert 'target="_blank"' in home
    assert 'rel="noopener noreferrer"' in home
    zh_home = (out / "zh" / "index.html").read_text(encoding="utf-8")
    assert "AI 热点摘要" in zh_home
    assert "更新" in zh_home
