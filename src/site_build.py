"""把 content/digests/*.md 建成极简静态站 → public/。"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path

from src.config import load_app_config
from src.digest import _parse_score_line
from src.leaderboard import fetch_arena_boards
from src.models import ArenaLeaderboard, DigestDocument, DigestItem, SiteConfig
from src.site_parse import parse_digest_markdown
from src.timeutil import parse_published

_DIGEST_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.(en|zh)\.md$")
_ITEM_MP3_RE = re.compile(r"^(\d{3})\.mp3$")

SITE_NAME_EN = "AI Hot Digest"
SITE_TAGLINE_EN = "Daily AI highlights from HN & official feeds"
SITE_TAGLINE_ZH = "AI 热点摘要"
_REPO_ISSUES = "https://github.com/wmsing/ai_hot/issues"
HOME_PAGE_SIZE = 30

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
    audio_dir: Path | None = None,
    audio_dirs: list[Path] | None = None,
) -> None:
    """扫描 content_dir，写出完整静态站到 output_dir。

    arena_boards 写入独立 Arena 页；首页与归档不嵌入榜单。
    audio_dirs / audio_dir：speak mp3 根目录（如 content/audio/zh、out/audio/zh）。
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
    roots: list[Path] = []
    if audio_dirs:
        roots.extend(audio_dirs)
    elif audio_dir is not None:
        roots.append(audio_dir)
    audio_available = _copy_speak_audio_roots(roots, output_dir, days)

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

    (output_dir / "feed.js").write_text(_feed_js(), encoding="utf-8")
    en_timeline = _timeline_items(days, "en")
    zh_timeline = _timeline_items(days, "zh")
    _write_feed_json_pages(
        output_dir,
        lang="en",
        items=en_timeline,
        affiliate_enabled=cfg.affiliate_enabled,
        audio_available=audio_available,
    )
    _write_feed_json_pages(
        output_dir,
        lang="zh",
        items=zh_timeline,
        affiliate_enabled=cfg.affiliate_enabled,
        audio_available=audio_available,
    )

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
        home_l, arena_l = "Home", "AI Models"
        about_l, privacy_l = "About", "Privacy"
        nav_label = "Primary"
    else:
        home_l, arena_l = "首页", "AI 模型榜"
        about_l, privacy_l = "关于", "隐私"
        nav_label = "主导航"
    parts = [
        f'<a href="{escape(links.home)}">{home_l}</a>',
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


def _item_sort_ts(item: DigestItem, day: date) -> float:
    dt = parse_published(item.published)
    if dt is not None:
        return dt.timestamp()
    fallback = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return fallback.timestamp()


def _item_group_day(item: DigestItem, archive_day: date) -> date:
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


def _audio_public_href(day: date, index: int) -> str:
    return f"/audio/zh/{day.isoformat()}/{index:03d}.mp3"


def _resolve_audio_href(
    lang: str,
    *,
    source_day: date,
    source_index: int,
    audio_available: set[tuple[str, int]],
) -> str | None:
    if lang != "zh":
        return None
    key = (source_day.isoformat(), source_index)
    if key not in audio_available:
        return None
    return _audio_public_href(source_day, source_index)


def _copy_speak_audio_roots(
    audio_srcs: list[Path],
    output_dir: Path,
    days: list[DayFiles],
) -> set[tuple[str, int]]:
    """按顺序从多个根目录拷贝；已存在的文件不覆盖。"""
    available: set[tuple[str, int]] = set()
    for src in audio_srcs:
        available |= _copy_speak_audio(src, output_dir, days, skip_existing=True)
    return available


def _copy_speak_audio(
    audio_src: Path | None,
    output_dir: Path,
    days: list[DayFiles],
    *,
    skip_existing: bool = False,
) -> set[tuple[str, int]]:
    """把 speak mp3 拷到 public/audio/zh/{day}/；返回可用 (day, index)。"""
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
        dest = output_dir / "audio" / "zh" / day_s
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


def _podcast_dock_html(lang: str) -> str:
    if lang != "zh":
        return ""
    return """
<audio id="site-audio" preload="none"></audio>
<div class="podcast-dock" id="podcast-dock" hidden>
  <button type="button" class="podcast-mode" id="podcast-mode"
    aria-pressed="false" aria-label="伴读播放或暂停">
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
    <span class="podcast-mode-label">伴读</span>
  </button>
  <div class="podcast-controls" id="podcast-controls" hidden>
    <button type="button" class="podcast-nav" id="podcast-prev"
      aria-label="上一条">上一</button>
    <button type="button" class="podcast-nav podcast-play" id="podcast-play"
      aria-label="播放或暂停">播</button>
    <button type="button" class="podcast-nav" id="podcast-next"
      aria-label="下一条">下一</button>
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


def _render_timeline_html(
    entries: list[TimelineEntry],
    lang: str,
    *,
    affiliate_enabled: bool,
    audio_available: set[tuple[str, int]],
    prev_day: date | None = None,
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


def _write_feed_json_pages(
    output_dir: Path,
    *,
    lang: str,
    items: list[TimelineEntry],
    affiliate_enabled: bool,
    audio_available: set[tuple[str, int]],
) -> None:
    """page 0 在首页 HTML；从 1 起写 feed/{lang}/{n}.html 分片。"""
    if len(items) <= HOME_PAGE_SIZE:
        return
    feed_dir = output_dir / "feed" / lang
    page_count = (len(items) + HOME_PAGE_SIZE - 1) // HOME_PAGE_SIZE
    for page_i in range(1, page_count):
        start = page_i * HOME_PAGE_SIZE
        chunk = items[start : start + HOME_PAGE_SIZE]
        prev_day = items[start - 1].group_day
        inner = _render_timeline_html(
            chunk,
            lang,
            affiliate_enabled=affiliate_enabled,
            audio_available=audio_available,
            prev_day=prev_day,
        )
        next_page: int | None = page_i + 1 if page_i + 1 < page_count else None
        next_attr = "" if next_page is None else str(next_page)
        html = (
            f'<div class="feed-chunk" data-next="{escape(next_attr)}">{inner}</div>\n'
        )
        _write(feed_dir / f"{page_i}.html", html)


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
  var dock = document.getElementById("podcast-dock");
  var modeBtn = document.getElementById("podcast-mode");
  var controls = document.getElementById("podcast-controls");
  var playBtn = document.getElementById("podcast-play");
  var prevBtn = document.getElementById("podcast-prev");
  var nextBtn = document.getElementById("podcast-next");
  var nowEl = document.getElementById("podcast-now");
  var podcastOn = false;
  var currentItem = null;

  var audioItems = function () {
    return Array.prototype.slice.call(document.querySelectorAll(".item[data-audio]"));
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
      btn.setAttribute("aria-pressed", "false");
      btn.textContent = "播";
    });
    setFabPlaying(!!playing && !!item);
    if (!item) {
      if (playBtn) playBtn.textContent = "播";
      if (nowEl) nowEl.textContent = "";
      return;
    }
    item.classList.add("is-playing");
    var cardBtn = item.querySelector(".item-speak");
    if (cardBtn) {
      cardBtn.setAttribute("aria-pressed", playing ? "true" : "false");
      cardBtn.textContent = playing ? "停" : "播";
    }
    if (playBtn) playBtn.textContent = playing ? "停" : "播";
    var idx = item.querySelector(".item-index");
    if (nowEl) nowEl.textContent = idx ? ("第 " + idx.textContent.trim() + " 条") : "";
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
    var p = audio.play();
    if (p && typeof p.catch === "function") {
      p.catch(function () {
        setPlayingUi(item, false);
      });
    }
  };

  var pauseAudio = function () {
    if (!audio) return;
    audio.pause();
    setPlayingUi(currentItem, false);
  };

  var toggleItem = function (item) {
    if (!audio || !item) return;
    if (currentItem === item && !audio.paused) {
      pauseAudio();
      return;
    }
    playItem(item, podcastOn);
  };

  var stepPodcast = function (delta) {
    var items = audioItems();
    if (!items.length) return;
    var idx = currentItem ? items.indexOf(currentItem) : -1;
    var next = items[Math.max(0, Math.min(items.length - 1, idx + delta))];
    if (!next) next = items[0];
    playItem(next, true);
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
      setPlayingUi(currentItem, false);
    });
    audio.addEventListener("play", function () { setPlayingUi(currentItem, true); });
    audio.addEventListener("pause", function () {
      if (audio.ended) return;
      setPlayingUi(currentItem, false);
    });
  }

  var btn = document.getElementById("load-more");
  var feed = document.getElementById("feed");
  if (!btn || !feed) return;
  btn.addEventListener("click", function () {
    var next = btn.getAttribute("data-next");
    var base = btn.getAttribute("data-feed-base");
    if (!next || !base) return;
    btn.disabled = true;
    fetch(base + "/" + next)
      .then(function (res) {
        if (!res.ok) throw new Error("feed fetch failed");
        return res.text();
      })
      .then(function (text) {
        var wrap = document.createElement("div");
        wrap.innerHTML = text;
        var chunk = wrap.querySelector(".feed-chunk");
        if (!chunk) throw new Error("feed chunk missing");
        feed.insertAdjacentHTML("beforeend", chunk.innerHTML);
        var more = chunk.getAttribute("data-next");
        if (!more) {
          btn.remove();
        } else {
          btn.setAttribute("data-next", more);
          btn.disabled = false;
        }
        refreshDock();
      })
      .catch(function () {
        btn.disabled = false;
      });
  });
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
    audio_available: set[tuple[str, int]] | None = None,
) -> str:
    day_s = day.isoformat()
    gen = escape(doc.generated_at) if doc.generated_at else "—"
    selected = doc.selected if doc.selected is not None else len(doc.items)
    if lang == "en":
        meta = f"Generated (UTC): {gen} · Selected: {selected}"
    else:
        meta = f"生成时间（UTC）：{gen} · 精选：{selected}"

    available = audio_available or set()
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
            ),
        )
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
        newer_is_latest=newer_is_latest,
    )

    origin = _origin(site)
    en_path, zh_path = f"/archive/{day_s}/", f"/zh/archive/{day_s}/"
    canonical_path = en_path if lang == "en" else zh_path
    en_hl = en_path if lang == "en" or has_other_lang else None
    zh_hl = zh_path if lang == "zh" or has_other_lang else None

    script_src = _feed_script_href(links.css)
    podcast = _podcast_dock_html(lang)
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
    audio_available: set[tuple[str, int]] | None = None,
) -> str:
    links = _links_digest_home(lang, "", has_other_lang)
    total = len(items)
    page0 = items[:HOME_PAGE_SIZE]
    has_more = total > HOME_PAGE_SIZE
    if lang == "en":
        load_l = "Load more"
        feed_base = "/feed/en"
    else:
        load_l = "加载更多"
        feed_base = "/feed/zh"
    script_src = _feed_script_href(links.css)
    available = audio_available or set()

    items_html = _render_timeline_html(
        page0,
        lang,
        affiliate_enabled=site.affiliate_enabled,
        audio_available=available,
        prev_day=None,
    )
    if not items_html:
        items_html = (
            '<p class="muted">No items.</p>'
            if lang == "en"
            else '<p class="muted">暂无条目。</p>'
        )

    load_more = ""
    if has_more:
        load_more = (
            f'<div class="load-more-wrap">'
            f'<button type="button" class="load-more" id="load-more" '
            f'data-feed-base="{escape(feed_base)}" data-next="1">'
            f"{escape(load_l)}</button></div>"
        )

    origin = _origin(site)
    en_path, zh_path = "/", "/zh/"
    en_hl = en_path if lang == "en" or has_other_lang else None
    zh_hl = zh_path if lang == "zh" or has_other_lang else None
    desc = _static_description("home", lang)
    podcast = _podcast_dock_html(lang)

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
<main class="feed" id="feed">
  {items_html}
</main>
{load_more}
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
            "speak": "Play",
        }
        if lang == "en"
        else {
            "affiliate": "联盟推荐",
            "read": "看正文",
            "speak": "播",
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
    img = item.image_url.strip()
    if img:
        src = escape(img, quote=True)
        bits.append(
            f'<div class="item-thumb">'
            f'<img src="{src}" alt="" loading="lazy" '
            f'referrerpolicy="no-referrer" decoding="async" /></div>'
        )
    if header_bits:
        bits.append(f'<div class="item-meta">{"".join(header_bits)}</div>')
    bits.append(f"<h2>{title}</h2>")
    if item.summary:
        bits.append(f'<p class="summary">{escape(item.summary)}</p>')
    action_bits: list[str] = []
    if audio_href:
        action_bits.append(
            f'<button type="button" class="item-speak" aria-pressed="false">'
            f"{labels['speak']}</button>"
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


def _stylesheet() -> str:
    # Dark glow field (indigo + pink radials); dials VARIANCE 5 / MOTION 3 / DENSITY 2
    return """
:root {
  --bg: #0d0f17;
  --bg-elev: rgba(255, 255, 255, 0.05);
  --ink: #e2e8f0;
  --muted: #94a3b8;
  --accent: #a5b4fc;
  --accent-hot: #c4b5fd;
  --line: rgba(255, 255, 255, 0.12);
  --focus: #a5b4fc;
  --shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
  --radius: 16px;
  --font-display: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto,
    sans-serif;
  --font-body: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto,
    sans-serif;
  --font-ui: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto,
    sans-serif;
  --pad: clamp(1.5rem, 5vw, 2.5rem);
  --max: 72rem;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  min-height: 100vh;
  font-family: var(--font-ui);
  font-size: 1.0625rem;
  background-color: var(--bg);
  color: var(--ink);
  line-height: 1.7;
  overflow-x: hidden;
  position: relative;
}
body::before,
body::after {
  content: "";
  position: fixed;
  border-radius: 50%;
  pointer-events: none;
  z-index: -1;
  transform: translateZ(0);
}
body::before {
  top: -10%;
  left: -10%;
  width: 50vw;
  height: 50vw;
  background: radial-gradient(
    circle,
    rgba(99, 102, 241, 0.4) 0%,
    rgba(0, 0, 0, 0) 70%
  );
  filter: blur(80px);
}
body::after {
  bottom: -10%;
  right: -10%;
  width: 60vw;
  height: 60vw;
  background: radial-gradient(
    circle,
    rgba(236, 72, 153, 0.3) 0%,
    rgba(0, 0, 0, 0) 70%
  );
  filter: blur(100px);
}
.site {
  margin: 0 auto;
  max-width: var(--max);
  padding: var(--pad) var(--pad) 4rem;
  position: relative;
  z-index: 0;
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
  margin-bottom: 0;
}
.brand-block {
  margin-bottom: 1.35rem;
  animation: soft-in 0.7s ease both;
}
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
  position: sticky;
  top: 0;
  z-index: 50;
  display: flex;
  flex-wrap: wrap;
  gap: 0.85rem 1.75rem;
  align-items: center;
  justify-content: space-between;
  margin: 0 0 1.75rem;
  padding: 16px 24px;
  background: rgba(15, 23, 42, 0.8);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: none;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 0;
  box-shadow: none;
  font-size: 1rem;
  font-weight: 500;
}
body.has-day-sticky .site-nav {
  margin-bottom: 0;
  border-radius: 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: none;
}
.nav-primary {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem 1.65rem;
}
.nav-primary a {
  color: var(--muted);
  text-decoration: none;
  cursor: pointer;
  padding: 0.15rem 0.1rem;
}
.nav-primary a:hover { color: var(--accent-hot); }
.lang-switch {
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.lang-toggle {
  color: var(--ink);
  font-weight: 600;
  text-decoration: none;
  cursor: pointer;
}
a.lang-toggle:hover { color: var(--accent-hot); }
.lang-toggle.muted { font-weight: 500; color: var(--muted); }
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
  cursor: pointer;
}
.day-nav-link:hover { text-decoration: underline; }
.day-nav-muted {
  color: var(--muted);
  opacity: 0.55;
  cursor: default;
}
.load-more-wrap {
  display: flex;
  justify-content: center;
  margin: 1.75rem 0 0.5rem;
}
.load-more {
  font-family: var(--font-ui);
  font-size: 0.92rem;
  font-weight: 600;
  letter-spacing: 0.01em;
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent) 35%, var(--line));
  border-radius: 0.55rem;
  padding: 0.65rem 1.25rem;
  cursor: pointer;
}
.load-more:hover {
  background: color-mix(in srgb, var(--accent) 16%, transparent);
}
.load-more:disabled {
  opacity: 0.55;
  cursor: wait;
}
.feed-day-sticky {
  position: sticky;
  top: var(--nav-sticky-bottom, 3.75rem);
  z-index: 3;
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 24px 0 16px;
  padding: 0.45rem 0;
  background: color-mix(in srgb, var(--bg) 82%, transparent);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border: none;
  border-radius: 0;
  font-family: var(--font-ui);
  font-size: 0.9rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: #94a3b8;
}
.feed-day-sticky::after {
  content: "";
  flex: 1;
  height: 1px;
  min-width: 2rem;
  background: linear-gradient(90deg, rgba(255, 255, 255, 0.1), transparent);
}
.feed-day-sticky:first-child {
  margin-top: 0;
}
.feed-day-sticky + .item {
  margin-top: 0;
}
.feed:has(> .item) > .feed-day-sticky + .item {
  margin-top: 0;
}
.feed-day-sticky time {
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
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
.feed:has(> .item) {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 20rem), 1fr));
  gap: 1.25rem;
  align-items: stretch;
}
.feed:has(> .item) > .feed-day-sticky {
  grid-column: 1 / -1;
}
.read-progress {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 2px;
  z-index: 50;
  pointer-events: none;
  background: color-mix(in srgb, var(--accent) 22%, transparent);
}
.read-progress::after {
  content: "";
  display: block;
  height: 100%;
  width: 100%;
  background: var(--accent);
  transform-origin: left center;
  transform: scaleX(var(--p, 0));
}
.item {
  --source: var(--accent);
  position: relative;
  display: grid;
  grid-template-columns: 2.5rem 1fr;
  gap: 0.55rem 0.95rem;
  padding: 1.25rem;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-left: 3px solid var(--source);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  animation: soft-in 0.55s ease both;
  animation-delay: calc(var(--i, 0) * 45ms);
  transition:
    transform 0.25s cubic-bezier(0.4, 0, 0.2, 1),
    border-color 0.25s cubic-bezier(0.4, 0, 0.2, 1),
    box-shadow 0.25s cubic-bezier(0.4, 0, 0.2, 1),
    background-color 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}
.item:has(.item-read) {
  cursor: pointer;
}
.item[data-source="hn"] { --source: #c45c26; }
.item[data-source="openai"],
.item[data-source="rss:openai"] { --source: #1a7f64; }
.item[data-source="google_ai"],
.item[data-source="rss:google_ai"] { --source: #3b6ea5; }
.item[data-source="deepmind"],
.item[data-source="rss:deepmind"] { --source: #2a8f8a; }
.item[data-source="anthropic"],
.item[data-source="rss:anthropic"] { --source: #b56a4a; }
.item[data-source="huggingface"],
.item[data-source="rss:huggingface"] { --source: #b0891d; }
.item[data-source="nvidia_ai"],
.item[data-source="rss:nvidia_ai"] { --source: #4a9a3e; }
.item[data-source="apple_newsroom"],
.item[data-source="rss:apple_newsroom"],
.item[data-source="apple_ml"],
.item[data-source="rss:apple_ml"] { --source: #6b7280; }
.item[data-source="qbitai"],
.item[data-source="rss:qbitai"] { --source: #6b5b8a; }
.item:hover {
  transform: translateY(-4px);
  border-color: rgba(99, 102, 241, 0.5);
  border-left-color: var(--source);
  background: rgba(255, 255, 255, 0.055);
  box-shadow:
    0 12px 30px -10px rgba(0, 0, 0, 0.5),
    0 0 15px rgba(99, 102, 241, 0.15);
}
.item:active {
  transform: translateY(-1px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}
.item-index {
  font-family: var(--font-display);
  font-size: 0.9rem;
  font-weight: 700;
  color: #38bdf8;
  letter-spacing: -0.02em;
  padding-top: 0.3rem;
  font-variant-numeric: tabular-nums;
  opacity: 0.7;
}
.item-thumb {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 9;
  margin: 0 0 0.75rem;
  border-radius: 0.55rem;
  overflow: hidden;
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--line) 55%, transparent);
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
  font-size: 1.2rem;
  font-weight: 600;
  margin: 0 0 0.55rem;
  line-height: 1.4;
  letter-spacing: -0.01em;
  color: #ffffff;
}
.item[data-heat="1"] h2 { font-weight: 500; }
.item[data-heat="2"] h2 { font-weight: 600; }
.item[data-heat="3"] h2 { font-weight: 700; }
.item-actions {
  margin: 12px 0 0;
  position: relative;
  z-index: 2;
}
.item-read {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0;
  border: none;
  background: none;
  font-family: var(--font-ui);
  font-size: 0.85rem;
  font-weight: 600;
  color: #818cf8;
  text-decoration: none;
  cursor: pointer;
}
.item-read::before {
  content: "";
  position: absolute;
  inset: 0;
  z-index: 1;
}
.item-read::after {
  content: " →";
  transition: transform 0.2s ease;
}
.item:hover .item-read {
  color: #a5b4fc;
}
.item:hover .item-read::after {
  transform: translateX(4px);
}
.item-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 0 0 0.65rem;
  font-family: var(--font-ui);
}
.badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.01em;
  font-family: var(--font-ui);
  background: rgba(99, 102, 241, 0.12);
  color: #a5b4fc;
  border: 1px solid rgba(99, 102, 241, 0.2);
}
.badge-primary,
.badge-source {
  background: color-mix(in srgb, var(--source) 22%, transparent);
  color: color-mix(in srgb, var(--source) 55%, #ffffff);
  border-color: color-mix(in srgb, var(--source) 35%, transparent);
}
.badge-tag {
  background: rgba(255, 255, 255, 0.06);
  color: #e2e8f0;
  border-color: rgba(255, 255, 255, 0.12);
}
.item[data-tag="paper"] .badge-tag {
  background: rgba(90, 111, 154, 0.2);
  color: #c7d2fe;
  border-color: rgba(90, 111, 154, 0.35);
}
.meta-text {
  font-size: 0.75rem;
  font-weight: 500;
  color: #64748b;
  letter-spacing: 0.01em;
}
.summary, .why, .affiliate {
  margin: 12px 0 0;
  font-family: var(--font-body);
  font-size: 0.95rem;
  line-height: 1.65;
  color: #e2e8f0;
}
.why {
  color: var(--muted);
  font-size: 0.875rem;
  font-family: var(--font-ui);
}
.affiliate {
  position: relative;
  z-index: 2;
  margin-top: 0.75rem;
  padding-top: 0.7rem;
  border-top: 1px dashed var(--line);
  font-size: 0.875rem;
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
  .brand-block, .day-bar, .arena, .item { animation: none; }
  .item, .archive-list li { transition: none; }
  .item:hover,
  .item:active { transform: none; }
  .read-progress::after { transition: none; }
}
@media (max-width: 720px) {
  /* 手机端大 blur 易被裁切/淡化：加大光斑、提高不透明度、减弱 blur */
  body::before {
    top: -8%;
    left: -30%;
    width: min(120vw, 34rem);
    height: min(120vw, 34rem);
    background: radial-gradient(
      circle,
      rgba(99, 102, 241, 0.65) 0%,
      rgba(99, 102, 241, 0.22) 42%,
      rgba(0, 0, 0, 0) 72%
    );
    filter: blur(36px);
  }
  body::after {
    bottom: 5%;
    right: -35%;
    top: auto;
    width: min(130vw, 38rem);
    height: min(130vw, 38rem);
    background: radial-gradient(
      circle,
      rgba(236, 72, 153, 0.55) 0%,
      rgba(236, 72, 153, 0.18) 45%,
      rgba(0, 0, 0, 0) 72%
    );
    filter: blur(42px);
  }
  .site-nav,
  body.has-day-sticky .site-nav,
  .feed-day-sticky {
    width: 100vw;
    max-width: 100vw;
    margin-left: calc(50% - 50vw);
    margin-right: calc(50% - 50vw);
    border-radius: 0;
    border-left: none;
    border-right: none;
    box-sizing: border-box;
  }
  .site-nav {
    top: 0;
    align-items: flex-start;
    padding: 0.85rem var(--pad);
  }
  body.has-day-sticky .site-nav {
    margin-bottom: 0;
    border-radius: 0;
  }
  .feed-day-sticky {
    padding-left: var(--pad);
    padding-right: var(--pad);
  }
  .item {
    grid-template-columns: 1.8rem 1fr;
    padding: 1.05rem 1rem 1.1rem;
  }
  .feed:has(> .item) {
    grid-template-columns: 1fr;
    gap: 0.95rem;
  }
}
.item-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
  align-items: center;
  margin: 0.65rem 0 0;
}
.item-speak {
  appearance: none;
  position: relative;
  z-index: 3;
  border: 1px solid rgba(148, 163, 184, 0.35);
  background: rgba(15, 23, 42, 0.55);
  color: #e2e8f0;
  border-radius: 999px;
  padding: 0.28rem 0.75rem;
  font: inherit;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
}
.item-speak[aria-pressed="true"] {
  border-color: rgba(99, 102, 241, 0.7);
  background: rgba(99, 102, 241, 0.25);
  color: #c7d2fe;
}
.item.is-playing {
  outline: 1px solid rgba(99, 102, 241, 0.55);
  box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.12);
}
.podcast-dock {
  position: fixed;
  left: 50%;
  right: auto;
  bottom: 0;
  z-index: 40;
  transform: translateX(-50%);
  width: min(42rem, 100%);
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
  align-items: center;
  justify-content: center;
  padding: 0.75rem 1rem calc(0.75rem + env(safe-area-inset-bottom));
  background: rgba(10, 12, 20, 0.94);
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-bottom: none;
  border-radius: 1rem 1rem 0 0;
  backdrop-filter: blur(10px);
  box-shadow: 0 -8px 28px rgba(0, 0, 0, 0.35);
}
.podcast-mode,
.podcast-nav {
  appearance: none;
  border: 1px solid rgba(148, 163, 184, 0.35);
  background: rgba(30, 41, 59, 0.9);
  color: #f8fafc;
  border-radius: 999px;
  padding: 0.45rem 0.9rem;
  font: inherit;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
}
.podcast-mode-icon {
  display: none;
  line-height: 0;
}
.podcast-mode-icon svg {
  display: block;
}
.podcast-mode-label {
  display: inline;
}
@media (min-width: 721px) {
  .podcast-mode-icon {
    display: none !important;
  }
}
.podcast-mode[aria-pressed="true"] {
  border-color: rgba(99, 102, 241, 0.75);
  background: rgba(99, 102, 241, 0.3);
}
.podcast-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  align-items: center;
}
.podcast-now {
  color: #cbd5e1;
  font-size: 0.82rem;
  min-width: 4.5rem;
}
body.has-podcast-dock {
  padding-bottom: 4.5rem;
}
@media (max-width: 720px) {
  body.has-podcast-dock {
    padding-bottom: 0;
  }
  .podcast-dock {
    left: auto;
    right: max(0.85rem, env(safe-area-inset-right));
    bottom: max(0.85rem, env(safe-area-inset-bottom));
    width: auto;
    max-width: calc(100vw - 1.7rem);
    transform: none;
    flex-direction: column-reverse;
    align-items: flex-end;
    gap: 0.55rem;
    padding: 0;
    background: transparent;
    border: none;
    border-radius: 0;
    box-shadow: none;
    backdrop-filter: none;
  }
  .podcast-mode {
    width: auto;
    min-width: 3.6rem;
    height: auto;
    padding: 0.55rem 0.7rem 0.45rem;
    border: none;
    border-radius: 1.15rem;
    background: rgba(99, 102, 241, 0.95);
    color: #f8fafc;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    display: inline-flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.2rem;
    position: relative;
    isolation: isolate;
    overflow: visible;
    box-shadow:
      0 10px 28px rgba(0, 0, 0, 0.45),
      0 0 0 1px rgba(255, 255, 255, 0.08);
  }
  .podcast-mode-label {
    display: block;
    line-height: 1;
  }
  .podcast-mode-icon {
    display: inline-flex;
  }
  .podcast-mode-icon[hidden] {
    display: none !important;
  }
  .podcast-mode[aria-pressed="true"] {
    background: rgba(79, 70, 229, 1);
    box-shadow:
      0 10px 28px rgba(99, 102, 241, 0.45),
      0 0 0 2px rgba(165, 180, 252, 0.45);
  }
  .podcast-mode[aria-pressed="true"]::before,
  .podcast-mode[aria-pressed="true"]::after {
    content: "";
    position: absolute;
    inset: -2px;
    border-radius: inherit;
    border: 2px solid rgba(165, 180, 252, 0.55);
    z-index: -1;
    pointer-events: none;
    animation: podcast-ripple 1.8s ease-out infinite;
  }
  .podcast-mode[aria-pressed="true"]::after {
    animation-delay: 0.9s;
  }
  .podcast-controls {
    display: none;
  }
  .podcast-now {
    display: none;
  }
}
@keyframes podcast-ripple {
  0% {
    transform: scale(1);
    opacity: 0.7;
  }
  100% {
    transform: scale(1.55);
    opacity: 0;
  }
}
@media (prefers-reduced-motion: reduce) {
  .podcast-mode[aria-pressed="true"]::before,
  .podcast-mode[aria-pressed="true"]::after {
    animation: none;
  }
}
""".strip()


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
    output_dir = Path(config.paths.site_output_dir).resolve()
    build_site(
        content_dir=Path(config.paths.content_digests_dir),
        output_dir=output_dir,
        site=config.site,
        arena_boards=boards,
        audio_dirs=[
            Path(config.paths.content_audio_dir),
            Path(config.paths.speak_audio_dir),
        ],
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
