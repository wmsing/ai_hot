"""把 content/digests/*.md 建成极简静态站 → public/。"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from html import escape
from pathlib import Path

from src.config import load_app_config
from src.leaderboard import fetch_arena_boards
from src.models import ArenaLeaderboard, DigestDocument, DigestItem, SiteConfig
from src.site_parse import parse_digest_markdown
from src.timeutil import format_published, parse_published

_DIGEST_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.(en|zh)\.md$")

SITE_NAME_EN = "AI Hot Digest"
SITE_TAGLINE_EN = "Daily AI highlights from HN & official feeds"
SITE_TAGLINE_ZH = "AI 热点摘要"
_REPO_ISSUES = "https://github.com/wmsing/ai_hot/issues"

_BOARD_TITLES: dict[str, tuple[str, str]] = {
    "agent": ("Agent", "Agent"),
    "text-to-image": ("Text to Image", "文生图"),
    "text-to-video": ("Text to Video", "文生视频"),
    "image-edit": ("Image Edit", "图片编辑"),
    "image-to-video": ("Image to Video", "图生视频"),
    "video-edit": ("Video Edit", "视频编辑"),
}


@dataclass(frozen=True)
class DayFiles:
    day: date
    en: Path | None
    zh: Path | None


@dataclass(frozen=True)
class PageLinks:
    css: str
    home: str
    arena: str
    archive: str
    disclosure: str
    about: str
    privacy: str
    lang_other: str
    brand_home: str


def build_site(
    *,
    content_dir: Path,
    output_dir: Path,
    site: SiteConfig | None = None,
    arena_boards: list[ArenaLeaderboard] | None = None,
) -> None:
    """扫描 content_dir，写出完整静态站到 output_dir。

    arena_boards 写入独立 Arena 页；首页与归档不嵌入榜单。
    """
    cfg = site if site is not None else SiteConfig()
    boards = arena_boards if arena_boards is not None else []
    days = _scan_days(content_dir)
    origin = _origin(cfg)
    sitemap_urls: list[str] = []
    if output_dir.exists():
        _clear_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "styles.css").write_text(_stylesheet(), encoding="utf-8")
    (output_dir / "favicon.svg").write_text(_favicon_svg(), encoding="utf-8")

    _write(
        output_dir / "archive" / "index.html",
        _render_archive_index(days, "en", cfg),
    )
    _write(
        output_dir / "zh" / "archive" / "index.html",
        _render_archive_index(days, "zh", cfg),
    )
    sitemap_urls.extend(
        [
            _abs_url(origin, "/archive/"),
            _abs_url(origin, "/zh/archive/"),
        ]
    )
    _write(output_dir / "arena.html", _render_arena_page("en", cfg, boards))
    _write(output_dir / "zh" / "arena.html", _render_arena_page("zh", cfg, boards))
    sitemap_urls.extend(
        [_abs_url(origin, "/arena.html"), _abs_url(origin, "/zh/arena.html")]
    )
    _write(output_dir / "disclosure.html", _render_disclosure("en", cfg))
    _write(output_dir / "zh" / "disclosure.html", _render_disclosure("zh", cfg))
    _write(output_dir / "about.html", _render_about("en", cfg))
    _write(output_dir / "zh" / "about.html", _render_about("zh", cfg))
    _write(output_dir / "privacy.html", _render_privacy("en", cfg))
    _write(output_dir / "zh" / "privacy.html", _render_privacy("zh", cfg))
    sitemap_urls.extend(
        [
            _abs_url(origin, "/disclosure.html"),
            _abs_url(origin, "/zh/disclosure.html"),
            _abs_url(origin, "/about.html"),
            _abs_url(origin, "/zh/about.html"),
            _abs_url(origin, "/privacy.html"),
            _abs_url(origin, "/zh/privacy.html"),
        ]
    )

    latest = days[0] if days else None
    if latest is None:
        _write(output_dir / "index.html", _render_empty_home("en", cfg))
        _write(output_dir / "zh" / "index.html", _render_empty_home("zh", cfg))
        sitemap_urls.extend([_abs_url(origin, "/"), _abs_url(origin, "/zh/")])
        _write_robots(output_dir, origin)
        _write_sitemap(output_dir, sitemap_urls)
        return

    for idx, day_files in enumerate(days):
        day_s = day_files.day.isoformat()
        en_doc = _load_doc(day_files.en)
        zh_doc = _load_doc(day_files.zh)
        has_zh = zh_doc is not None
        has_en = en_doc is not None
        is_latest = day_files.day == latest.day
        # days 按新→旧；newer=更近一天，older=更早一天
        newer_day = days[idx - 1].day if idx > 0 else None
        older_day = days[idx + 1].day if idx + 1 < len(days) else None
        newer_is_latest = newer_day == latest.day if newer_day else False
        en_archive_path = f"/archive/{day_s}/"
        zh_archive_path = f"/zh/archive/{day_s}/"

        if en_doc is not None:
            archive_page = _render_digest(
                doc=en_doc,
                day=day_files.day,
                lang="en",
                has_other_lang=has_zh,
                links=_links_digest_archive("en", day_s, has_zh),
                site=cfg,
                older_day=older_day,
                newer_day=newer_day,
                is_home=False,
                newer_is_latest=newer_is_latest,
            )
            _write(output_dir / "archive" / day_s / "index.html", archive_page)
            sitemap_urls.append(_abs_url(origin, en_archive_path))
            if is_latest:
                home_page = _render_digest(
                    doc=en_doc,
                    day=day_files.day,
                    lang="en",
                    has_other_lang=has_zh,
                    links=_links_digest_home("en", day_s, has_zh),
                    site=cfg,
                    older_day=older_day,
                    newer_day=None,
                    is_home=True,
                    newer_is_latest=False,
                )
                _write(output_dir / "index.html", home_page)
                sitemap_urls.append(_abs_url(origin, "/"))
        elif is_latest:
            _write(
                output_dir / "index.html",
                _render_missing_home("en", day_files.day, cfg),
            )
            sitemap_urls.append(_abs_url(origin, "/"))

        if zh_doc is not None:
            archive_page = _render_digest(
                doc=zh_doc,
                day=day_files.day,
                lang="zh",
                has_other_lang=has_en,
                links=_links_digest_archive("zh", day_s, has_en),
                site=cfg,
                older_day=older_day,
                newer_day=newer_day,
                is_home=False,
                newer_is_latest=newer_is_latest,
            )
            _write(
                output_dir / "zh" / "archive" / day_s / "index.html",
                archive_page,
            )
            sitemap_urls.append(_abs_url(origin, zh_archive_path))
            if is_latest:
                home_page = _render_digest(
                    doc=zh_doc,
                    day=day_files.day,
                    lang="zh",
                    has_other_lang=has_en,
                    links=_links_digest_home("zh", day_s, has_en),
                    site=cfg,
                    older_day=older_day,
                    newer_day=None,
                    is_home=True,
                    newer_is_latest=False,
                )
                _write(output_dir / "zh" / "index.html", home_page)
                sitemap_urls.append(_abs_url(origin, "/zh/"))
        elif is_latest:
            _write(
                output_dir / "zh" / "index.html",
                _render_missing_home("zh", day_files.day, cfg),
            )
            sitemap_urls.append(_abs_url(origin, "/zh/"))

    _write_robots(output_dir, origin)
    _write_sitemap(output_dir, sitemap_urls)


def _make_links(
    *,
    css: str,
    home: str,
    archive: str,
    disclosure: str,
    lang_other: str,
    brand_home: str,
) -> PageLinks:
    return PageLinks(
        css=css,
        home=home,
        arena=disclosure.replace("disclosure.html", "arena.html"),
        archive=archive,
        disclosure=disclosure,
        about=disclosure.replace("disclosure.html", "about.html"),
        privacy=disclosure.replace("disclosure.html", "privacy.html"),
        lang_other=lang_other,
        brand_home=brand_home,
    )


def _links_digest_home(lang: str, day_s: str, has_other: bool) -> PageLinks:
    _ = day_s
    if lang == "en":
        other = "zh/index.html" if has_other else ""
        return _make_links(
            css="styles.css",
            home="index.html",
            archive="archive/index.html",
            disclosure="disclosure.html",
            lang_other=other,
            brand_home="index.html",
        )
    other = "../index.html" if has_other else ""
    return _make_links(
        css="../styles.css",
        home="index.html",
        archive="archive/index.html",
        disclosure="disclosure.html",
        lang_other=other,
        brand_home="index.html",
    )


def _links_digest_archive(lang: str, day_s: str, has_other: bool) -> PageLinks:
    if lang == "en":
        other = f"../../zh/archive/{day_s}/index.html" if has_other else ""
        return _make_links(
            css="../../styles.css",
            home="../../index.html",
            archive="../index.html",
            disclosure="../../disclosure.html",
            lang_other=other,
            brand_home="../../index.html",
        )
    other = f"../../../archive/{day_s}/index.html" if has_other else ""
    return _make_links(
        css="../../../styles.css",
        home="../../index.html",
        archive="../index.html",
        disclosure="../../disclosure.html",
        lang_other=other,
        brand_home="../../index.html",
    )


def _links_root(lang: str, *, lang_other: str) -> PageLinks:
    if lang == "en":
        return _make_links(
            css="styles.css",
            home="index.html",
            archive="archive/index.html",
            disclosure="disclosure.html",
            lang_other=lang_other,
            brand_home="index.html",
        )
    return _make_links(
        css="../styles.css",
        home="index.html",
        archive="archive/index.html",
        disclosure="disclosure.html",
        lang_other=lang_other,
        brand_home="index.html",
    )


def _scan_days(content_dir: Path) -> list[DayFiles]:
    if not content_dir.is_dir():
        return []
    by_day: dict[date, dict[str, Path]] = {}
    for path in sorted(content_dir.iterdir()):
        if not path.is_file():
            continue
        match = _DIGEST_NAME_RE.match(path.name)
        if not match:
            continue
        day = date.fromisoformat(match.group(1))
        by_day.setdefault(day, {})[match.group(2)] = path
    return [
        DayFiles(day=day, en=files.get("en"), zh=files.get("zh"))
        for day in sorted(by_day.keys(), reverse=True)
        for files in [by_day[day]]
    ]


def _load_doc(path: Path | None) -> DigestDocument | None:
    if path is None or not path.is_file():
        return None
    return parse_digest_markdown(path.read_text(encoding="utf-8"))


def _write(path: Path, html: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def _clear_dir(path: Path) -> None:
    for child in path.iterdir():
        if child.is_dir():
            _clear_dir(child)
            child.rmdir()
        else:
            child.unlink()


def _lang_nav(lang: str, other_href: str) -> str:
    if lang == "en":
        if other_href:
            inner = (
                '<span class="lang-current">EN</span> · '
                f'<a href="{escape(other_href)}">中文</a>'
            )
        else:
            inner = (
                '<span class="lang-current">EN</span> · '
                '<span class="muted">中文 N/A</span>'
            )
    elif other_href:
        inner = (
            f'<a href="{escape(other_href)}">EN</a> · '
            '<span class="lang-current">中文</span>'
        )
    else:
        inner = (
            '<span class="muted">EN N/A</span> · <span class="lang-current">中文</span>'
        )
    return f'<div class="lang-switch">{inner}</div>'


def _main_nav(lang: str, links: PageLinks, *, include_archive: bool = True) -> str:
    if lang == "en":
        home_l, arena_l, archive_l = "Home", "AI Models", "Archive"
        about_l, privacy_l = "About", "Privacy"
        nav_label = "Primary"
    else:
        home_l, arena_l, archive_l = "首页", "AI 模型榜", "归档"
        about_l, privacy_l = "关于", "隐私"
        nav_label = "主导航"
    parts = [
        f'<a href="{escape(links.home)}">{home_l}</a>',
        f'<a href="{escape(links.arena)}">{arena_l}</a>',
    ]
    if include_archive:
        parts.append(f'<a href="{escape(links.archive)}">{archive_l}</a>')
    parts.append(f'<a href="{escape(links.about)}">{about_l}</a>')
    parts.append(f'<a href="{escape(links.privacy)}">{privacy_l}</a>')
    return (
        f'<nav class="site-nav" aria-label="{nav_label}">'
        f'<div class="nav-primary">{"".join(parts)}</div>'
        f"{_lang_nav(lang, links.lang_other)}"
        f"</nav>"
    )


def _footer(lang: str, links: PageLinks, site: SiteConfig) -> str:
    if site.affiliate_enabled:
        lead = (
            "This page may contain affiliate links."
            if lang == "en"
            else "本页可能包含联盟推广链接。"
        )
    else:
        lead = (
            "Affiliate links are not enabled."
            if lang == "en"
            else "当前未启用联盟链接。"
        )
    if lang == "en":
        about_l, privacy_l, disc_l = "About", "Privacy", "Disclosure"
    else:
        about_l, privacy_l, disc_l = "关于", "隐私", "披露说明"
    return (
        f"{lead} "
        f'<a href="{escape(links.about)}">{about_l}</a> · '
        f'<a href="{escape(links.privacy)}">{privacy_l}</a> · '
        f'<a href="{escape(links.disclosure)}">{disc_l}</a>.'
    )


def _brand_sub(lang: str) -> str:
    tagline = SITE_TAGLINE_ZH if lang == "zh" else SITE_TAGLINE_EN
    return f'<p class="tagline">{escape(tagline)}</p>'


def _page_description(lang: str) -> str:
    return SITE_TAGLINE_ZH if lang == "zh" else SITE_TAGLINE_EN


def _digest_description(lang: str, day: date, selected: int) -> str:
    day_s = day.isoformat()
    if lang == "en":
        return (
            f"AI Hot Digest for {day_s}: {selected} AI highlights from "
            "Hacker News and official feeds."
        )
    return (
        f"AI 热点摘要 {day_s}：精选 {selected} 条来自 Hacker News 与官方源的 AI 资讯。"
    )


def _static_description(page: str, lang: str) -> str:
    """page: home|archive|arena|about|privacy|disclosure|empty|missing"""
    en = {
        "home": SITE_TAGLINE_EN,
        "archive": "Browse archived daily AI Hot Digests by date.",
        "arena": "AI model leaderboards from Arena.ai (third-party scores).",
        "about": "About AI Hot Digest — personal AI news curation from HN and RSS.",
        "privacy": "Privacy policy for the AI Hot Digest static site.",
        "disclosure": "Affiliate disclosure for AI Hot Digest.",
        "empty": "AI Hot Digest — no digests published yet.",
        "missing": "AI Hot Digest — latest day content is temporarily unavailable.",
    }
    zh = {
        "home": SITE_TAGLINE_ZH,
        "archive": "按日期浏览 AI 热点摘要归档。",
        "arena": "来自 Arena.ai 的 AI 模型榜（第三方数据）。",
        "about": "关于 AI Hot Digest：个人维护的 HN 与 RSS AI 热点摘要。",
        "privacy": "AI Hot Digest 静态站隐私说明。",
        "disclosure": "AI Hot Digest 联盟推广披露说明。",
        "empty": "AI Hot Digest — 暂无摘要。",
        "missing": "AI Hot Digest — 最新日内容暂不可用。",
    }
    table = zh if lang == "zh" else en
    return table.get(page, _page_description(lang))


def _origin(site: SiteConfig) -> str:
    return site.base_url.rstrip("/")


def _abs_url(origin: str, path: str) -> str:
    text = path.strip()
    if not text or text == "/":
        return f"{origin}/"
    if not text.startswith("/"):
        text = "/" + text
    return origin + text


def _hreflang_pairs(
    *,
    en_path: str | None,
    zh_path: str | None,
    origin: str,
) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    en_url = _abs_url(origin, en_path) if en_path is not None else None
    zh_url = _abs_url(origin, zh_path) if zh_path is not None else None
    if en_url:
        pairs.append(("en", en_url))
    if zh_url:
        pairs.append(("zh-Hans", zh_url))
    default = en_url or zh_url
    if default:
        pairs.append(("x-default", default))
    return pairs


def _write_robots(output_dir: Path, origin: str) -> None:
    body = f"User-agent: *\nAllow: /\n\nSitemap: {origin}/sitemap.xml\n"
    _write(output_dir / "robots.txt", body)


def _write_sitemap(output_dir: Path, urls: list[str]) -> None:
    # stable unique order
    seen: set[str] = set()
    ordered: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for url in ordered:
        lines.append("  <url>")
        lines.append(f"    <loc>{escape(url)}</loc>")
        lines.append("  </url>")
    lines.append("</urlset>")
    lines.append("")
    _write(output_dir / "sitemap.xml", "\n".join(lines))


def _favicon_href(css_href: str) -> str:
    return css_href.replace("styles.css", "favicon.svg")


def _contact_blurb(lang: str, site: SiteConfig) -> str:
    email = site.contact_email.strip()
    if email:
        safe = escape(email)
        return f'<a href="mailto:{safe}">{safe}</a>'
    issues = escape(_REPO_ISSUES)
    if lang == "en":
        return f'open an issue on the <a href="{issues}">project repository</a>'
    return f'通过 <a href="{issues}">项目仓库 Issues</a> 联系'


def _owner_blurb(lang: str, site: SiteConfig) -> str:
    name = site.owner_name.strip()
    if name:
        return escape(name)
    return "a personally maintained project" if lang == "en" else "个人维护的项目"


def _render_digest(
    *,
    doc: DigestDocument,
    day: date,
    lang: str,
    has_other_lang: bool,
    links: PageLinks,
    site: SiteConfig,
    older_day: date | None = None,
    newer_day: date | None = None,
    is_home: bool = False,
    newer_is_latest: bool = False,
) -> str:
    day_s = day.isoformat()
    gen = escape(doc.generated_at) if doc.generated_at else "—"
    selected = doc.selected if doc.selected is not None else len(doc.items)
    if lang == "en":
        meta = f"Generated (UTC): {gen} · Selected: {selected}"
    else:
        meta = f"生成时间（UTC）：{gen} · 精选：{selected}"

    items_html = "".join(
        _render_item(item, lang, affiliate_enabled=site.affiliate_enabled)
        for item in doc.items
    )
    if not items_html:
        items_html = (
            '<p class="muted">No items.</p>'
            if lang == "en"
            else '<p class="muted">暂无条目。</p>'
        )

    day_nav = _day_nav(
        lang,
        older_day=older_day,
        newer_day=newer_day,
        is_home=is_home,
        newer_is_latest=newer_is_latest,
    )

    origin = _origin(site)
    if is_home:
        en_path, zh_path = "/", "/zh/"
    else:
        en_path, zh_path = f"/archive/{day_s}/", f"/zh/archive/{day_s}/"
    canonical_path = en_path if lang == "en" else zh_path
    en_hl = en_path if lang == "en" or has_other_lang else None
    zh_hl = zh_path if lang == "zh" or has_other_lang else None

    return _shell(
        title=f"{SITE_NAME_EN} — {day_s}",
        css_href=links.css,
        lang=lang,
        description=_digest_description(lang, day, selected),
        canonical=_abs_url(origin, canonical_path),
        hreflang=_hreflang_pairs(en_path=en_hl, zh_path=zh_hl, origin=origin),
        body=f"""
<div class="site">
<header class="site-header">
  <div class="brand-block">
    <p class="brand"><a href="{escape(links.brand_home)}">{escape(SITE_NAME_EN)}</a></p>
    {_brand_sub(lang)}
  </div>
  {_main_nav(lang, links)}
  <div class="day-bar">
    <h1>{escape(day_s)}</h1>
    <p class="meta">{meta}</p>
    {day_nav}
  </div>
</header>
<main class="feed">
  {items_html}
</main>
<footer class="site-footer"><p>{_footer(lang, links, site)}</p></footer>
</div>
""",
    )


def _day_nav(
    lang: str,
    *,
    older_day: date | None,
    newer_day: date | None,
    is_home: bool,
    newer_is_latest: bool,
) -> str:
    """前一天=更早归档；后一天=更新归档（首页为最新则无后一天）。"""
    if lang == "en":
        older_l, newer_l = "← Previous day", "Next day →"
    else:
        older_l, newer_l = "← 前一天", "后一天 →"

    older_href = _day_href(
        target=older_day,
        is_home=is_home,
        link_home=False,
    )
    newer_href = _day_href(
        target=newer_day,
        is_home=is_home,
        link_home=newer_is_latest,
    )

    older_html = (
        f'<a class="day-nav-link" href="{escape(older_href)}">{escape(older_l)}</a>'
        if older_href
        else f'<span class="day-nav-muted">{escape(older_l)}</span>'
    )
    newer_html = (
        f'<a class="day-nav-link" href="{escape(newer_href)}">{escape(newer_l)}</a>'
        if newer_href
        else f'<span class="day-nav-muted">{escape(newer_l)}</span>'
    )
    nav_label = "Day navigation" if lang == "en" else "日期导航"
    return (
        f'<nav class="day-nav" aria-label="{escape(nav_label)}">'
        f'{older_html}<span class="day-nav-gap"></span>{newer_html}</nav>'
    )


def _day_href(
    *,
    target: date | None,
    is_home: bool,
    link_home: bool,
) -> str | None:
    if target is None:
        return None
    day_s = target.isoformat()
    if is_home:
        return f"archive/{day_s}/index.html"
    if link_home:
        return "../../index.html"
    return f"../{day_s}/index.html"


def _board_title(board: str, lang: str) -> str:
    titles = _BOARD_TITLES.get(board)
    if titles is None:
        return board
    return titles[0] if lang == "en" else titles[1]


def _format_as_of_date(raw: str) -> str:
    """Arena last_updated → 2026-9-7；解析失败则原样返回。"""
    text = raw.strip()
    if not text:
        return ""
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(text, fmt)
            return f"{dt.year}-{dt.month}-{dt.day}"
        except ValueError:
            continue
    # drop timezone-less ISO with time
    if "T" in text:
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return f"{dt.year}-{dt.month}-{dt.day}"
        except ValueError:
            pass
    return text


def _board_heading(board: ArenaLeaderboard, lang: str) -> str:
    title = _board_title(board.board, lang)
    as_of = _format_as_of_date(board.last_updated)
    if not as_of:
        return title
    if lang == "en":
        return f"{title} (as of {as_of})"
    return f"{title}（截至 {as_of}）"


def _format_arena_score(score: float | None) -> str:
    if score is None:
        return "—"
    if score == int(score):
        return str(int(score))
    return f"{score:.2f}"


def _render_arena_board_section(board: ArenaLeaderboard, lang: str) -> str:
    heading = _board_heading(board, lang)
    if lang == "en":
        col_rank, col_model, col_vendor = "Rank", "Model", "Vendor"
        note_prefix = "Source:"
        not_ours = "Third-party scores — not our evaluation."
        score_col = board.score_label
    else:
        col_rank, col_model, col_vendor = "名次", "模型", "厂商"
        note_prefix = "来源："
        not_ours = "第三方数据，非本站评测。"
        if board.score_label == "Net Improvement":
            score_col = "净提升"
        elif board.score_label == "Elo":
            score_col = "评分"
        else:
            score_col = board.score_label

    rows: list[str] = []
    for row in board.models:
        vendor = escape(row.vendor) if row.vendor else "—"
        score = _format_arena_score(row.score)
        rows.append(
            "<tr>"
            f'<td class="arena-rank">{row.rank}</td>'
            f"<td>{escape(row.model)}</td>"
            f"<td>{vendor}</td>"
            f'<td class="arena-elo">{escape(score)}</td>'
            "</tr>"
        )

    page_href = escape(board.source_page, quote=True)
    heading_id = f"arena-{escape(board.board)}"

    return f"""
<section class="arena" aria-labelledby="{heading_id}">
  <div class="arena-head">
    <h2 id="{heading_id}">{escape(heading)}</h2>
  </div>
  <div class="arena-table-wrap">
    <table class="arena-table">
      <thead>
        <tr>
          <th scope="col">{escape(col_rank)}</th>
          <th scope="col">{escape(col_model)}</th>
          <th scope="col">{escape(col_vendor)}</th>
          <th scope="col">{escape(score_col)}</th>
        </tr>
      </thead>
      <tbody>
        {"".join(rows)}
      </tbody>
    </table>
  </div>
  <p class="arena-note">
    {escape(note_prefix)}
    <a href="{page_href}" target="_blank" rel="noopener noreferrer">Arena AI</a>
    · {escape(not_ours)}
  </p>
</section>
""".strip()


def _render_arena_page(
    lang: str,
    site: SiteConfig,
    boards: list[ArenaLeaderboard],
) -> str:
    if lang == "en":
        links = _links_root("en", lang_other="zh/arena.html")
        heading = "AI Models"
        intro = (
            "Arena AI model & agent rankings (community mirror), refreshed on each "
            "site build. Dates in titles are Arena's last update "
            "(scores keep changing). "
            "Media boards show Elo; Agent shows Net Improvement."
        )
        empty = "AI model ranking data is unavailable right now."
    else:
        links = _links_root("zh", lang_other="../arena.html")
        heading = "AI 模型榜"
        intro = (
            "Arena AI 模型与 Agent 排行（社区镜像），站点每次构建时刷新。"
            "标题中的日期为 Arena 侧最近更新日（分数会持续变动）。"
            "媒体榜为评分（Elo）；Agent 榜展示净提升（Net Improvement）。"
        )
        empty = "当前暂无 AI 模型榜数据。"

    if boards:
        body = "\n".join(_render_arena_board_section(b, lang) for b in boards)
    else:
        body = f'<p class="muted">{escape(empty)}</p>'

    origin = _origin(site)
    en_path, zh_path = "/arena.html", "/zh/arena.html"
    return _shell(
        title=f"{SITE_NAME_EN} — {heading}",
        css_href=links.css,
        lang=lang,
        description=_static_description("arena", lang),
        canonical=_abs_url(origin, en_path if lang == "en" else zh_path),
        hreflang=_hreflang_pairs(en_path=en_path, zh_path=zh_path, origin=origin),
        body=f"""
<div class="site">
<header class="site-header">
  <div class="brand-block">
    <p class="brand"><a href="{escape(links.brand_home)}">{escape(SITE_NAME_EN)}</a></p>
    {_brand_sub(lang)}
  </div>
  {_main_nav(lang, links)}
  <h1 class="page-title">{escape(heading)}</h1>
  <p class="meta arena-page-intro">{escape(intro)}</p>
</header>
<main class="feed arena-page">
  {body}
</main>
<footer class="site-footer"><p>{_footer(lang, links, site)}</p></footer>
</div>
""",
    )


def _render_item(
    item: DigestItem,
    lang: str,
    *,
    affiliate_enabled: bool,
) -> str:
    labels = (
        {
            "summary": "Summary",
            "affiliate": "Affiliate offer",
            "published": "Published",
        }
        if lang == "en"
        else {
            "summary": "摘要",
            "affiliate": "联盟推荐",
            "published": "发布时间",
        }
    )
    title = escape(item.title)
    if item.url.strip():
        title_html = (
            f'<a href="{escape(item.url.strip(), quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">{title}</a>'
        )
    else:
        title_html = title

    meta_bits: list[str] = []
    if item.source:
        meta_bits.append(f'<span class="badge">{escape(item.source)}</span>')
    published_disp = _display_published(item.published)
    if published_disp:
        meta_bits.append(
            f"<span>{escape(labels['published'])}: {escape(published_disp)}</span>"
        )
    score_disp = _display_score_line(item.score_line)
    if score_disp:
        meta_bits.append(f"<span>{escape(score_disp)}</span>")

    bits = [
        '<article class="item">',
        f'<span class="item-index" aria-hidden="true">{item.index:02d}</span>',
    ]
    img = item.image_url.strip()
    if img:
        href = escape(item.url.strip() or img, quote=True)
        src = escape(img, quote=True)
        bits.append(
            f'<a class="item-thumb" href="{href}" '
            f'target="_blank" rel="noopener noreferrer">'
            f'<img src="{src}" alt="" loading="lazy" '
            f'referrerpolicy="no-referrer" decoding="async" /></a>'
        )
    bits.append('<div class="item-body">')
    bits.append(f"<h2>{title_html}</h2>")
    if meta_bits:
        bits.append(f'<p class="item-meta">{" · ".join(meta_bits)}</p>')
    if item.summary:
        bits.append(
            f'<p class="summary"><span class="label">{labels["summary"]}</span> '
            f"{escape(item.summary)}</p>"
        )
    # Why / reason 不对读者展示
    aff = item.affiliate_url.strip()
    if affiliate_enabled and aff:
        bits.append(
            f'<p class="affiliate"><span class="label">{labels["affiliate"]}</span> '
            f'<a href="{escape(aff, quote=True)}" target="_blank" '
            f'rel="sponsored noopener noreferrer">{escape(aff)}</a></p>'
        )
    bits.extend(["</div>", "</article>"])
    return "\n".join(bits)


def _display_published(raw: str) -> str:
    text = raw.strip()
    if not text or text.lower() == "n/a":
        return ""
    dt = parse_published(text)
    if dt is None:
        return text
    return format_published(dt)


def _display_score_line(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    if "n/a" in text.lower() and not re.search(r"\d", text):
        return ""
    return text


def _render_archive_index(days: list[DayFiles], lang: str, site: SiteConfig) -> str:
    if lang == "en":
        links = _make_links(
            css="../styles.css",
            home="../index.html",
            archive="index.html",
            disclosure="../disclosure.html",
            lang_other="../zh/archive/index.html",
            brand_home="../index.html",
        )
        heading, empty = "Archive", "No digests yet."
    else:
        links = _make_links(
            css="../../styles.css",
            home="../index.html",
            archive="index.html",
            disclosure="../disclosure.html",
            lang_other="../../archive/index.html",
            brand_home="../index.html",
        )
        heading, empty = "归档", "暂无摘要。"

    if not days:
        lis = f'<p class="muted">{escape(empty)}</p>'
    else:
        rows = ['<ul class="archive-list">']
        for day_files in days:
            day_s = day_files.day.isoformat()
            missing = ""
            if lang == "en" and day_files.en is None:
                missing = " (EN missing)"
            if lang == "zh" and day_files.zh is None:
                missing = " (中文缺失)"
            rows.append(
                f'<li><a href="{day_s}/index.html">{day_s}</a>{escape(missing)}</li>'
            )
        rows.append("</ul>")
        lis = "\n".join(rows)

    origin = _origin(site)
    en_path, zh_path = "/archive/", "/zh/archive/"
    return _shell(
        title=f"{SITE_NAME_EN} — {heading}",
        css_href=links.css,
        lang=lang,
        description=_static_description("archive", lang),
        canonical=_abs_url(origin, en_path if lang == "en" else zh_path),
        hreflang=_hreflang_pairs(en_path=en_path, zh_path=zh_path, origin=origin),
        body=f"""
<div class="site">
<header class="site-header">
  <div class="brand-block">
    <p class="brand"><a href="{escape(links.brand_home)}">{escape(SITE_NAME_EN)}</a></p>
    {_brand_sub(lang)}
  </div>
  {_main_nav(lang, links, include_archive=False)}
  <h1 class="page-title">{heading}</h1>
</header>
<main class="feed">{lis}</main>
<footer class="site-footer"><p>{_footer(lang, links, site)}</p></footer>
</div>
""",
    )


def _static_page_shell(
    *,
    lang: str,
    links: PageLinks,
    site: SiteConfig,
    heading: str,
    body_text: str,
    page_key: str,
    en_path: str,
    zh_path: str,
) -> str:
    origin = _origin(site)
    return _shell(
        title=f"{SITE_NAME_EN} — {heading}",
        css_href=links.css,
        lang=lang,
        description=_static_description(page_key, lang),
        canonical=_abs_url(origin, en_path if lang == "en" else zh_path),
        hreflang=_hreflang_pairs(en_path=en_path, zh_path=zh_path, origin=origin),
        body=f"""
<div class="site">
<header class="site-header">
  <div class="brand-block">
    <p class="brand"><a href="{escape(links.brand_home)}">{escape(SITE_NAME_EN)}</a></p>
    {_brand_sub(lang)}
  </div>
  {_main_nav(lang, links)}
  <h1 class="page-title">{heading}</h1>
</header>
<main class="prose">{body_text}</main>
<footer class="site-footer"><p>{_footer(lang, links, site)}</p></footer>
</div>
""",
    )


def _render_disclosure(lang: str, site: SiteConfig) -> str:
    if lang == "en":
        links = _links_root("en", lang_other="zh/disclosure.html")
        heading = "Disclosure"
        if site.affiliate_enabled:
            body_text = (
                "<p>This site may include affiliate links. If you buy through "
                "those links, we may earn a commission at no extra cost to you."
                "</p>"
                "<p>Affiliate offers are marked on individual digest items "
                "when present.</p>"
            )
        else:
            body_text = (
                "<p>Affiliate links are configured but currently disabled "
                "(<code>site.affiliate_enabled: false</code>).</p>"
                "<p>When enabled, sponsored links will appear on items and "
                "will be disclosed here and in the footer.</p>"
            )
    else:
        links = _links_root("zh", lang_other="../disclosure.html")
        heading = "披露说明"
        if site.affiliate_enabled:
            body_text = (
                "<p>本站可能包含联盟推广链接。经由这些链接购买时，"
                "我们可能获得佣金，你无需额外付费。</p>"
                "<p>若某条摘要含联盟推荐，会在该条目中标注。</p>"
            )
        else:
            body_text = (
                "<p>联盟链接功能已预留，当前关闭"
                "（<code>site.affiliate_enabled: false</code>）。</p>"
                "<p>启用后，相关链接会显示在条目中，并在本页与页脚披露。</p>"
            )
    return _static_page_shell(
        lang=lang,
        links=links,
        site=site,
        heading=heading,
        body_text=body_text,
        page_key="disclosure",
        en_path="/disclosure.html",
        zh_path="/zh/disclosure.html",
    )


def _render_about(lang: str, site: SiteConfig) -> str:
    owner = _owner_blurb(lang, site)
    contact = _contact_blurb(lang, site)
    if lang == "en":
        links = _links_root("en", lang_other="zh/about.html")
        heading = "About"
        body_text = (
            f"<p><strong>{escape(SITE_NAME_EN)}</strong> is {owner} that "
            "curates AI-related highlights from Hacker News and selected "
            "official or mirrored RSS feeds.</p>"
            "<p>Each day is archived as a short digest with source links. "
            "Content is for personal monitoring and public reading—not "
            "investment or professional advice.</p>"
            f"<p>Contact: {contact}.</p>"
        )
    else:
        links = _links_root("zh", lang_other="../about.html")
        heading = "关于"
        body_text = (
            f"<p><strong>{escape(SITE_NAME_EN)}</strong>（{escape(SITE_TAGLINE_ZH)}）"
            f"是{owner}：汇总 Hacker News 与精选官方/镜像 RSS 中的 AI 相关热点。</p>"
            "<p>按日归档为短摘要并附上来源链接。内容仅供个人巡检与公开阅读，"
            "不构成投资或专业建议。</p>"
            f"<p>联系：{contact}。</p>"
        )
    return _static_page_shell(
        lang=lang,
        links=links,
        site=site,
        heading=heading,
        body_text=body_text,
        page_key="about",
        en_path="/about.html",
        zh_path="/zh/about.html",
    )


def _render_privacy(lang: str, site: SiteConfig) -> str:
    contact = _contact_blurb(lang, site)
    if lang == "en":
        links = _links_root("en", lang_other="zh/privacy.html")
        heading = "Privacy"
        body_text = (
            "<p>This is a static site. We do not run accounts, comments, or "
            "server-side analytics on these pages.</p>"
            "<p>Hosting and CDN providers (for example Cloudflare) may "
            "process standard request logs such as IP address, user agent, "
            "and timestamps as part of delivering the site.</p>"
            "<p>We do not sell personal data. Third-party pages you open via "
            "outbound links have their own privacy practices.</p>"
            "<p>If affiliate links are enabled later, those partners may set "
            "cookies or measure referrals according to their policies; "
            "see the Disclosure page.</p>"
            f"<p>Questions: {contact}.</p>"
        )
    else:
        links = _links_root("zh", lang_other="../privacy.html")
        heading = "隐私"
        body_text = (
            "<p>本站为静态站点，不提供账号、评论或页面侧服务端统计。</p>"
            "<p>托管与 CDN（例如 Cloudflare）在交付页面时可能处理常规请求日志，"
            "例如 IP、User-Agent 与时间戳。</p>"
            "<p>我们不出售个人数据。你点击的外链站点遵循其各自隐私政策。</p>"
            "<p>若日后启用联盟链接，合作方可能按其政策设置 Cookie 或统计引荐；"
            "详见披露说明页。</p>"
            f"<p>疑问请联系：{contact}。</p>"
        )
    return _static_page_shell(
        lang=lang,
        links=links,
        site=site,
        heading=heading,
        body_text=body_text,
        page_key="privacy",
        en_path="/privacy.html",
        zh_path="/zh/privacy.html",
    )


def _render_empty_home(
    lang: str,
    site: SiteConfig,
) -> str:
    if lang == "en":
        links = _links_root("en", lang_other="zh/index.html")
        msg = "No digests published yet. Run publish then build."
    else:
        links = _links_root("zh", lang_other="../index.html")
        msg = "尚无已发布摘要。请先 publish 再 build。"
    origin = _origin(site)
    en_path, zh_path = "/", "/zh/"
    return _shell(
        title=SITE_NAME_EN,
        css_href=links.css,
        lang=lang,
        description=_static_description("empty", lang),
        canonical=_abs_url(origin, en_path if lang == "en" else zh_path),
        hreflang=_hreflang_pairs(en_path=en_path, zh_path=zh_path, origin=origin),
        body=f"""
<div class="site">
<header class="site-header">
  <div class="brand-block">
    <p class="brand"><a href="{escape(links.brand_home)}">{escape(SITE_NAME_EN)}</a></p>
    {_brand_sub(lang)}
  </div>
  {_main_nav(lang, links)}
</header>
<main class="feed"><p class="muted">{escape(msg)}</p></main>
<footer class="site-footer"><p>{_footer(lang, links, site)}</p></footer>
</div>
""",
    )


def _render_missing_home(
    lang: str,
    day: date,
    site: SiteConfig,
) -> str:
    day_s = day.isoformat()
    if lang == "en":
        links = _links_root("en", lang_other="zh/index.html")
        msg = f"English digest for {day_s} is missing."
    else:
        links = _links_root("zh", lang_other="../index.html")
        msg = f"{day_s} 的中文摘要缺失。"
    origin = _origin(site)
    en_path, zh_path = "/", "/zh/"
    return _shell(
        title=f"{SITE_NAME_EN} — {day_s}",
        css_href=links.css,
        lang=lang,
        description=_static_description("missing", lang),
        canonical=_abs_url(origin, en_path if lang == "en" else zh_path),
        hreflang=_hreflang_pairs(en_path=en_path, zh_path=zh_path, origin=origin),
        body=f"""
<div class="site">
<header class="site-header">
  <div class="brand-block">
    <p class="brand"><a href="{escape(links.brand_home)}">{escape(SITE_NAME_EN)}</a></p>
    {_brand_sub(lang)}
  </div>
  {_main_nav(lang, links)}
  <div class="day-bar">
    <h1>{escape(day_s)}</h1>
  </div>
</header>
<main class="feed"><p class="muted">{escape(msg)}</p></main>
<footer class="site-footer"><p>{_footer(lang, links, site)}</p></footer>
</div>
""",
    )


def _shell(
    *,
    title: str,
    css_href: str,
    lang: str,
    body: str,
    description: str | None = None,
    canonical: str | None = None,
    hreflang: list[tuple[str, str]] | None = None,
) -> str:
    html_lang = "zh-Hans" if lang == "zh" else "en"
    desc = description if description is not None else _page_description(lang)
    favicon = _favicon_href(css_href)
    fonts = (
        "https://fonts.googleapis.com/css2?"
        "family=Outfit:wght@500;600;700&amp;"
        "family=Literata:opsz,wght@7..72,400;600&amp;"
        "family=Source+Sans+3:wght@400;500;600&amp;display=swap"
    )
    seo_links = ""
    if canonical:
        seo_links += f'\n  <link rel="canonical" href="{escape(canonical)}">'
        seo_links += f'\n  <meta property="og:url" content="{escape(canonical)}">'
    if hreflang:
        for hlang, href in hreflang:
            seo_links += (
                f'\n  <link rel="alternate" hreflang="{escape(hlang)}" '
                f'href="{escape(href)}">'
            )
    return f"""<!DOCTYPE html>
<html lang="{html_lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <meta name="description" content="{escape(desc)}">
  <meta name="theme-color" content="#eef3f0" media="(prefers-color-scheme: light)">
  <meta name="theme-color" content="#0f1613" media="(prefers-color-scheme: dark)">
  <meta property="og:title" content="{escape(title)}">
  <meta property="og:description" content="{escape(desc)}">
  <meta property="og:type" content="website">
{seo_links}
  <link rel="icon" href="{escape(favicon)}" type="image/svg+xml">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="{fonts}" rel="stylesheet">
  <link rel="stylesheet" href="{escape(css_href)}">
</head>
<body>
{body}
</body>
</html>
"""


def _favicon_svg() -> str:
    return """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" fill="none">
  <rect width="32" height="32" rx="10" fill="#1a3c32"/>
  <circle cx="16" cy="16" r="6.5" stroke="#eef3f0" stroke-width="2.5"/>
</svg>
""".strip()


def _stylesheet() -> str:
    # Taste soft + ink green (墨绿); dials VARIANCE 5 / MOTION 3 / DENSITY 2
    return """
:root {
  --bg: #eef3f0;
  --bg-elev: #f7faf8;
  --ink: #14201b;
  --muted: #5a6b63;
  --accent: #1a3c32;
  --accent-hot: #245246;
  --line: #d2ddd6;
  --focus: #1a3c32;
  --shadow: 0 8px 28px rgba(20, 32, 27, 0.07);
  --radius: 16px;
  --font-display: "Outfit", "Avenir Next", sans-serif;
  --font-body: "Literata", "Palatino Linotype", serif;
  --font-ui: "Source Sans 3", "Segoe UI", sans-serif;
  --pad: clamp(1.5rem, 5vw, 2.5rem);
  --max: 44rem;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1613;
    --bg-elev: #17201c;
    --ink: #e4ebe7;
    --muted: #95a59d;
    --accent: #7eb39f;
    --accent-hot: #96c7b4;
    --line: #2a3832;
    --focus: #7eb39f;
    --shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
  }
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  min-height: 100vh;
  font-family: var(--font-ui);
  font-size: 1.0625rem;
  background:
    radial-gradient(
      ellipse 90% 55% at 50% -20%,
      color-mix(in srgb, var(--accent) 12%, transparent),
      transparent 60%
    ),
    var(--bg);
  color: var(--ink);
  line-height: 1.7;
}
.site {
  margin: 0 auto;
  max-width: var(--max);
  padding: var(--pad) var(--pad) 4rem;
}
a {
  color: var(--accent);
  text-decoration-thickness: 1px;
  text-underline-offset: 0.2em;
  transition: color 0.28s ease, opacity 0.28s ease;
}
a:hover { color: var(--accent-hot); }
a:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 3px;
  border-radius: 4px;
}
.site-header {
  margin-bottom: 2rem;
  animation: soft-in 0.7s ease both;
}
.brand-block { margin-bottom: 1.35rem; }
.brand {
  font-family: var(--font-display);
  font-size: clamp(2.45rem, 7vw, 3.25rem);
  font-weight: 600;
  letter-spacing: -0.03em;
  margin: 0 0 0.5rem;
  line-height: 1.08;
}
.brand a {
  color: inherit;
  text-decoration: none;
}
.brand a:hover { color: var(--accent); }
.tagline {
  margin: 0;
  max-width: 28rem;
  color: var(--muted);
  font-size: 1.18rem;
  font-weight: 400;
  line-height: 1.5;
}
.site-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 0.9rem 1.35rem;
  align-items: center;
  justify-content: space-between;
  margin: 0 0 1.75rem;
  padding: 0.95rem 1.1rem;
  background: var(--bg-elev);
  border: 1px solid var(--line);
  border-radius: calc(var(--radius) - 2px);
  box-shadow: var(--shadow);
  font-size: 1rem;
  font-weight: 500;
}
.nav-primary {
  display: flex;
  flex-wrap: wrap;
  gap: 0.8rem 1.2rem;
}
.nav-primary a {
  color: var(--muted);
  text-decoration: none;
}
.nav-primary a:hover { color: var(--accent-hot); }
.lang-switch {
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.lang-current { color: var(--ink); font-weight: 600; }
.lang-switch a { text-decoration: none; }
.day-bar {
  padding: 1rem 1.15rem;
  background: var(--bg-elev);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  animation: soft-in 0.85s 0.08s ease both;
}
.day-bar h1,
.page-title {
  font-family: var(--font-display);
  font-size: clamp(1.5rem, 4vw, 1.85rem);
  font-weight: 600;
  letter-spacing: -0.02em;
  margin: 0 0 0.3rem;
}
.day-bar .meta,
.meta {
  margin: 0;
  color: var(--muted);
  font-size: 0.95rem;
}
.day-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  gap: 0.75rem;
  margin-top: 0.85rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--line);
  font-size: 0.92rem;
}
.day-nav-gap {
  flex: 1 1 auto;
  min-width: 0.5rem;
}
.day-nav > :last-child {
  margin-left: auto;
  text-align: right;
}
.day-nav-link {
  color: var(--accent);
  text-decoration: none;
  font-weight: 600;
}
.day-nav-link:hover { text-decoration: underline; }
.day-nav-muted {
  color: var(--muted);
  opacity: 0.55;
}
.page-title { margin-bottom: 1.25rem; }
.arena {
  padding: 1.2rem 1.15rem 1.15rem;
  background: var(--bg-elev);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  animation: soft-in 0.85s 0.05s ease both;
}
.arena-head h2 {
  font-family: var(--font-display);
  font-size: clamp(1.2rem, 3.2vw, 1.4rem);
  font-weight: 600;
  letter-spacing: -0.02em;
  margin: 0 0 0.25rem;
}
.arena-sub,
.arena-page-intro {
  margin: 0 0 0.9rem;
  color: var(--muted);
  font-size: 0.92rem;
  line-height: 1.45;
}
.arena-page-intro { margin-bottom: 1.25rem; }
.arena-table-wrap {
  overflow-x: auto;
  margin: 0 0 0.65rem;
  border: 1px solid var(--line);
  border-radius: calc(var(--radius) - 6px);
}
.arena-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.92rem;
  font-variant-numeric: tabular-nums;
}
.arena-table th,
.arena-table td {
  padding: 0.55rem 0.7rem;
  text-align: left;
  border-bottom: 1px solid var(--line);
  vertical-align: top;
}
.arena-table th {
  color: var(--muted);
  font-weight: 600;
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  background: color-mix(in srgb, var(--accent) 6%, transparent);
}
.arena-table tbody tr:last-child td { border-bottom: none; }
.arena-rank,
.arena-elo {
  font-family: var(--font-display);
  font-weight: 600;
  color: var(--accent);
  white-space: nowrap;
}
.arena-meta,
.arena-note {
  margin: 0.35rem 0 0;
  color: var(--muted);
  font-size: 0.82rem;
  line-height: 1.45;
}
.feed {
  display: flex;
  flex-direction: column;
  gap: 0.95rem;
}
.item {
  display: grid;
  grid-template-columns: 2.5rem 1fr;
  gap: 0.55rem 0.95rem;
  padding: 1.3rem 1.25rem 1.35rem;
  background: var(--bg-elev);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  transition:
    box-shadow 0.3s ease,
    border-color 0.3s ease,
    transform 0.3s ease;
}
.item:has(.item-thumb) {
  grid-template-columns: 2.5rem 5.75rem 1fr;
}
.item:hover {
  border-color: color-mix(in srgb, var(--accent) 35%, var(--line));
  box-shadow: 0 12px 32px rgba(20, 32, 27, 0.09);
  transform: translateY(-2px);
}
.item-index {
  font-family: var(--font-display);
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--accent);
  letter-spacing: -0.02em;
  padding-top: 0.3rem;
  font-variant-numeric: tabular-nums;
  opacity: 0.85;
}
.item-thumb {
  display: block;
  width: 5.75rem;
  height: 5.75rem;
  border-radius: 0.55rem;
  overflow: hidden;
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--line) 55%, transparent);
  flex-shrink: 0;
}
.item-thumb img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.item-body { min-width: 0; }
.item h2 {
  font-family: var(--font-body);
  font-size: clamp(1.22rem, 2.5vw, 1.38rem);
  font-weight: 600;
  margin: 0 0 0.55rem;
  line-height: 1.4;
  letter-spacing: -0.01em;
}
.item h2 a {
  color: var(--ink);
  text-decoration: none;
}
.item h2 a:hover { color: var(--accent); }
.item-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.3rem 0.15rem;
  margin: 0 0 0.75rem;
  color: var(--muted);
  font-size: 0.9rem;
  font-family: var(--font-ui);
}
.badge {
  display: inline-block;
  border: none;
  background: color-mix(in srgb, var(--accent) 14%, var(--bg));
  color: var(--accent);
  border-radius: 999px;
  padding: 0.16rem 0.6rem;
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  font-family: ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
}
.summary, .why, .affiliate {
  margin: 0.5rem 0 0;
  font-family: var(--font-body);
  font-size: 1.12rem;
  color: var(--ink);
}
.why {
  color: var(--muted);
  font-size: 0.98rem;
  font-family: var(--font-ui);
}
.affiliate {
  margin-top: 0.75rem;
  padding-top: 0.7rem;
  border-top: 1px dashed var(--line);
  font-size: 0.98rem;
  font-family: var(--font-ui);
  color: var(--muted);
}
.label {
  display: inline-block;
  font-family: var(--font-ui);
  font-size: 0.74rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--accent);
  margin-right: 0.4rem;
}
.muted { color: var(--muted); }
.prose {
  font-family: var(--font-body);
  font-size: 1.18rem;
}
.prose p { margin: 0 0 1rem; }
.archive-list {
  list-style: none;
  margin: 0;
  padding: 0.35rem;
  background: var(--bg-elev);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  overflow: hidden;
}
.archive-list li {
  margin: 0;
  border-bottom: 1px solid var(--line);
  padding: 0.95rem 1rem;
  line-height: 1.4;
  transition: background-color 0.25s ease;
}
.archive-list li:last-child { border-bottom: none; }
.archive-list li:hover {
  background: color-mix(in srgb, var(--accent) 6%, transparent);
}
.archive-list a {
  color: var(--ink);
  font-family: var(--font-display);
  font-weight: 600;
  text-decoration: none;
  letter-spacing: -0.01em;
}
.archive-list a:hover { color: var(--accent-hot); }
.site-footer {
  margin-top: 3rem;
  padding-top: 1.25rem;
  border-top: 1px solid var(--line);
  color: var(--muted);
  font-size: 0.84rem;
  font-family: var(--font-ui);
}
.site-footer a { color: var(--accent); }
code {
  font-size: 0.85em;
  font-family: ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
}
@keyframes soft-in {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  .site-header, .day-bar, .arena { animation: none; }
  .item, .archive-list li { transition: none; }
  .item:hover { transform: none; }
}
@media (max-width: 480px) {
  .item {
    grid-template-columns: 1.8rem 1fr;
    padding: 1.05rem 1rem 1.1rem;
  }
  .item:has(.item-thumb) {
    grid-template-columns: 1.8rem 4.5rem 1fr;
  }
  .item-thumb {
    width: 4.5rem;
    height: 4.5rem;
  }
  .site-nav {
    align-items: flex-start;
    padding: 0.85rem 0.95rem;
  }
}
""".strip()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build AI Hot Digest static site.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _parse_args(argv)
    config = load_app_config()
    boards = fetch_arena_boards(config.leaderboard, config.http)
    build_site(
        content_dir=Path(config.paths.content_digests_dir),
        output_dir=Path(config.paths.site_output_dir),
        site=config.site,
        arena_boards=boards,
    )
    print(f"[ai_hot] site built → {config.paths.site_output_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
