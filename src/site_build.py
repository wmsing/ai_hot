"""把 content/digests/*.md 建成极简静态站 → public/。"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path

from src.config import load_app_config
from src.deep_summarize import hot_topic_display_title
from src.digest import _parse_score_line, has_usable_digest_summary
from src.leaderboard import fetch_arena_boards
from src.models import (
    ArenaLeaderboard,
    DigestDocument,
    DigestItem,
    HotTopicSnapshot,
    HotTopicSnapshotItem,
    SiteConfig,
)
from src.site_parse import parse_digest_markdown
from src.timeutil import format_published, parse_published

_DIGEST_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.(en|zh)\.md$")
_ITEM_MP3_RE = re.compile(r"^(\d{3})\.mp3$")
_YT_WATCH_RE = re.compile(
    r"(?:youtube\.com/watch\?(?:[^#]*&)?v=|youtu\.be/)([A-Za-z0-9_-]{11})",
    re.IGNORECASE,
)

SITE_NAME_EN = "AI Hot Digest"
SITE_TAGLINE_EN = "Daily AI highlights from HN & official feeds"
SITE_TAGLINE_ZH = "AI 热点摘要"
_REPO_ISSUES = "https://github.com/wmsing/ai_hot/issues"
# 首页筛选 Tab（与 DigestItem.tag / data-tag 对齐；可扩展）
_FEED_FILTER_TAGS: tuple[tuple[str, str, str], ...] = (
    ("paper", "Paper", "论文"),
    ("video", "Video", "视频"),
)
# key, en, zh, 匹配的 data-source 集合（族）
_FEED_FILTER_SOURCES: tuple[tuple[str, str, str, frozenset[str]], ...] = (
    ("hn", "HN", "HN", frozenset({"hn"})),
    (
        "openai",
        "OpenAI",
        "OpenAI",
        frozenset({"rss:openai", "rss:openai_youtube"}),
    ),
    (
        "apple",
        "Apple",
        "Apple",
        frozenset({"rss:apple_newsroom", "rss:apple_ml"}),
    ),
    ("google_ai", "Google", "Google", frozenset({"rss:google_ai"})),
    ("deepmind", "DeepMind", "DeepMind", frozenset({"rss:deepmind"})),
    ("anthropic", "Anthropic", "Anthropic", frozenset({"rss:anthropic"})),
    (
        "huggingface",
        "Hugging Face",
        "Hugging Face",
        frozenset({"rss:huggingface"}),
    ),
    ("nvidia_ai", "NVIDIA", "NVIDIA", frozenset({"rss:nvidia_ai"})),
    ("qbitai", "QbitAI", "量子位", frozenset({"rss:qbitai"})),
    ("claude", "Claude", "Claude", frozenset({"rss:claude_youtube"})),
    ("grok", "Grok", "Grok", frozenset({"rss:grok_youtube"})),
)

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
class TimelineEntry:
    """首页时间线条目：group_day 为 UTC 发布日（sticky 用）。"""

    group_day: date
    item: DigestItem
    # 口播 mp3 对齐归档日 + digest 原序号（首页展示 index 可能被重排）
    source_day: date
    source_index: int


@dataclass(frozen=True)
class PageLinks:
    css: str
    home: str
    hot: str
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
    hot_topics: HotTopicSnapshot | None = None,
    audio_dir: Path | None = None,
    audio_dirs: list[Path] | None = None,
    audio_dirs_by_lang: dict[str, list[Path]] | None = None,
    bgm_path: Path | None = None,
) -> None:
    """扫描 content_dir，写出完整静态站到 output_dir。

    arena_boards 写入独立 Arena 页；首页与归档不嵌入榜单。
    audio_dirs / audio_dir：兼容旧调用（视为 zh）。
    audio_dirs_by_lang：按语言分别拷贝 mp3 根目录。
    bgm_path：可选垫乐；缺省时在音频根目录查找 bgm.mp3。
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
    (output_dir / "_headers").write_text(
        "/*\n  Referrer-Policy: strict-origin-when-cross-origin\n",
        encoding="utf-8",
    )
    roots: list[Path] = []
    if audio_dirs:
        roots.extend(audio_dirs)
    elif audio_dir is not None:
        roots.append(audio_dir)
    # tests 仍可传 audio_dirs 当作 zh；正式构建传 audio_dirs_by_lang
    audio_available: dict[str, set[tuple[str, int]]] = {
        "zh": set(),
        "en": set(),
    }
    if audio_dirs_by_lang is not None:
        for lang_key, lang_roots in audio_dirs_by_lang.items():
            audio_available[lang_key] = _copy_speak_audio_roots(
                lang_roots, output_dir, days, lang=lang_key
            )
    elif roots:
        audio_available["zh"] = _copy_speak_audio_roots(
            roots, output_dir, days, lang="zh"
        )

    bgm_candidates: list[Path] = []
    if bgm_path is not None:
        bgm_candidates.append(bgm_path)
    scan_roots: list[Path] = list(roots)
    if audio_dirs_by_lang is not None:
        for lang_roots in audio_dirs_by_lang.values():
            scan_roots.extend(lang_roots)
    seen_bgm: set[Path] = set()
    for root in scan_roots:
        for candidate in (root / "bgm.mp3", root.parent / "bgm.mp3"):
            resolved = candidate.resolve() if candidate.exists() else candidate
            if resolved in seen_bgm:
                continue
            seen_bgm.add(resolved)
            bgm_candidates.append(candidate)
    has_bgm = _copy_site_bgm(bgm_candidates, output_dir)

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
    hot_snap = hot_topics if hot_topics is not None else HotTopicSnapshot()
    _write(output_dir / "hot.html", _render_hot_page("en", cfg, hot_snap))
    _write(output_dir / "zh" / "hot.html", _render_hot_page("zh", cfg, hot_snap))
    sitemap_urls.extend(
        [_abs_url(origin, "/hot.html"), _abs_url(origin, "/zh/hot.html")]
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

    (output_dir / "feed.js").write_text(_feed_js(), encoding="utf-8")
    en_timeline = _timeline_items(days, "en")
    zh_timeline = _timeline_items(days, "zh")

    if en_timeline:
        _write(
            output_dir / "index.html",
            _render_home_timeline(
                items=en_timeline,
                lang="en",
                has_other_lang=bool(zh_timeline),
                site=cfg,
                as_of=_latest_generated_at(days, "en"),
                audio_available=audio_available,
                has_bgm=has_bgm,
            ),
        )
    else:
        _write(output_dir / "index.html", _render_empty_home("en", cfg))
    sitemap_urls.append(_abs_url(origin, "/"))

    if zh_timeline:
        _write(
            output_dir / "zh" / "index.html",
            _render_home_timeline(
                items=zh_timeline,
                lang="zh",
                has_other_lang=bool(en_timeline),
                site=cfg,
                as_of=_latest_generated_at(days, "zh"),
                audio_available=audio_available,
                has_bgm=has_bgm,
            ),
        )
    else:
        _write(output_dir / "zh" / "index.html", _render_empty_home("zh", cfg))
    sitemap_urls.append(_abs_url(origin, "/zh/"))

    for idx, day_files in enumerate(days):
        day_s = day_files.day.isoformat()
        en_doc = _load_doc(day_files.en)
        zh_doc = _load_doc(day_files.zh)
        has_zh = zh_doc is not None
        has_en = en_doc is not None
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
                newer_is_latest=newer_is_latest,
                audio_available=audio_available,
                has_bgm=has_bgm,
            )
            _write(output_dir / "archive" / day_s / "index.html", archive_page)
            sitemap_urls.append(_abs_url(origin, en_archive_path))

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
                newer_is_latest=newer_is_latest,
                audio_available=audio_available,
                has_bgm=has_bgm,
            )
            _write(
                output_dir / "zh" / "archive" / day_s / "index.html",
                archive_page,
            )
            sitemap_urls.append(_abs_url(origin, zh_archive_path))

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
        hot=disclosure.replace("disclosure.html", "hot.html"),
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
    """仅显示对方语言入口：EN 页 →「中文」，中文页 →「EN」。"""
    label = "中文" if lang == "en" else "EN"
    if other_href:
        inner = (
            f'<a href="{escape(other_href)}" class="lang-toggle" '
            f'hreflang="{"zh-Hans" if lang == "en" else "en"}">{label}</a>'
        )
    else:
        inner = f'<span class="lang-toggle muted" aria-disabled="true">{label}</span>'
    return f'<div class="lang-switch">{inner}</div>'


def _chrome_brand_nav(
    lang: str,
    links: PageLinks,
    *,
    as_of: str | None = None,
) -> str:
    """品牌头 + sticky 导航（nav 必须在 header 外，否则吸顶只撑过标题高度）。"""
    return (
        '<header class="site-header">'
        '<div class="brand-block">'
        f'<p class="brand"><a href="{escape(links.brand_home)}">'
        f"{escape(SITE_NAME_EN)}</a></p>"
        f"{_brand_sub(lang, as_of=as_of)}"
        "</div>"
        "</header>"
        f"{_main_nav(lang, links)}"
    )


def _main_nav(lang: str, links: PageLinks) -> str:
    if lang == "en":
        home_l, hot_l, arena_l = "Home", "Trending", "AI Models"
        about_l, privacy_l = "About", "Privacy"
        nav_label = "Primary"
    else:
        home_l, hot_l, arena_l = "首页", "今日热搜", "AI 模型榜"
        about_l, privacy_l = "关于", "隐私"
        nav_label = "主导航"
    parts = [
        f'<a href="{escape(links.home)}">{home_l}</a>',
        f'<a href="{escape(links.hot)}">{hot_l}</a>',
        f'<a href="{escape(links.arena)}">{arena_l}</a>',
        f'<a href="{escape(links.about)}">{about_l}</a>',
        f'<a href="{escape(links.privacy)}">{privacy_l}</a>',
    ]
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
        archive_l, about_l, privacy_l, disc_l = (
            "Archive",
            "About",
            "Privacy",
            "Disclosure",
        )
    else:
        archive_l, about_l, privacy_l, disc_l = (
            "归档",
            "关于",
            "隐私",
            "披露说明",
        )
    return (
        f"{lead} "
        f'<a href="{escape(links.archive)}">{archive_l}</a> · '
        f'<a href="{escape(links.about)}">{about_l}</a> · '
        f'<a href="{escape(links.privacy)}">{privacy_l}</a> · '
        f'<a href="{escape(links.disclosure)}">{disc_l}</a>.'
    )


def _format_tagline_as_of(raw: str) -> str:
    """digest generated_at → `YYYY-MM-DD`（UTC）；解析失败返回空。"""
    text = raw.strip()
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}"


def _latest_generated_at(days: list[DayFiles], lang: str) -> str:
    """取最新一日 digest 的 generated_at，格式化为 tagline 用。"""
    for day_files in days:
        path = day_files.en if lang == "en" else day_files.zh
        doc = _load_doc(path)
        if doc is not None and doc.generated_at:
            formatted = _format_tagline_as_of(doc.generated_at)
            if formatted:
                return formatted
    return ""


def _brand_sub(lang: str, *, as_of: str | None = None) -> str:
    tagline = SITE_TAGLINE_ZH if lang == "zh" else SITE_TAGLINE_EN
    if as_of:
        if lang == "zh":
            tagline = f"{tagline} 截至 {as_of}"
        else:
            tagline = f"{tagline} · as of {as_of}"
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
    """page: home|archive|arena|hot|about|privacy|disclosure|empty|missing"""
    en = {
        "home": SITE_TAGLINE_EN,
        "archive": "Browse archived daily AI Hot Digests by date.",
        "arena": "AI model leaderboards from Arena.ai (third-party scores).",
        "hot": (
            "Cross-source AI trending topics from HN, Reddit, Google News, and more."
        ),
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
        "hot": "跨源 AI 今日热搜：HN、Reddit、Google News 等。",
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


def _item_sort_ts(item: DigestItem, day: date) -> float:
    """首页排序键：有 published 用发布时间，否则回退归档日。"""
    dt = parse_published(item.published)
    if dt is not None:
        return dt.timestamp()
    fallback = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return fallback.timestamp()


def _item_group_day(item: DigestItem, archive_day: date) -> date:
    """时间线 sticky 日：UTC 发布日；无 published 则用归档日。"""
    dt = parse_published(item.published)
    if dt is not None:
        return dt.astimezone(timezone.utc).date()
    return archive_day


def _timeline_items(days: list[DayFiles], lang: str) -> list[TimelineEntry]:
    """跨日合并：按 published 新→旧；同 URL 保留更新的一条。"""
    by_url: dict[str, tuple[float, TimelineEntry]] = {}
    orphans: list[tuple[float, TimelineEntry]] = []
    for day_files in days:
        path = day_files.en if lang == "en" else day_files.zh
        doc = _load_doc(path)
        if doc is None:
            continue
        for item in doc.items:
            if not has_usable_digest_summary(item.summary, title=item.title):
                continue
            ts = _item_sort_ts(item, day_files.day)
            group_day = _item_group_day(item, day_files.day)
            entry = TimelineEntry(
                group_day=group_day,
                item=item,
                source_day=day_files.day,
                source_index=item.index,
            )
            url = item.url.strip()
            if not url:
                orphans.append((ts, entry))
                continue
            prev = by_url.get(url)
            if prev is None or ts > prev[0]:
                by_url[url] = (ts, entry)
    ranked = list(by_url.values()) + orphans
    ranked.sort(key=lambda pair: (-pair[0], pair[1].item.url))
    out: list[TimelineEntry] = []
    for idx, (_, entry) in enumerate(ranked, start=1):
        out.append(
            TimelineEntry(
                group_day=entry.group_day,
                item=entry.item.model_copy(update={"index": idx}),
                source_day=entry.source_day,
                source_index=entry.source_index,
            )
        )
    return out


def _asset_prefix(css_href: str) -> str:
    """从 styles.css 相对路径得到站点根前缀：'' / '../' / '../../'。"""
    normalized = css_href.replace("\\", "/")
    if "/" not in normalized:
        return ""
    return normalized.rsplit("/", 1)[0] + "/"


def _page_asset(path_from_root: str, css_href: str) -> str:
    """把站点根相对路径（可带前导 /）转成相对当前页的 URL。"""
    clean = path_from_root.lstrip("/")
    return f"{_asset_prefix(css_href)}{clean}"


def _audio_public_href(
    lang: str,
    day: date,
    index: int,
    *,
    css_href: str = "styles.css",
) -> str:
    return _page_asset(
        f"audio/{lang}/{day.isoformat()}/{index:03d}.mp3",
        css_href,
    )


def _resolve_audio_href(
    lang: str,
    *,
    source_day: date,
    source_index: int,
    audio_available: dict[str, set[tuple[str, int]]] | set[tuple[str, int]],
    css_href: str = "styles.css",
) -> str | None:
    if lang not in {"zh", "en"}:
        return None
    if isinstance(audio_available, dict):
        bucket = audio_available.get(lang, set())
    else:
        if lang != "zh":
            return None
        bucket = audio_available
    key = (source_day.isoformat(), source_index)
    if key not in bucket:
        return None
    return _audio_public_href(lang, source_day, source_index, css_href=css_href)


def _copy_speak_audio_roots(
    audio_srcs: list[Path],
    output_dir: Path,
    days: list[DayFiles],
    *,
    lang: str = "zh",
) -> set[tuple[str, int]]:
    """按顺序从多个根目录拷贝；已存在的文件不覆盖。"""
    available: set[tuple[str, int]] = set()
    for src in audio_srcs:
        available |= _copy_speak_audio(
            src, output_dir, days, lang=lang, skip_existing=True
        )
    return available


def _copy_speak_audio(
    audio_src: Path | None,
    output_dir: Path,
    days: list[DayFiles],
    *,
    lang: str = "zh",
    skip_existing: bool = False,
) -> set[tuple[str, int]]:
    """把 speak mp3 拷到 public/audio/{lang}/{day}/；返回可用 (day, index)。"""
    available: set[tuple[str, int]] = set()
    if audio_src is None or not audio_src.is_dir() or not days:
        return available
    latest = days[0].day.isoformat()
    for day_files in days:
        day_s = day_files.day.isoformat()
        src_day = audio_src / day_s
        files: list[Path] = []
        if src_day.is_dir():
            files = sorted(src_day.glob("*.mp3"))
        elif day_s == latest:
            files = sorted(
                p for p in audio_src.glob("*.mp3") if _ITEM_MP3_RE.match(p.name)
            )
        if not files:
            continue
        dest = output_dir / "audio" / lang / day_s
        dest.mkdir(parents=True, exist_ok=True)
        for path in files:
            match = _ITEM_MP3_RE.match(path.name)
            if match is None:
                continue
            index = int(match.group(1))
            if index <= 0:
                continue
            dest_file = dest / path.name
            if skip_existing and dest_file.is_file():
                available.add((day_s, index))
                continue
            shutil.copy2(path, dest_file)
            available.add((day_s, index))
    return available


def _attenuate_bgm_file(src: Path, dest: Path, *, db: float = -20.0) -> bool:
    """用 ffmpeg 压低垫乐响度；失败返回 False。"""
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(src),
                "-af",
                f"volume={db}dB",
                "-codec:a",
                "libmp3lame",
                "-q:a",
                "5",
                str(dest),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    return proc.returncode == 0 and dest.is_file() and dest.stat().st_size > 0


def _copy_site_bgm(candidates: list[Path], output_dir: Path) -> bool:
    """拷贝首个存在的 bgm.mp3 → public/audio/bgm.mp3。

    源文件建议已压低响度（content/audio/bgm.mp3）；有 ffmpeg 时再轻压 -6dB。
    """
    for src in candidates:
        if not src.is_file():
            continue
        dest_dir = output_dir / "audio"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "bgm.mp3"
        if not _attenuate_bgm_file(src, dest, db=-6.0):
            shutil.copy2(src, dest)
        return True
    return False


def _podcast_dock_html(
    lang: str,
    *,
    has_bgm: bool = False,
    css_href: str = "styles.css",
) -> str:
    if lang == "zh":
        mode_label = "伴读"
        prev_l, play_l, next_l = "上一", "播", "下一"
        prev_a, play_a, next_a = "上一条", "播放或暂停", "下一条"
        mode_a = "伴读播放或暂停"
    elif lang == "en":
        mode_label = "Listen"
        prev_l, play_l, next_l = "Prev", "Play", "Next"
        prev_a, play_a, next_a = "Previous", "Play or pause", "Next"
        mode_a = "Listen play or pause"
    else:
        return ""
    bgm_src = escape(_page_asset("audio/bgm.mp3", css_href), quote=True)
    bgm = (
        f'<audio id="site-bgm" src="{bgm_src}" loop preload="none"></audio>\n'
        if has_bgm
        else ""
    )
    return f"""
<audio id="site-audio" preload="none"></audio>
{bgm}<div class="podcast-dock" id="podcast-dock" hidden>
  <button type="button" class="podcast-mode" id="podcast-mode"
    aria-pressed="false" aria-label="{escape(mode_a)}">
    <span class="podcast-mode-icon podcast-mode-play" aria-hidden="true">
      <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">
        <path d="M8 5v14l11-7z"/>
      </svg>
    </span>
    <span class="podcast-mode-icon podcast-mode-pause" aria-hidden="true" hidden>
      <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">
        <path d="M6 5h4v14H6zm8 0h4v14h-4z"/>
      </svg>
    </span>
    <span class="podcast-mode-label">{escape(mode_label)}</span>
  </button>
  <div class="podcast-controls" id="podcast-controls" hidden>
    <button type="button" class="podcast-nav" id="podcast-prev"
      aria-label="{escape(prev_a)}">{escape(prev_l)}</button>
    <button type="button" class="podcast-nav podcast-play" id="podcast-play"
      aria-label="{escape(play_a)}">{escape(play_l)}</button>
    <button type="button" class="podcast-nav" id="podcast-next"
      aria-label="{escape(next_a)}">{escape(next_l)}</button>
    <span class="podcast-now" id="podcast-now"></span>
  </div>
</div>
""".strip()


def _render_day_sticky(day: date) -> str:
    day_s = day.isoformat()
    return (
        f'<div class="feed-day-sticky" data-day="{escape(day_s)}">'
        f'<time datetime="{escape(day_s)}">{escape(day_s)}</time>'
        f"</div>"
    )


def _render_feed_filter(lang: str) -> str:
    """首页筛选：全部 + tag（paper/video）+ 来源族；互斥单选。"""
    if lang == "zh":
        aria = "按标签或来源筛选"
        all_l = "全部"
    else:
        aria = "Filter by tag or source"
        all_l = "All"
    bits = [
        f'<nav class="feed-filter" role="tablist" aria-label="{escape(aria)}">',
        '<button type="button" class="feed-filter-tab is-active" role="tab" '
        'aria-selected="true" data-filter-kind="" data-filter="">'
        f"{escape(all_l)}</button>",
    ]
    for key, en_l, zh_l in _FEED_FILTER_TAGS:
        label = zh_l if lang == "zh" else en_l
        bits.append(
            '<button type="button" class="feed-filter-tab" role="tab" '
            'aria-selected="false" data-filter-kind="tag" '
            f'data-filter="{escape(key, quote=True)}">'
            f"{escape(label)}</button>"
        )
    for key, en_l, zh_l, sources in _FEED_FILTER_SOURCES:
        label = zh_l if lang == "zh" else en_l
        match = ",".join(sorted(sources))
        bits.append(
            '<button type="button" class="feed-filter-tab" role="tab" '
            'aria-selected="false" data-filter-kind="source" '
            f'data-filter="{escape(key, quote=True)}" '
            f'data-match="{escape(match, quote=True)}">'
            f"{escape(label)}</button>"
        )
    bits.append("</nav>")
    return "\n".join(bits)


def _render_timeline_html(
    entries: list[TimelineEntry],
    lang: str,
    *,
    affiliate_enabled: bool,
    audio_available: dict[str, set[tuple[str, int]]] | set[tuple[str, int]],
    prev_day: date | None = None,
    css_href: str = "styles.css",
) -> str:
    bits: list[str] = []
    last = prev_day
    for entry in entries:
        if entry.group_day != last:
            bits.append(_render_day_sticky(entry.group_day))
            last = entry.group_day
        audio_href = _resolve_audio_href(
            lang,
            source_day=entry.source_day,
            source_index=entry.source_index,
            audio_available=audio_available,
            css_href=css_href,
        )
        bits.append(
            _render_item(
                entry.item,
                lang,
                affiliate_enabled=affiliate_enabled,
                audio_href=audio_href,
            )
        )
    return "".join(bits)


def _feed_js() -> str:
    return r"""
(function () {
  var root = document.documentElement;
  var syncNavStickyBottom = function () {
    var nav = document.querySelector(".site-nav");
    if (!nav) return;
    var top = parseFloat(window.getComputedStyle(nav).top);
    if (isNaN(top)) top = 0;
    var bottom = top + nav.getBoundingClientRect().height;
    root.style.setProperty("--nav-sticky-bottom", bottom + "px");
  };
  if (document.querySelector(".feed-day-sticky")) {
    document.body.classList.add("has-day-sticky");
  }
  syncNavStickyBottom();
  window.addEventListener("resize", syncNavStickyBottom);

  var mobileReadMq = window.matchMedia("(max-width: 720px)");
  var feedScrollKey = "ai-hot-feed-scroll:" + location.pathname;

  var isMobileRead = function () {
    return mobileReadMq.matches;
  };

  var syncReadLinks = function () {
    var links = document.querySelectorAll("a.item-read");
    for (var i = 0; i < links.length; i++) {
      var a = links[i];
      if (isMobileRead()) {
        a.removeAttribute("target");
        a.setAttribute("data-same-tab", "1");
      } else if (a.getAttribute("data-same-tab") === "1") {
        a.setAttribute("target", "_blank");
        a.removeAttribute("data-same-tab");
      } else if (!a.getAttribute("target")) {
        a.setAttribute("target", "_blank");
      }
    }
  };

  var saveFeedScroll = function () {
    try {
      sessionStorage.setItem(feedScrollKey, String(window.scrollY || 0));
    } catch (e) {}
  };

  var restoreFeedScroll = function () {
    try {
      var raw = sessionStorage.getItem(feedScrollKey);
      if (raw == null) return;
      var y = parseInt(raw, 10);
      if (!(y > 0)) {
        sessionStorage.removeItem(feedScrollKey);
        return;
      }
      sessionStorage.removeItem(feedScrollKey);
      window.requestAnimationFrame(function () {
        window.scrollTo(0, y);
      });
    } catch (e) {}
  };

  syncReadLinks();
  if (mobileReadMq.addEventListener) {
    mobileReadMq.addEventListener("change", syncReadLinks);
  } else if (mobileReadMq.addListener) {
    mobileReadMq.addListener(syncReadLinks);
  }

  document.addEventListener(
    "click",
    function (ev) {
      var t = ev.target;
      if (!t || !t.closest) return;
      var link = t.closest("a.item-read");
      if (!link || !isMobileRead()) return;
      saveFeedScroll();
    },
    true
  );

  window.addEventListener("pageshow", restoreFeedScroll);

  var mountYoutube = function (wrap) {
    if (!wrap) return;
    var id = wrap.getAttribute("data-yt");
    if (!id || wrap.getAttribute("data-yt-mounted") === "1") return;
    if (location.protocol === "file:") {
      window.open(
        "https://www.youtube.com/watch?v=" + encodeURIComponent(id),
        "_blank",
        "noopener,noreferrer"
      );
      return;
    }
    wrap.setAttribute("data-yt-mounted", "1");
    var titleEl = wrap.closest(".item");
    var title = "";
    if (titleEl) {
      var h2 = titleEl.querySelector("h2");
      if (h2) title = h2.textContent || "";
    }
    var iframe = document.createElement("iframe");
    iframe.src =
      "https://www.youtube.com/embed/" +
      encodeURIComponent(id) +
      "?autoplay=1&rel=0";
    iframe.title = title || "YouTube";
    iframe.allow =
      "accelerometer; autoplay; clipboard-write; encrypted-media; " +
      "gyroscope; picture-in-picture; web-share";
    iframe.allowFullscreen = true;
    iframe.setAttribute("referrerpolicy", "strict-origin-when-cross-origin");
    iframe.setAttribute("loading", "eager");
    wrap.replaceChildren(iframe);
  };

  document.addEventListener("click", function (ev) {
    var t = ev.target;
    if (!t || !t.closest) return;
    var facade = t.closest(".yt-facade");
    if (!facade) return;
    ev.preventDefault();
    mountYoutube(facade.closest(".item-thumb-video"));
  });

  var bar = document.querySelector(".read-progress");
  if (bar) {
    var updateProgress = function () {
      var doc = document.documentElement;
      var max = doc.scrollHeight - window.innerHeight;
      var p = max > 0 ? window.scrollY / max : 0;
      if (p < 0) p = 0;
      if (p > 1) p = 1;
      bar.style.setProperty("--p", String(p));
    };
    window.addEventListener("scroll", updateProgress, { passive: true });
    window.addEventListener("resize", updateProgress);
    updateProgress();
  }

  var audio = document.getElementById("site-audio");
  var bgm = document.getElementById("site-bgm");
  var dock = document.getElementById("podcast-dock");
  var modeBtn = document.getElementById("podcast-mode");
  var controls = document.getElementById("podcast-controls");
  var playBtn = document.getElementById("podcast-play");
  var prevBtn = document.getElementById("podcast-prev");
  var nextBtn = document.getElementById("podcast-next");
  var nowEl = document.getElementById("podcast-now");
  var podcastOn = false;
  var currentItem = null;
  var isZh = (root.getAttribute("lang") || "").toLowerCase().indexOf("zh") === 0;
  var labelPlay = isZh ? "播" : "Play";
  var labelStop = isZh ? "停" : "Stop";
  var labelSpeakPlay = isZh ? "播放" : "Play";
  var labelSpeakPause = isZh ? "暂停" : "Pause";
  var labelNow = isZh ? "第 " : "#";
  var labelNowSuffix = isZh ? " 条" : "";
  var BGM_DUCK = 0.22;
  var SPEECH_VOL = 1;
  var bgmCtx = null;
  var bgmGain = null;
  var bgmWired = false;

  var setSpeakBtn = function (btn, playing) {
    if (!btn) return;
    btn.setAttribute("aria-pressed", playing ? "true" : "false");
    btn.setAttribute("aria-label", playing ? labelSpeakPause : labelSpeakPlay);
    var playIcon = btn.querySelector(".item-speak-play");
    var pauseIcon = btn.querySelector(".item-speak-pause");
    if (playIcon) playIcon.hidden = !!playing;
    if (pauseIcon) pauseIcon.hidden = !playing;
  };

  var wireBgmGraph = function () {
    if (!bgm || bgmWired) return;
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    try {
      bgmCtx = new AC();
      bgmGain = bgmCtx.createGain();
      bgmGain.gain.value = BGM_DUCK;
      var srcNode = bgmCtx.createMediaElementSource(bgm);
      srcNode.connect(bgmGain);
      bgmGain.connect(bgmCtx.destination);
      bgm.volume = 1;
      bgmWired = true;
    } catch (e) {
      bgmCtx = null;
      bgmGain = null;
      bgmWired = false;
    }
  };

  var ensureBgm = function () {
    if (!bgm) return;
    bgm.loop = true;
    wireBgmGraph();
    if (bgmGain) {
      bgmGain.gain.value = BGM_DUCK;
      bgm.volume = 1;
    } else {
      bgm.volume = BGM_DUCK;
    }
    if (bgmCtx && bgmCtx.state === "suspended") {
      bgmCtx.resume().catch(function () {});
    }
    var bp = bgm.play();
    if (bp && typeof bp.catch === "function") {
      bp.catch(function () {});
    }
  };

  var stopBgm = function () {
    if (!bgm) return;
    bgm.pause();
  };

  var audioItems = function () {
    return Array.prototype.slice.call(
      document.querySelectorAll(".item[data-audio]:not(.is-filtered-out)")
    );
  };

  var refreshDock = function () {
    if (!dock) return;
    var items = audioItems();
    if (!items.length) {
      dock.hidden = true;
      document.body.classList.remove("has-podcast-dock");
      return;
    }
    dock.hidden = false;
    document.body.classList.add("has-podcast-dock");
  };

  var syncPodcastToFilter = function () {};

  var setFabPlaying = function (playing) {
    if (!modeBtn) return;
    modeBtn.setAttribute("aria-pressed", playing ? "true" : "false");
    var playIcon = modeBtn.querySelector(".podcast-mode-play");
    var pauseIcon = modeBtn.querySelector(".podcast-mode-pause");
    if (playIcon) playIcon.hidden = !!playing;
    if (pauseIcon) pauseIcon.hidden = !playing;
  };

  var setPlayingUi = function (item, playing) {
    document.querySelectorAll(".item.is-playing").forEach(function (el) {
      el.classList.remove("is-playing");
    });
    document.querySelectorAll(".item-speak").forEach(function (btn) {
      setSpeakBtn(btn, false);
    });
    setFabPlaying(!!playing && !!item);
    if (!item) {
      if (playBtn) playBtn.textContent = labelPlay;
      if (nowEl) nowEl.textContent = "";
      return;
    }
    item.classList.add("is-playing");
    setSpeakBtn(item.querySelector(".item-speak"), playing);
    if (playBtn) playBtn.textContent = playing ? labelStop : labelPlay;
    var idx = item.querySelector(".item-index");
    if (nowEl) {
      nowEl.textContent = idx
        ? (labelNow + idx.textContent.trim() + labelNowSuffix)
        : "";
    }
  };

  var focusItem = function (item) {
    if (!item) return;
    try {
      item.scrollIntoView({ behavior: "smooth", block: "center" });
    } catch (e) {
      item.scrollIntoView(true);
    }
  };

  var playItem = function (item, fromPodcast) {
    if (!audio || !item) return;
    var src = item.getAttribute("data-audio");
    if (!src) return;
    if (!fromPodcast) {
      podcastOn = false;
      if (modeBtn) modeBtn.setAttribute("aria-pressed", "false");
      if (controls) controls.hidden = true;
      document.body.classList.remove("podcast-on");
    }
    currentItem = item;
    if (audio.getAttribute("src") !== src) {
      audio.setAttribute("src", src);
      audio.load();
    }
    setPlayingUi(item, true);
    focusItem(item);
    audio.volume = SPEECH_VOL;
    ensureBgm();
    var p = audio.play();
    if (p && typeof p.catch === "function") {
      p.catch(function () {
        setPlayingUi(item, false);
        stopBgm();
      });
    }
  };

  // 筛选变更：伴读只跟可见队列；正在播且当前被滤掉 → 跳到筛选首条（无则停）
  syncPodcastToFilter = function () {
    refreshDock();
    var items = audioItems();
    var stillVisible = !!(currentItem && items.indexOf(currentItem) >= 0);
    if (stillVisible) return;
    var wasPlaying = !!(audio && !audio.paused);
    if (wasPlaying && items.length) {
      podcastOn = true;
      if (controls) controls.hidden = false;
      document.body.classList.add("podcast-on");
      playItem(items[0], true);
      return;
    }
    if (wasPlaying || podcastOn) {
      podcastOn = false;
      if (modeBtn) modeBtn.setAttribute("aria-pressed", "false");
      if (controls) controls.hidden = true;
      document.body.classList.remove("podcast-on");
      if (audio) audio.pause();
      stopBgm();
    }
    currentItem = null;
    setPlayingUi(null, false);
  };

  var pauseAudio = function () {
    if (!audio) return;
    audio.pause();
    stopBgm();
    setPlayingUi(currentItem, false);
  };

  var stepPodcast = function (delta) {
    var items = audioItems();
    if (!items.length) return;
    var idx = currentItem ? items.indexOf(currentItem) : -1;
    var next = items[Math.max(0, Math.min(items.length - 1, idx + delta))];
    if (!next) next = items[0];
    playItem(next, true);
  };

  var toggleItem = function (item) {
    if (!audio || !item) return;
    if (currentItem === item && !audio.paused) {
      pauseAudio();
      return;
    }
    playItem(item, podcastOn);
  };

  if (audio && dock) {
    refreshDock();
    document.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.closest) return;
      var speakBtn = t.closest(".item-speak");
      if (speakBtn) {
        ev.preventDefault();
        ev.stopPropagation();
        var card = speakBtn.closest(".item[data-audio]");
        if (card) toggleItem(card);
        return;
      }
    });
    if (modeBtn) {
      modeBtn.addEventListener("click", function () {
        if (audio && !audio.paused && currentItem) {
          pauseAudio();
          return;
        }
        podcastOn = true;
        if (controls) controls.hidden = false;
        document.body.classList.add("podcast-on");
        var items = audioItems();
        if (!items.length) return;
        var start = currentItem && items.indexOf(currentItem) >= 0
          ? currentItem
          : items[0];
        playItem(start, true);
      });
    }
    if (playBtn) {
      playBtn.addEventListener("click", function () {
        if (!currentItem) {
          var items = audioItems();
          if (items[0]) playItem(items[0], podcastOn);
          return;
        }
        if (audio.paused) playItem(currentItem, podcastOn);
        else pauseAudio();
      });
    }
    if (prevBtn) prevBtn.addEventListener("click", function () { stepPodcast(-1); });
    if (nextBtn) nextBtn.addEventListener("click", function () { stepPodcast(1); });
    audio.addEventListener("ended", function () {
      if (podcastOn) {
        var items = audioItems();
        var idx = currentItem ? items.indexOf(currentItem) : -1;
        if (idx >= 0 && idx + 1 < items.length) {
          playItem(items[idx + 1], true);
          return;
        }
        podcastOn = false;
        if (modeBtn) modeBtn.setAttribute("aria-pressed", "false");
        if (controls) controls.hidden = true;
        document.body.classList.remove("podcast-on");
      }
      stopBgm();
      setPlayingUi(currentItem, false);
    });
    audio.addEventListener("play", function () { setPlayingUi(currentItem, true); });
    audio.addEventListener("pause", function () {
      if (audio.ended) return;
      setPlayingUi(currentItem, false);
    });
  }

  var feed = document.getElementById("feed");
  var filterRoot = document.querySelector(".feed-filter");
  var activeKind = "";
  var activeFilter = "";

  var readFilterFromUrl = function () {
    try {
      var sp = new URLSearchParams(window.location.search || "");
      var tag = (sp.get("tag") || "").toLowerCase();
      var source = (sp.get("source") || "").toLowerCase();
      if (tag) return { kind: "tag", key: tag };
      if (source) return { kind: "source", key: source };
      return { kind: "", key: "" };
    } catch (e) {
      return { kind: "", key: "" };
    }
  };

  var writeFilterToUrl = function (kind, key) {
    try {
      var url = new URL(window.location.href);
      url.searchParams.delete("tag");
      url.searchParams.delete("source");
      if (kind === "tag" && key) url.searchParams.set("tag", key);
      else if (kind === "source" && key) url.searchParams.set("source", key);
      var next = url.pathname + url.search + url.hash;
      if (
        next !==
        window.location.pathname + window.location.search + window.location.hash
      ) {
        history.replaceState(null, "", next);
      }
    } catch (e) {}
    var langLinks = document.querySelectorAll("a.lang-toggle[href]");
    for (var i = 0; i < langLinks.length; i++) {
      try {
        var raw = langLinks[i].getAttribute("href") || "";
        var pathOnly = raw.split("?")[0].split("#")[0];
        var q = "";
        if (kind === "tag" && key) q = "?tag=" + encodeURIComponent(key);
        else if (kind === "source" && key)
          q = "?source=" + encodeURIComponent(key);
        langLinks[i].setAttribute("href", pathOnly + q);
      } catch (e2) {}
    }
  };

  var syncFilterTabs = function () {
    if (!filterRoot) return;
    var tabs = filterRoot.querySelectorAll(".feed-filter-tab");
    var matched = false;
    for (var i = 0; i < tabs.length; i++) {
      var kind = (tabs[i].getAttribute("data-filter-kind") || "").toLowerCase();
      var key = (tabs[i].getAttribute("data-filter") || "").toLowerCase();
      var on = kind === activeKind && key === activeFilter;
      if (on) matched = true;
      tabs[i].classList.toggle("is-active", on);
      tabs[i].setAttribute("aria-selected", on ? "true" : "false");
    }
    if (!matched && tabs.length) {
      activeKind = "";
      activeFilter = "";
      tabs[0].classList.add("is-active");
      tabs[0].setAttribute("aria-selected", "true");
    }
  };

  var activeMatchSet = function () {
    if (!filterRoot || activeKind !== "source" || !activeFilter) return null;
    var tabs = filterRoot.querySelectorAll(".feed-filter-tab");
    for (var i = 0; i < tabs.length; i++) {
      var kind = (tabs[i].getAttribute("data-filter-kind") || "").toLowerCase();
      var key = (tabs[i].getAttribute("data-filter") || "").toLowerCase();
      if (kind === "source" && key === activeFilter) {
        var raw = tabs[i].getAttribute("data-match") || "";
        var parts = raw.split(",");
        var set = {};
        for (var p = 0; p < parts.length; p++) {
          var s = parts[p].trim().toLowerCase();
          if (s) set[s] = true;
        }
        return set;
      }
    }
    return null;
  };

  var applyTagFilter = function () {
    if (!feed) return;
    var matchSet = activeKind === "source" ? activeMatchSet() : null;
    var items = feed.querySelectorAll(".item");
    for (var i = 0; i < items.length; i++) {
      var el = items[i];
      var hide = false;
      if (activeKind === "tag" && activeFilter) {
        var tag = (el.getAttribute("data-tag") || "").toLowerCase();
        hide = tag !== activeFilter;
      } else if (activeKind === "source" && activeFilter) {
        var src = (el.getAttribute("data-source") || "").toLowerCase();
        hide = !(matchSet && matchSet[src]);
      }
      el.classList.toggle("is-filtered-out", hide);
    }
    var stickies = feed.querySelectorAll(".feed-day-sticky");
    for (var s = 0; s < stickies.length; s++) {
      var sticky = stickies[s];
      var next = sticky.nextElementSibling;
      var anyVisible = false;
      while (next && !next.classList.contains("feed-day-sticky")) {
        if (
          next.classList.contains("item") &&
          !next.classList.contains("is-filtered-out")
        ) {
          anyVisible = true;
          break;
        }
        next = next.nextElementSibling;
      }
      sticky.classList.toggle(
        "is-filtered-out",
        !!(activeKind && activeFilter) && !anyVisible
      );
    }
    syncPodcastToFilter();
  };

  if (filterRoot) {
    var allowed = { "\0": true };
    var tabsInit = filterRoot.querySelectorAll(".feed-filter-tab");
    for (var t = 0; t < tabsInit.length; t++) {
      var k0 = (tabsInit[t].getAttribute("data-filter-kind") || "").toLowerCase();
      var f0 = (tabsInit[t].getAttribute("data-filter") || "").toLowerCase();
      allowed[k0 + "\0" + f0] = true;
    }
    var initial = readFilterFromUrl();
    if (allowed[initial.kind + "\0" + initial.key]) {
      activeKind = initial.kind;
      activeFilter = initial.key;
    } else {
      activeKind = "";
      activeFilter = "";
    }
    syncFilterTabs();
    applyTagFilter();
    writeFilterToUrl(activeKind, activeFilter);

    filterRoot.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.closest) return;
      var tab = t.closest(".feed-filter-tab");
      if (!tab || !filterRoot.contains(tab)) return;
      activeKind = (tab.getAttribute("data-filter-kind") || "").toLowerCase();
      activeFilter = (tab.getAttribute("data-filter") || "").toLowerCase();
      syncFilterTabs();
      applyTagFilter();
      writeFilterToUrl(activeKind, activeFilter);
    });
  }
})();
""".strip()


def _favicon_href(css_href: str) -> str:
    return css_href.replace("styles.css", "favicon.svg")


def _feed_script_href(css_href: str) -> str:
    return css_href.replace("styles.css", "feed.js")


def _heat_level(score_line: str) -> int:
    """0=无分；1=<150；2=150–299；3=≥300。"""
    score, _ = _parse_item_scores(score_line)
    if score is None:
        return 0
    if score < 150:
        return 1
    if score < 300:
        return 2
    return 3


_SCORE_ZH_RE = re.compile(
    r"评分=(?P<score>n/a|\d+)(?:\s*\|\s*评论数=(?P<comments>n/a|\d+))?",
)


def _parse_item_scores(raw: str) -> tuple[int | None, int | None]:
    """兼容 EN `score=` 与 ZH `评分=` 行。"""
    score, comments = _parse_score_line(raw)
    if score is not None or comments is not None:
        return score, comments
    match = _SCORE_ZH_RE.search(raw.strip())
    if not match:
        return None, None
    score_s = match.group("score")
    comments_s = match.group("comments")
    score_out = None if score_s is None or score_s.lower() == "n/a" else int(score_s)
    comments_out = (
        None if comments_s is None or comments_s.lower() == "n/a" else int(comments_s)
    )
    return score_out, comments_out


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
    newer_is_latest: bool = False,
    audio_available: dict[str, set[tuple[str, int]]]
    | set[tuple[str, int]]
    | None = None,
    has_bgm: bool = False,
) -> str:
    day_s = day.isoformat()
    gen = escape(doc.generated_at) if doc.generated_at else "—"
    selected = doc.selected if doc.selected is not None else len(doc.items)
    if lang == "en":
        meta = f"Generated (UTC): {gen} · Selected: {selected}"
    else:
        meta = f"生成时间（UTC）：{gen} · 精选：{selected}"

    available: dict[str, set[tuple[str, int]]] | set[tuple[str, int]] = (
        audio_available or {}
    )
    items_html = "".join(
        _render_item(
            item,
            lang,
            affiliate_enabled=site.affiliate_enabled,
            audio_href=_resolve_audio_href(
                lang,
                source_day=day,
                source_index=item.index,
                audio_available=available,
                css_href=links.css,
            ),
        )
        for item in doc.items
        if has_usable_digest_summary(item.summary, title=item.title)
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
        newer_is_latest=newer_is_latest,
    )

    origin = _origin(site)
    en_path, zh_path = f"/archive/{day_s}/", f"/zh/archive/{day_s}/"
    canonical_path = en_path if lang == "en" else zh_path
    en_hl = en_path if lang == "en" or has_other_lang else None
    zh_hl = zh_path if lang == "zh" or has_other_lang else None

    script_src = _feed_script_href(links.css)
    podcast = _podcast_dock_html(lang, has_bgm=has_bgm, css_href=links.css)
    return _shell(
        title=f"{SITE_NAME_EN} — {day_s}",
        css_href=links.css,
        lang=lang,
        description=_digest_description(lang, day, selected),
        canonical=_abs_url(origin, canonical_path),
        hreflang=_hreflang_pairs(en_path=en_hl, zh_path=zh_hl, origin=origin),
        extra_scripts=f'<script src="{escape(script_src)}" defer></script>',
        body=f"""
<div class="read-progress" aria-hidden="true"></div>
<div class="site">
{_chrome_brand_nav(lang, links)}
  <div class="day-bar">
    <h1>{escape(day_s)}</h1>
    <p class="meta">{meta}</p>
    {day_nav}
  </div>
<main class="feed">
  {items_html}
</main>
<footer class="site-footer"><p>{_footer(lang, links, site)}</p></footer>
</div>
{podcast}
""",
    )


def _render_home_timeline(
    *,
    items: list[TimelineEntry],
    lang: str,
    has_other_lang: bool,
    site: SiteConfig,
    as_of: str = "",
    audio_available: dict[str, set[tuple[str, int]]]
    | set[tuple[str, int]]
    | None = None,
    has_bgm: bool = False,
) -> str:
    links = _links_digest_home(lang, "", has_other_lang)
    script_src = _feed_script_href(links.css)
    available: dict[str, set[tuple[str, int]]] | set[tuple[str, int]] = (
        audio_available or {}
    )

    items_html = _render_timeline_html(
        items,
        lang,
        affiliate_enabled=site.affiliate_enabled,
        audio_available=available,
        prev_day=None,
        css_href=links.css,
    )
    if not items_html:
        items_html = (
            '<p class="muted">No items.</p>'
            if lang == "en"
            else '<p class="muted">暂无条目。</p>'
        )

    origin = _origin(site)
    en_path, zh_path = "/", "/zh/"
    en_hl = en_path if lang == "en" or has_other_lang else None
    zh_hl = zh_path if lang == "zh" or has_other_lang else None
    desc = _static_description("home", lang)
    podcast = _podcast_dock_html(lang, has_bgm=has_bgm, css_href=links.css)

    return _shell(
        title=SITE_NAME_EN,
        css_href=links.css,
        lang=lang,
        description=desc,
        canonical=_abs_url(origin, en_path if lang == "en" else zh_path),
        hreflang=_hreflang_pairs(en_path=en_hl, zh_path=zh_hl, origin=origin),
        extra_scripts=f'<script src="{escape(script_src)}" defer></script>',
        body=f"""
<div class="read-progress" aria-hidden="true"></div>
<div class="site">
{_chrome_brand_nav(lang, links, as_of=as_of or None)}
{_render_feed_filter(lang)}
<main class="feed" id="feed">
  {items_html}
</main>
<footer class="site-footer"><p>{_footer(lang, links, site)}</p></footer>
</div>
{podcast}
""",
    )


def _day_nav(
    lang: str,
    *,
    older_day: date | None,
    newer_day: date | None,
    newer_is_latest: bool,
) -> str:
    """前一天=更早归档；后一天=更新归档（最新一天的后一天指向首页时间线）。"""
    if lang == "en":
        older_l, newer_l = "← Previous day", "Next day →"
    else:
        older_l, newer_l = "← 前一天", "后一天 →"

    older_href = _day_href(target=older_day, link_home=False)
    newer_href = _day_href(target=newer_day, link_home=newer_is_latest)

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
    link_home: bool,
) -> str | None:
    if target is None:
        return None
    day_s = target.isoformat()
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
{_chrome_brand_nav(lang, links)}
  <h1 class="page-title">{escape(heading)}</h1>
  <p class="meta arena-page-intro">{escape(intro)}</p>
<main class="feed arena-page">
  {body}
</main>
<footer class="site-footer"><p>{_footer(lang, links, site)}</p></footer>
</div>
""",
    )


def _hot_source_family(source: str) -> str:
    if ":" in source:
        return source.split(":", 1)[0]
    return source


def _hot_source_label(source: str, lang: str) -> str:
    family = _hot_source_family(source)
    en = {
        "hn": "HN",
        "reddit": "Reddit",
        "google_news": "Google News",
        "trends": "Google Trends",
        "threads": "Threads",
    }
    zh = {
        "hn": "HN",
        "reddit": "Reddit",
        "google_news": "谷歌新闻",
        "trends": "谷歌趋势",
        "threads": "Threads",
    }
    table = zh if lang == "zh" else en
    return table.get(family, family)


def _hot_item_sources(item: HotTopicSnapshotItem) -> list[str]:
    if item.sources:
        return item.sources
    family = _hot_source_family(item.source)
    return [family] if family else []


def _render_hot_source_badges(sources: list[str], lang: str) -> str:
    badges: list[str] = []
    for family in sources:
        label = _hot_source_label(family, lang)
        badges.append(
            f'<span class="badge badge-primary badge-source" '
            f'data-source="{escape(family, quote=True)}">'
            f"{escape(label)}</span>"
        )
    return f'<span class="badge-group">{"".join(badges)}</span>'


def _hot_meta_text(lang: str, item: HotTopicSnapshotItem) -> str:
    parts: list[str] = []
    heat_l = "热度" if lang == "zh" else "Heat"
    parts.append(f"{heat_l} {item.heat:.2f}")
    if item.published_at is not None:
        pub = format_published(item.published_at)
        if lang == "zh":
            parts.append(f"发布 {pub}")
        else:
            parts.append(f"Published {pub}")
    if item.score is not None and item.score > 0:
        if lang == "zh":
            parts.append(f"{item.score} 分")
        else:
            parts.append(f"{item.score} pts")
    if item.comments is not None and item.comments > 0:
        if lang == "zh":
            parts.append(f"{item.comments} 评论")
        else:
            parts.append(f"{item.comments} comments")
    return " · ".join(parts)


def _render_hot_item(item: HotTopicSnapshotItem, lang: str, *, index: int) -> str:
    labels = (
        {"read": "Read article"}
        if lang == "en"
        else {"read": "看正文"}
    )
    source = item.source.strip()
    sources = _hot_item_sources(item)
    source_attr = sources[0] if sources else _hot_source_family(source)
    source_badges = _render_hot_source_badges(sources, lang)
    title = escape(hot_topic_display_title(item, lang))
    url = item.url.strip()
    meta_text = _hot_meta_text(lang, item)
    heat = min(3, max(1, int(item.heat / 3) + 1))
    stagger_i = max(0, min(index - 1, 12))
    attrs = [
        'class="item"',
        f'data-heat="{heat}"',
        f'data-source="{escape(source_attr, quote=True)}"',
        f'style="--i: {stagger_i}"',
    ]
    if len(sources) >= 2:
        attrs.append('data-cross-source="true"')
    cross_fire = ""
    if len(sources) >= 2:
        fire_label = "多平台热议" if lang == "zh" else "Cross-source trending"
        cross_fire = (
            f'<span class="hot-fire" aria-label="{escape(fire_label)}">🔥</span>'
        )
    bits = [
        f"<article {' '.join(attrs)}>",
        f'<span class="item-index" aria-hidden="true">{index:02d}</span>',
        '<div class="item-body">',
        '<div class="item-meta">'
        f"{source_badges}"
        f"{cross_fire}"
        f'<span class="meta-text">{escape(meta_text)}</span>'
        "</div>",
    ]
    if url:
        bits.append(
            f'<h2><a href="{escape(url, quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">{title}</a></h2>'
        )
    else:
        bits.append(f"<h2>{title}</h2>")
    summary = (
        (item.summary_zh or item.summary or "")
        if lang == "zh"
        else (item.summary_en or item.summary or "")
    ).strip()
    if summary:
        bits.append(f'<p class="summary">{escape(summary)}</p>')
    if url:
        bits.append(
            f'<p class="item-actions">'
            f'<a class="item-read" href="{escape(url, quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">'
            f"{labels['read']}</a></p>"
        )
    bits.extend(["</div>", "</article>"])
    return "\n".join(bits)


def _render_hot_page(lang: str, site: SiteConfig, snapshot: HotTopicSnapshot) -> str:
    if lang == "en":
        links = _links_root("en", lang_other="zh/hot.html")
        heading = "Trending Today"
        intro = (
            "Cross-source AI hot topics ranked by engagement, recency, and source "
            "weight. Refreshed on each site build from HN, Reddit, Google News, "
            "and optional Google Trends / Threads."
        )
        empty = "No trending topics available right now. Run the hot topics probe."
        updated = "Updated"
    else:
        links = _links_root("zh", lang_other="../hot.html")
        heading = "今日热搜"
        intro = (
            "跨源 AI 热搜榜：按互动、时效与来源权重综合排序。"
            "站点每次构建时从 HN、Reddit、Google News 等拉取；"
            "可选 Google Trends / Threads。"
        )
        empty = "暂无热搜数据。请先运行 hot topics probe。"
        updated = "更新于"

    if snapshot.items:
        body = "\n".join(
            _render_hot_item(item, lang, index=idx)
            for idx, item in enumerate(snapshot.items, start=1)
        )
        as_of = _format_tagline_as_of(snapshot.generated_at.isoformat())
        if as_of:
            intro = f"{intro} {updated} {as_of} UTC."
    else:
        body = f'<p class="muted">{escape(empty)}</p>'

    origin = _origin(site)
    en_path, zh_path = "/hot.html", "/zh/hot.html"
    return _shell(
        title=f"{SITE_NAME_EN} — {heading}",
        css_href=links.css,
        lang=lang,
        description=_static_description("hot", lang),
        canonical=_abs_url(origin, en_path if lang == "en" else zh_path),
        hreflang=_hreflang_pairs(en_path=en_path, zh_path=zh_path, origin=origin),
        body=f"""
<div class="site">
{_chrome_brand_nav(lang, links)}
  <h1 class="page-title">{escape(heading)}</h1>
  <p class="meta arena-page-intro">{escape(intro)}</p>
<main class="feed hot-page">
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
    audio_href: str | None = None,
) -> str:
    labels = (
        {
            "affiliate": "Affiliate offer",
            "read": "Read article",
            "speak_play": "Play",
        }
        if lang == "en"
        else {
            "affiliate": "联盟推荐",
            "read": "看正文",
            "speak_play": "播放",
        }
    )
    title = escape(item.title)
    url = item.url.strip()

    header_bits: list[str] = []
    source = item.source.strip()
    if source:
        header_bits.append(
            f'<span class="badge badge-primary badge-source">{escape(source)}</span>'
        )
    tag_raw = item.tag.strip()
    tag_disp = _display_tag(tag_raw, lang)
    if tag_disp:
        header_bits.append(f'<span class="badge badge-tag">{escape(tag_disp)}</span>')
    score_val, comments_val = _parse_item_scores(item.score_line)
    meta_text = _format_meta_text(
        lang,
        published=item.published,
        score=score_val,
        comments=comments_val,
    )
    if meta_text:
        header_bits.append(f'<span class="meta-text">{escape(meta_text)}</span>')

    heat = _heat_level(item.score_line)
    stagger_i = max(0, min(max(item.index, 1) - 1, 12))
    attrs = [
        'class="item"',
        f'data-heat="{heat}"',
        f'style="--i: {stagger_i}"',
    ]
    if source:
        attrs.append(f'data-source="{escape(source, quote=True)}"')
    if tag_raw:
        attrs.append(f'data-tag="{escape(tag_raw, quote=True)}"')
    if audio_href:
        attrs.append(f'data-audio="{escape(audio_href, quote=True)}"')

    bits = [
        f"<article {' '.join(attrs)}>",
        f'<span class="item-index" aria-hidden="true">{item.index:02d}</span>',
        '<div class="item-body">',
    ]
    video_id = youtube_video_id(url)
    img = item.image_url.strip()
    if video_id:
        vid = escape(video_id, quote=True)
        thumb = escape(
            img or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            quote=True,
        )
        play_l = "播放视频" if lang == "zh" else "Play video"
        bits.append(
            f'<div class="item-thumb item-thumb-video" data-yt="{vid}">'
            f'<button type="button" class="yt-facade" '
            f'aria-label="{escape(play_l)}">'
            f'<img src="{thumb}" alt="" loading="lazy" decoding="async" />'
            f'<span class="yt-facade-play" aria-hidden="true">'
            f'<svg viewBox="0 0 24 24" width="28" height="28" fill="currentColor">'
            f'<path d="M8 5v14l11-7z"/></svg></span>'
            f"</button></div>"
        )
    elif img:
        src = escape(img, quote=True)
        bits.append(
            f'<div class="item-thumb">'
            f'<img src="{src}" alt="" loading="lazy" '
            f'referrerpolicy="no-referrer" decoding="async" /></div>'
        )
    if header_bits:
        bits.append(f'<div class="item-meta">{"".join(header_bits)}</div>')
    bits.append(f"<h2>{title}</h2>")
    if has_usable_digest_summary(item.summary, title=item.title):
        bits.append(f'<p class="summary">{escape(item.summary)}</p>')
    action_bits: list[str] = []
    if audio_href:
        action_bits.append(
            f'<button type="button" class="item-speak" aria-pressed="false" '
            f'aria-label="{escape(labels["speak_play"])}">'
            f'<span class="item-speak-icon item-speak-play" aria-hidden="true">'
            f'<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">'
            f'<path d="M8 5v14l11-7z"/></svg></span>'
            f'<span class="item-speak-icon item-speak-pause" aria-hidden="true" hidden>'
            f'<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">'
            f'<path d="M6 5h4v14H6zm8 0h4v14h-4z"/></svg></span>'
            f"</button>"
        )
    if url:
        action_bits.append(
            f'<a class="item-read" href="{escape(url, quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">'
            f"{labels['read']}</a>"
        )
    if action_bits:
        bits.append(f'<p class="item-actions">{" ".join(action_bits)}</p>')
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


def youtube_video_id(url: str) -> str | None:
    """从 watch?v= / youtu.be 链接提取 11 位 video id；Shorts 与其它形态返回 None。"""
    text = url.strip()
    if not text or "/shorts/" in text.lower():
        return None
    match = _YT_WATCH_RE.search(text)
    if not match:
        return None
    return match.group(1)


def _meta_day(raw: str) -> str:
    """元信息用短日期 YYYY-MM-DD（UTC）。"""
    text = raw.strip()
    if not text or text.lower() == "n/a":
        return ""
    dt = parse_published(text)
    if dt is None:
        return text.split()[0] if text.split() else text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date().isoformat()


def _format_meta_text(
    lang: str,
    *,
    published: str,
    score: int | None,
    comments: int | None,
) -> str:
    """次要元信息：2026-09-10 · 134 pts · 131 comments。"""
    bits: list[str] = []
    day = _meta_day(published)
    if day:
        bits.append(day)
    if score is not None:
        bits.append(f"{score} pts" if lang == "en" else f"{score} 分")
    if comments is not None:
        bits.append(f"{comments} comments" if lang == "en" else f"{comments} 评论")
    return " · ".join(bits)


def _display_tag(raw: str, lang: str) -> str:
    """paper → Paper / 论文；其它 tag 原样（ZH 未知则原样）。"""
    text = raw.strip()
    if not text:
        return ""
    key = text.lower()
    if key == "paper":
        return "论文" if lang == "zh" else "Paper"
    if key == "video":
        return "视频" if lang == "zh" else "Video"
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
{_chrome_brand_nav(lang, links)}
  <h1 class="page-title">{heading}</h1>
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
{_chrome_brand_nav(lang, links)}
  <h1 class="page-title">{heading}</h1>
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
            "<p>Each UTC day is archived as a bilingual digest (English and "
            "简体中文) with source links. On digest pages you can use "
            "<strong>Listen</strong> / per-item play to hear short spoken "
            "summaries (optional background music under speech). The "
            "<strong>AI Models</strong> page mirrors public arena-style "
            "leaderboard snapshots.</p>"
            "<p>Content is for personal monitoring and public reading—not "
            "investment or professional advice. Speech audio is "
            "machine-generated and may lag or omit items.</p>"
            f"<p>Contact: {contact}.</p>"
        )
    else:
        links = _links_root("zh", lang_other="../about.html")
        heading = "关于"
        body_text = (
            f"<p><strong>{escape(SITE_NAME_EN)}</strong>（{escape(SITE_TAGLINE_ZH)}）"
            f"是{owner}：汇总 Hacker News 与精选官方/镜像 RSS 中的 AI 相关热点。</p>"
            "<p>按 UTC 日归档为中英双语短摘要并附来源链接。摘要页提供"
            "<strong>伴读</strong>与条目播放，可听机读标题与简介（播放时可选垫乐）。"
            "<strong>AI 模型榜</strong>页展示公开竞技场类榜单快照。</p>"
            "<p>内容仅供个人巡检与公开阅读，不构成投资或专业建议。"
            "语音由机器生成，可能滞后或缺条。</p>"
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
            "<p>Listen / companion audio plays static MP3 files in your "
            "browser. Playback happens on your device; we do not run a "
            "separate listening analytics service. Background music, when "
            "present, is also a static asset shipped with the site.</p>"
            "<p>We do not sell personal data. Third-party pages you open via "
            "outbound links have their own privacy practices.</p>"
            "<p>If affiliate links are enabled, those partners may set "
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
            "<p>伴读/条目语音在浏览器中播放静态 MP3，播放发生在你的设备上；"
            "我们不另行收集收听分析。垫乐（如有）同样是随站分发的静态资源。</p>"
            "<p>我们不出售个人数据。你点击的外链站点遵循其各自隐私政策。</p>"
            "<p>若启用联盟链接，合作方可能按其政策设置 Cookie 或统计引荐；"
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
{_chrome_brand_nav(lang, links)}
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
{_chrome_brand_nav(lang, links)}
  <div class="day-bar">
    <h1>{escape(day_s)}</h1>
  </div>
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
    extra_scripts: str = "",
) -> str:
    html_lang = "zh-Hans" if lang == "zh" else "en"
    desc = description if description is not None else _page_description(lang)
    favicon = _favicon_href(css_href)
    fonts = (
        "https://fonts.googleapis.com/css2?"
        "family=Inter:wght@400;500;600;700&amp;display=swap"
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
    scripts = f"\n{extra_scripts}" if extra_scripts else ""
    return f"""<!DOCTYPE html>
<html lang="{html_lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <meta name="description" content="{escape(desc)}">
  <meta name="referrer" content="strict-origin-when-cross-origin">
  <meta name="theme-color" content="#0d0f17">
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
{scripts}
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


_DESIGN_SYSTEM_DIR = Path(__file__).resolve().parent.parent / "design-system"
_STYLESHEET_PARTS = ("tokens.css", "editorial.css")


def _stylesheet() -> str:
    return "\n\n".join(
        (_DESIGN_SYSTEM_DIR / name).read_text(encoding="utf-8").strip()
        for name in _STYLESHEET_PARTS
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build AI Hot Digest static site.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _parse_args(argv)
    config = load_app_config()
    boards = fetch_arena_boards(
        config.leaderboard,
        config.http,
        cache_dir=Path(config.paths.arena_cache_dir),
    )
    hot_path = Path(config.paths.hot_topics_path)
    hot_snapshot: HotTopicSnapshot | None = None
    try:
        from src.hot_topics_probe import (
            load_hot_topics_snapshot,
            run_probe,
            save_hot_topics_snapshot,
        )

        ranked = run_probe(config)
        save_hot_topics_snapshot(hot_path, ranked)
        hot_snapshot = load_hot_topics_snapshot(hot_path)
        if config.hot_topics.deep_summarize and hot_snapshot is not None:
            from src.deep_summarize import deep_summarize_hot_topics

            try:
                _, n = deep_summarize_hot_topics(
                    config,
                    snapshot_path=hot_path,
                    llm_flag=None,
                )
                if n:
                    hot_snapshot = load_hot_topics_snapshot(hot_path)
                print(f"[ai_hot] hot topics deep-summarized {n} item(s)")
            except Exception as ds_exc:
                print(
                    f"[ai_hot] hot topics deep-summarize skipped: {ds_exc}",
                    file=sys.stderr,
                )
    except Exception as exc:
        print(f"[ai_hot] hot topics probe skipped: {exc}", file=sys.stderr)
        hot_snapshot = load_hot_topics_snapshot(hot_path)
    if hot_snapshot is None:
        hot_snapshot = HotTopicSnapshot()

    output_dir = Path(config.paths.site_output_dir).resolve()

    def _audio_base(path: Path) -> Path:
        return path.parent if path.name in {"zh", "en"} else path

    content_audio = _audio_base(Path(config.paths.content_audio_dir))
    speak_audio = _audio_base(Path(config.paths.speak_audio_dir))
    build_site(
        content_dir=Path(config.paths.content_digests_dir),
        output_dir=output_dir,
        site=config.site,
        arena_boards=boards,
        hot_topics=hot_snapshot,
        audio_dirs_by_lang={
            "zh": [content_audio / "zh", speak_audio / "zh"],
            "en": [content_audio / "en", speak_audio / "en"],
        },
        bgm_path=content_audio / "bgm.mp3",
    )
    home = output_dir / "index.html"
    home_zh = output_dir / "zh" / "index.html"
    print(f"[ai_hot] site built → {output_dir}/")
    print(f"[ai_hot] open: {home.as_uri()}")
    if home_zh.is_file():
        print(f"[ai_hot] open zh: {home_zh.as_uri()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
