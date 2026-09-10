"""把 content/digests/*.md 建成极简静态站 → public/。"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date
from html import escape
from pathlib import Path

from src.config import load_app_config
from src.models import DigestDocument, DigestItem, SiteConfig
from src.site_parse import parse_digest_markdown

_DIGEST_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.(en|zh)\.md$")

SITE_NAME_EN = "AI Hot Digest"
SITE_TAGLINE_EN = "Daily AI highlights from HN & official feeds"
SITE_TAGLINE_ZH = "AI 热点摘要"
_REPO_ISSUES = "https://github.com/wmsing/ai_hot/issues"


@dataclass(frozen=True)
class DayFiles:
    day: date
    en: Path | None
    zh: Path | None


@dataclass(frozen=True)
class PageLinks:
    css: str
    home: str
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
) -> None:
    """扫描 content_dir，写出完整静态站到 output_dir。"""
    cfg = site if site is not None else SiteConfig()
    days = _scan_days(content_dir)
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
    _write(output_dir / "disclosure.html", _render_disclosure("en", cfg))
    _write(output_dir / "zh" / "disclosure.html", _render_disclosure("zh", cfg))
    _write(output_dir / "about.html", _render_about("en", cfg))
    _write(output_dir / "zh" / "about.html", _render_about("zh", cfg))
    _write(output_dir / "privacy.html", _render_privacy("en", cfg))
    _write(output_dir / "zh" / "privacy.html", _render_privacy("zh", cfg))

    latest = days[0] if days else None
    if latest is None:
        _write(output_dir / "index.html", _render_empty_home("en", cfg))
        _write(output_dir / "zh" / "index.html", _render_empty_home("zh", cfg))
        return

    for day_files in days:
        day_s = day_files.day.isoformat()
        en_doc = _load_doc(day_files.en)
        zh_doc = _load_doc(day_files.zh)
        has_zh = zh_doc is not None
        has_en = en_doc is not None

        if en_doc is not None:
            archive_page = _render_digest(
                doc=en_doc,
                day=day_files.day,
                lang="en",
                has_other_lang=has_zh,
                links=_links_digest_archive("en", day_s, has_zh),
                site=cfg,
            )
            _write(output_dir / "archive" / day_s / "index.html", archive_page)
            if day_files.day == latest.day:
                home_page = _render_digest(
                    doc=en_doc,
                    day=day_files.day,
                    lang="en",
                    has_other_lang=has_zh,
                    links=_links_digest_home("en", day_s, has_zh),
                    site=cfg,
                )
                _write(output_dir / "index.html", home_page)
        elif day_files.day == latest.day:
            _write(
                output_dir / "index.html",
                _render_missing_home("en", day_files.day, cfg),
            )

        if zh_doc is not None:
            archive_page = _render_digest(
                doc=zh_doc,
                day=day_files.day,
                lang="zh",
                has_other_lang=has_en,
                links=_links_digest_archive("zh", day_s, has_en),
                site=cfg,
            )
            _write(
                output_dir / "zh" / "archive" / day_s / "index.html",
                archive_page,
            )
            if day_files.day == latest.day:
                home_page = _render_digest(
                    doc=zh_doc,
                    day=day_files.day,
                    lang="zh",
                    has_other_lang=has_en,
                    links=_links_digest_home("zh", day_s, has_en),
                    site=cfg,
                )
                _write(output_dir / "zh" / "index.html", home_page)
        elif day_files.day == latest.day:
            _write(
                output_dir / "zh" / "index.html",
                _render_missing_home("zh", day_files.day, cfg),
            )


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
        home_l, archive_l = "Home", "Archive"
        about_l, privacy_l = "About", "Privacy"
        nav_label = "Primary"
    else:
        home_l, archive_l = "首页", "归档"
        about_l, privacy_l = "关于", "隐私"
        nav_label = "主导航"
    parts = [f'<a href="{escape(links.home)}">{home_l}</a>']
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
) -> str:
    del has_other_lang  # encoded in links.lang_other
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

    return _shell(
        title=f"{SITE_NAME_EN} — {day_s}",
        css_href=links.css,
        lang=lang,
        description=_page_description(lang),
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
  </div>
</header>
<main class="feed">
  {items_html}
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
        {"summary": "Summary", "why": "Why", "affiliate": "Affiliate offer"}
        if lang == "en"
        else {"summary": "摘要", "why": "原因", "affiliate": "联盟推荐"}
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
    if item.published:
        meta_bits.append(f"<span>{escape(item.published)}</span>")
    if item.score_line:
        meta_bits.append(f"<span>{escape(item.score_line)}</span>")

    bits = [
        '<article class="item">',
        f'<span class="item-index" aria-hidden="true">{item.index:02d}</span>',
        '<div class="item-body">',
        f"<h2>{title_html}</h2>",
    ]
    if meta_bits:
        bits.append(f'<p class="item-meta">{" · ".join(meta_bits)}</p>')
    if item.summary:
        bits.append(
            f'<p class="summary"><span class="label">{labels["summary"]}</span> '
            f"{escape(item.summary)}</p>"
        )
    if item.reason:
        bits.append(
            f'<p class="why"><span class="label">{labels["why"]}</span> '
            f"{escape(item.reason)}</p>"
        )
    aff = item.affiliate_url.strip()
    if affiliate_enabled and aff:
        bits.append(
            f'<p class="affiliate"><span class="label">{labels["affiliate"]}</span> '
            f'<a href="{escape(aff, quote=True)}" target="_blank" '
            f'rel="sponsored noopener noreferrer">{escape(aff)}</a></p>'
        )
    bits.extend(["</div>", "</article>"])
    return "\n".join(bits)


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

    return _shell(
        title=f"{SITE_NAME_EN} — {heading}",
        css_href=links.css,
        lang=lang,
        description=_page_description(lang),
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
) -> str:
    return _shell(
        title=f"{SITE_NAME_EN} — {heading}",
        css_href=links.css,
        lang=lang,
        description=_page_description(lang),
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
    )


def _render_empty_home(lang: str, site: SiteConfig) -> str:
    if lang == "en":
        links = _links_root("en", lang_other="zh/index.html")
        msg = "No digests published yet. Run publish then build."
    else:
        links = _links_root("zh", lang_other="../index.html")
        msg = "尚无已发布摘要。请先 publish 再 build。"
    return _shell(
        title=SITE_NAME_EN,
        css_href=links.css,
        lang=lang,
        description=_page_description(lang),
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


def _render_missing_home(lang: str, day: date, site: SiteConfig) -> str:
    day_s = day.isoformat()
    if lang == "en":
        links = _links_root("en", lang_other="zh/index.html")
        msg = f"English digest for {day_s} is missing."
    else:
        links = _links_root("zh", lang_other="../index.html")
        msg = f"{day_s} 的中文摘要缺失。"
    return _shell(
        title=f"{SITE_NAME_EN} — {day_s}",
        css_href=links.css,
        lang=lang,
        description=_page_description(lang),
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
) -> str:
    html_lang = "zh-Hans" if lang == "zh" else "en"
    desc = description if description is not None else _page_description(lang)
    favicon = _favicon_href(css_href)
    fonts = (
        "https://fonts.googleapis.com/css2?"
        "family=Bricolage+Grotesque:opsz,wght@12..96,600;700&amp;"
        "family=Source+Serif+4:opsz,wght@8..60,400;600&amp;"
        "family=Source+Sans+3:wght@400;500;600&amp;display=swap"
    )
    return f"""<!DOCTYPE html>
<html lang="{html_lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <meta name="description" content="{escape(desc)}">
  <meta name="theme-color" content="#eceff3" media="(prefers-color-scheme: light)">
  <meta name="theme-color" content="#12151a" media="(prefers-color-scheme: dark)">
  <meta property="og:title" content="{escape(title)}">
  <meta property="og:description" content="{escape(desc)}">
  <meta property="og:type" content="website">
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
  <rect width="32" height="32" rx="6" fill="#1e3a5f"/>
  <path fill="#eceff3"
    d="M8 22V10h3.4c2.8 0 4.5 1.5 4.5 3.8 0 1.5-.8 2.7-2.2 3.3L17.2 22h-3.1
       l-2.9-4.5H11V22H8zm3-7.2h.6c1.1 0 1.8-.6 1.8-1.5S12.7 12 11.6 12H11v2.8z"/>
</svg>
""".strip()


def _stylesheet() -> str:
    # Taste redesign: editorial digest; dials VARIANCE 8 / MOTION 6 / DENSITY 3
    return """
:root {
  --bg: #eceff3;
  --bg-elev: #f6f7f9;
  --ink: #16181d;
  --muted: #5c6570;
  --accent: #1e3a5f;
  --accent-hot: #0f6e7c;
  --line: #cfd5de;
  --focus: #1e3a5f;
  --shadow: 0 1px 0 rgba(22, 24, 29, 0.04);
  --font-display: "Bricolage Grotesque", "Avenir Next", sans-serif;
  --font-body: "Source Serif 4", "Palatino Linotype", serif;
  --font-ui: "Source Sans 3", "Segoe UI", sans-serif;
  --pad: clamp(1.25rem, 4vw, 2rem);
  --max: 42rem;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #12151a;
    --bg-elev: #1a1e26;
    --ink: #e8ecf1;
    --muted: #9aa3ad;
    --accent: #8eb4e0;
    --accent-hot: #5ec4c8;
    --line: #2c3340;
    --focus: #8eb4e0;
    --shadow: none;
  }
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  min-height: 100vh;
  font-family: var(--font-ui);
  background:
    linear-gradient(
      180deg,
      color-mix(in srgb, var(--accent) 6%, var(--bg)) 0%,
      var(--bg) 28%
    ),
    var(--bg);
  color: var(--ink);
  line-height: 1.55;
}
.site {
  margin: 0 auto;
  max-width: var(--max);
  padding: var(--pad) var(--pad) 3.5rem;
}
a {
  color: var(--accent);
  text-decoration-thickness: 1px;
  text-underline-offset: 0.18em;
  transition: color 0.2s ease, text-underline-offset 0.2s ease;
}
a:hover {
  color: var(--accent-hot);
  text-underline-offset: 0.28em;
}
a:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 3px;
  border-radius: 2px;
}
.site-header {
  margin-bottom: 1.75rem;
  animation: rise 0.55s ease both;
}
.brand-block { margin-bottom: 1.1rem; }
.brand {
  font-family: var(--font-display);
  font-size: clamp(2.1rem, 6vw, 2.85rem);
  font-weight: 700;
  letter-spacing: -0.035em;
  margin: 0 0 0.4rem;
  line-height: 1.05;
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
  font-size: 1.02rem;
  font-weight: 500;
  line-height: 1.4;
}
.site-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 0.85rem 1.25rem;
  align-items: center;
  justify-content: space-between;
  margin: 0 0 1.5rem;
  padding: 0.85rem 0;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  font-size: 0.9rem;
  font-weight: 600;
}
.nav-primary {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem 1.15rem;
}
.nav-primary a {
  color: var(--ink);
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
  padding: 0.35rem 0 0;
  animation: rise 0.65s 0.06s ease both;
}
.day-bar h1,
.page-title {
  font-family: var(--font-display);
  font-size: clamp(1.35rem, 3.5vw, 1.65rem);
  font-weight: 600;
  letter-spacing: -0.02em;
  margin: 0 0 0.25rem;
}
.day-bar .meta,
.meta {
  margin: 0;
  color: var(--muted);
  font-size: 0.86rem;
}
.feed {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.item {
  display: grid;
  grid-template-columns: 2.4rem 1fr;
  gap: 0.65rem 0.9rem;
  padding: 1.2rem 0;
  border-bottom: 1px solid var(--line);
  transition: background-color 0.2s ease, transform 0.2s ease;
}
.item:first-child { border-top: 1px solid var(--line); }
.item:hover {
  background: color-mix(in srgb, var(--bg-elev) 80%, transparent);
  transform: translateX(2px);
}
.item-index {
  font-family: var(--font-display);
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--accent-hot);
  letter-spacing: -0.02em;
  padding-top: 0.2rem;
  font-variant-numeric: tabular-nums;
}
.item-body { min-width: 0; }
.item h2 {
  font-family: var(--font-body);
  font-size: 1.12rem;
  font-weight: 600;
  margin: 0 0 0.45rem;
  line-height: 1.35;
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
  margin: 0 0 0.65rem;
  color: var(--muted);
  font-size: 0.8rem;
  font-family: var(--font-ui);
}
.badge {
  display: inline-block;
  border: 1px solid var(--line);
  background: var(--bg-elev);
  color: var(--accent);
  border-radius: 999px;
  padding: 0.1rem 0.5rem;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.03em;
  font-family: ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
}
.summary, .why, .affiliate {
  margin: 0.4rem 0 0;
  font-family: var(--font-body);
  font-size: 0.98rem;
  color: var(--ink);
}
.why {
  color: var(--muted);
  font-size: 0.88rem;
  font-family: var(--font-ui);
}
.affiliate {
  margin-top: 0.7rem;
  padding-top: 0.65rem;
  border-top: 1px dashed var(--line);
  font-size: 0.88rem;
  font-family: var(--font-ui);
  color: var(--muted);
}
.label {
  display: inline-block;
  font-family: var(--font-ui);
  font-size: 0.68rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--accent-hot);
  margin-right: 0.4rem;
}
.muted { color: var(--muted); }
.prose {
  font-family: var(--font-body);
  font-size: 1.05rem;
}
.prose p { margin: 0 0 0.95rem; }
.archive-list {
  list-style: none;
  margin: 0;
  padding: 0;
  border-top: 1px solid var(--line);
}
.archive-list li {
  margin: 0;
  border-bottom: 1px solid var(--line);
  padding: 0.95rem 0.15rem;
  line-height: 1.4;
  transition: transform 0.2s ease;
}
.archive-list li:hover { transform: translateX(2px); }
.archive-list a {
  color: var(--ink);
  font-family: var(--font-display);
  font-weight: 600;
  text-decoration: none;
  letter-spacing: -0.01em;
}
.archive-list a:hover { color: var(--accent-hot); }
.site-footer {
  margin-top: 2.75rem;
  padding-top: 1.15rem;
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
@keyframes rise {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  .site-header, .day-bar { animation: none; }
  .item, .archive-list li { transition: none; }
  .item:hover, .archive-list li:hover { transform: none; }
}
@media (max-width: 480px) {
  .item { grid-template-columns: 1.9rem 1fr; gap: 0.45rem 0.65rem; }
  .site-nav { align-items: flex-start; }
}
""".strip()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build AI Hot Digest static site.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _parse_args(argv)
    config = load_app_config()
    build_site(
        content_dir=Path(config.paths.content_digests_dir),
        output_dir=Path(config.paths.site_output_dir),
        site=config.site,
    )
    print(f"[ai_hot] site built → {config.paths.site_output_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
