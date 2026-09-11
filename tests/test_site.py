"""site_parse / publish / site_build 单测。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from src.models import SiteConfig
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
- image: https://cdn.example/cover.webp
- summary: Hello summary
- why: hn score>=100
- affiliate: https://partner.example/offer
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
- 联盟链接：https://partner.example/offer-zh
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
    assert item.affiliate_url == "https://partner.example/offer"
    assert item.image_url == "https://cdn.example/cover.webp"


def test_parse_digest_zh() -> None:
    doc = parse_digest_markdown(_ZH_DIGEST)
    assert doc.selected == 1
    assert doc.generated_at == "2026-09-10T05:00:00+00:00"
    assert len(doc.items) == 1
    item = doc.items[0]
    assert item.title == "示例标题"
    assert item.source == "hn"
    assert item.summary == "你好摘要"
    assert "评分=120" in item.score_line
    assert item.affiliate_url == "https://partner.example/offer-zh"


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


def _seed_digests(content: Path) -> None:
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


def test_build_site_outputs(tmp_path: Path) -> None:
    content = tmp_path / "digests"
    _seed_digests(content)
    out = tmp_path / "public"
    build_site(content_dir=content, output_dir=out)

    assert (out / "styles.css").is_file()
    assert (out / "favicon.svg").is_file()
    assert (out / "index.html").is_file()
    assert (out / "zh" / "index.html").is_file()
    assert (out / "archive" / "index.html").is_file()
    assert (out / "archive" / "2026-09-10" / "index.html").is_file()
    assert (out / "archive" / "2026-09-09" / "index.html").is_file()
    assert (out / "zh" / "archive" / "2026-09-10" / "index.html").is_file()
    assert (out / "disclosure.html").is_file()
    assert (out / "zh" / "disclosure.html").is_file()
    assert (out / "about.html").is_file()
    assert (out / "zh" / "about.html").is_file()
    assert (out / "privacy.html").is_file()
    assert (out / "zh" / "privacy.html").is_file()

    home = (out / "index.html").read_text(encoding="utf-8")
    assert "AI Hot Digest" in home
    assert "Daily AI highlights" in home
    assert "as of 2026-09-10" in home
    assert "as of 2026-09-10 05" not in home
    assert "Newer" in home
    assert 'class="item"' in home
    assert "badge-source" in home
    assert 'data-source="hn"' in home
    assert 'data-heat="1"' in home
    assert 'class="read-progress"' in home
    assert 'src="feed.js"' in home
    assert 'class="site-header"' in home
    styles = (out / "styles.css").read_text(encoding="utf-8")
    assert ".site-nav" in styles
    assert "position: sticky" in styles
    assert ".read-progress" in styles
    assert "#0d0f17" in styles
    assert "body::before" in styles
    assert "radial-gradient" in styles
    assert "cursor: pointer" in styles
    assert ".item" in styles
    assert "100vw" in styles
    assert "calc(50% - 50vw)" in styles
    assert "0.65" in styles or "blur(36px)" in styles
    assert "blur(36px)" in styles
    assert '[data-source="hn"]' in styles
    assert "--source" in styles
    assert 'class="item-index"' in home
    assert "Outfit" in home
    assert "Source+Sans+3" in home or "Source Sans 3" in home
    assert "Literata" not in home
    assert "cursor: pointer" in styles
    assert "translateY(-4px)" in styles
    assert 'property="og:title"' in home
    assert 'rel="icon"' in home
    assert 'href="favicon.svg"' in home
    assert 'target="_blank"' in home
    assert 'rel="noopener noreferrer"' in home
    assert "Affiliate links are not enabled." in home
    assert 'rel="sponsored' not in home
    assert "partner.example" not in home
    assert 'href="about.html"' in home
    assert 'href="arena.html"' in home
    assert ">AI Models<" in home
    assert 'href="privacy.html"' in home
    assert ">Archive<" not in home.split('class="nav-primary">', 1)[1].split(
        "</div>", 1
    )[0]
    assert 'href="archive/index.html">Archive</a>' in home
    assert 'class="lang-toggle"' in home
    assert ">中文<" in home
    assert "lang-current" not in home
    assert "EN ·" not in home
    assert 'class="why"' not in home
    assert "hn score>=100" not in home
    assert "score=n/a" not in home
    assert "2026-09-10 01:00 UTC" in home
    assert "Published:" in home
    assert "Published (UTC)" not in home
    assert 'class="item-thumb"' in home
    assert "https://cdn.example/cover.webp" in home
    assert 'class="day-nav"' not in home
    assert "Previous day" not in home
    assert ">Latest<" not in home
    assert "highlights · newest first" not in home
    assert 'class="day-bar"' not in home
    assert 'class="feed-day-sticky"' in home
    assert 'data-day="2026-09-10"' in home
    assert 'id="load-more"' not in home
    assert (out / "feed.js").is_file()
    older = (out / "archive" / "2026-09-09" / "index.html").read_text(encoding="utf-8")
    assert "Example Title" in older
    assert "Next day" in older
    assert 'href="../../index.html"' in older
    assert 'class="day-nav"' in older
    assert 'class="read-progress"' in older
    assert 'src="../../feed.js"' in older
    assert 'data-source="hn"' in older
    assert "badge-source" in older
    feed_js = (out / "feed.js").read_text(encoding="utf-8")
    assert "read-progress" in feed_js
    assert "--p" in feed_js
    assert "--nav-sticky-bottom" in feed_js
    assert "has-day-sticky" in feed_js
    assert "--nav-sticky-bottom" in styles
    assert "has-day-sticky" in styles
    zh_home = (out / "zh" / "index.html").read_text(encoding="utf-8")
    assert "发布时间:" in zh_home or "发布时间：" in zh_home
    assert "发布时间（UTC）" not in zh_home
    assert "前一天" not in zh_home
    assert "后一天" not in zh_home
    assert ">最新<" not in zh_home
    assert "条 · 新在前" not in zh_home
    assert 'class="feed-day-sticky"' in zh_home
    assert "AI 热点摘要 截至 2026-09-10" in zh_home
    assert "截至 2026-09-10 05" not in zh_home
    assert 'class="lang-toggle"' in zh_home
    assert ">EN<" in zh_home
    assert "lang-current" not in zh_home
    assert "更新" in zh_home
    assert 'href="../favicon.svg"' in zh_home
    assert "当前未启用联盟链接" in zh_home
    assert ">归档<" not in zh_home.split('class="nav-primary">', 1)[1].split(
        "</div>", 1
    )[0]
    assert 'href="archive/index.html">归档</a>' in zh_home

    archive_day = (out / "zh" / "archive" / "2026-09-10" / "index.html").read_text(
        encoding="utf-8"
    )
    assert '<p class="tagline">AI 热点摘要</p>' in archive_day
    assert "截至" not in archive_day.split('class="tagline">', 1)[1].split("</p>", 1)[0]

    about = (out / "about.html").read_text(encoding="utf-8")
    assert "personally maintained project" in about
    assert "as of" not in about.split('class="tagline">', 1)[1].split("</p>", 1)[0]
    privacy = (out / "privacy.html").read_text(encoding="utf-8")
    assert "static site" in privacy.lower() or "static" in privacy
    disclosure = (out / "disclosure.html").read_text(encoding="utf-8")
    assert "affiliate_enabled" in disclosure


def test_build_site_home_load_more(tmp_path: Path) -> None:
    content = tmp_path / "digests"
    content.mkdir()
    en_lines = [
        "# ai_hot digest",
        "",
        "Generated (UTC): 2026-09-10T05:00:00+00:00",
        "Selected: 35",
        "",
    ]
    zh_lines = [
        "# ai_hot 消息摘要",
        "",
        "生成时间（UTC）：2026-09-10T05:00:00+00:00",
        "精选：35",
        "",
    ]
    for i in range(35):
        hour = i % 24
        pub = f"2026-09-10T{hour:02d}:00:00+00:00"
        en_lines.extend(
            [
                f"## {i + 1}. Title {i}",
                "",
                "- source: `hn`",
                f"- url: https://example.com/item-{i}",
                f"- published: {pub}",
                "- score=10 | comments=1",
                f"- summary: Summary {i}",
                "",
            ]
        )
        zh_lines.extend(
            [
                f"## {i + 1}. 标题 {i}",
                "",
                "- 来源：`hn`",
                f"- 链接：https://example.com/item-{i}",
                f"- 发布时间：{pub}",
                "- 评分=10 | 评论数=1",
                f"- 摘要：摘要 {i}",
                "",
            ]
        )
    (content / "2026-09-10.en.md").write_text("\n".join(en_lines), encoding="utf-8")
    (content / "2026-09-10.zh.md").write_text("\n".join(zh_lines), encoding="utf-8")
    out = tmp_path / "public"
    build_site(content_dir=content, output_dir=out)

    home = (out / "index.html").read_text(encoding="utf-8")
    assert "highlights · newest first" not in home
    assert 'id="load-more"' in home
    assert 'data-feed-base="/feed/en"' in home
    assert 'data-next="1"' in home
    assert home.count('class="item"') == 30
    assert home.count('class="feed-day-sticky"') == 1
    assert 'data-day="2026-09-10"' in home
    page1 = (out / "feed" / "en" / "1.html").read_text(encoding="utf-8")
    assert 'class="feed-chunk"' in page1
    assert 'data-next=""' in page1
    assert page1.count('class="item"') == 5
    assert 'class="feed-day-sticky"' not in page1
    assert "Title" in page1

    zh_home = (out / "zh" / "index.html").read_text(encoding="utf-8")
    assert "条 · 新在前" not in zh_home
    assert 'data-feed-base="/feed/zh"' in zh_home
    assert (out / "feed" / "zh" / "1.html").is_file()


def test_build_site_home_sticky_by_day(tmp_path: Path) -> None:
    content = tmp_path / "digests"
    content.mkdir()
    (content / "2026-09-10.en.md").write_text(
        "\n".join(
            [
                "# ai_hot digest",
                "",
                "Generated (UTC): 2026-09-10T05:00:00+00:00",
                "Selected: 2",
                "",
                "## 1. Newer A",
                "",
                "- source: `hn`",
                "- url: https://example.com/a",
                "- published: 2026-09-10T12:00:00+00:00",
                "- summary: a",
                "",
                "## 2. Newer B",
                "",
                "- source: `hn`",
                "- url: https://example.com/b",
                "- published: 2026-09-10T08:00:00+00:00",
                "- summary: b",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (content / "2026-09-09.en.md").write_text(
        "\n".join(
            [
                "# ai_hot digest",
                "",
                "Generated (UTC): 2026-09-09T05:00:00+00:00",
                "Selected: 1",
                "",
                "## 1. Older C",
                "",
                "- source: `hn`",
                "- url: https://example.com/c",
                "- published: 2026-09-09T18:00:00+00:00",
                "- summary: c",
                "",
            ]
        ),
        encoding="utf-8",
    )
    out = tmp_path / "public"
    build_site(content_dir=content, output_dir=out)
    home = (out / "index.html").read_text(encoding="utf-8")
    assert home.count('class="feed-day-sticky"') == 2
    assert home.index('data-day="2026-09-10"') < home.index('data-day="2026-09-09"')
    assert home.index("Newer A") < home.index("Older C")
    assert home.index('data-day="2026-09-10"') < home.index("Newer A")
    assert home.index('data-day="2026-09-09"') < home.index("Older C")


def test_build_site_seo(tmp_path: Path) -> None:
    content = tmp_path / "digests"
    _seed_digests(content)
    out = tmp_path / "public"
    base = "https://example.test"
    build_site(
        content_dir=content,
        output_dir=out,
        site=SiteConfig(base_url=base),
    )

    robots = (out / "robots.txt").read_text(encoding="utf-8")
    assert "User-agent: *" in robots
    assert "Allow: /" in robots
    assert f"Sitemap: {base}/sitemap.xml" in robots

    sitemap = (out / "sitemap.xml").read_text(encoding="utf-8")
    assert f"<loc>{base}/</loc>" in sitemap
    assert f"<loc>{base}/zh/</loc>" in sitemap
    assert f"<loc>{base}/archive/</loc>" in sitemap
    assert f"<loc>{base}/archive/2026-09-10/</loc>" in sitemap
    assert f"<loc>{base}/zh/archive/2026-09-10/</loc>" in sitemap
    assert f"<loc>{base}/about.html</loc>" in sitemap
    assert f"<loc>{base}/arena.html</loc>" in sitemap

    home = (out / "index.html").read_text(encoding="utf-8")
    assert 'rel="canonical" href="https://example.test/"' in home
    assert 'hreflang="en" href="https://example.test/"' in home
    assert 'hreflang="zh-Hans" href="https://example.test/zh/"' in home
    assert 'hreflang="x-default" href="https://example.test/"' in home
    assert "Daily AI highlights from HN &amp; official feeds" in home or (
        'content="Daily AI highlights from HN & official feeds"' in home
    )

    about = (out / "about.html").read_text(encoding="utf-8")
    assert 'rel="canonical" href="https://example.test/about.html"' in about
    assert "About AI Hot Digest" in about
    assert 'hreflang="zh-Hans" href="https://example.test/zh/about.html"' in about

    arena = (out / "arena.html").read_text(encoding="utf-8")
    assert "AI model leaderboards" in arena

    archive_day = (out / "archive" / "2026-09-09" / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'hreflang="zh-Hans" href="https://example.test/zh/archive/2026-09-09/"' in (
        archive_day
    )


def test_build_site_affiliate_enabled(tmp_path: Path) -> None:
    content = tmp_path / "digests"
    _seed_digests(content)
    out = tmp_path / "public"
    build_site(
        content_dir=content,
        output_dir=out,
        site=SiteConfig(affiliate_enabled=True),
    )
    home = (out / "index.html").read_text(encoding="utf-8")
    assert "may contain affiliate links" in home
    assert 'rel="sponsored noopener noreferrer"' in home
    assert "https://partner.example/offer" in home
    disclosure = (out / "disclosure.html").read_text(encoding="utf-8")
    assert "commission" in disclosure
