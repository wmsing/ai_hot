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
from src.models import DigestDocument, DigestItem
from src.site_parse import parse_digest_markdown

_DIGEST_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.(en|zh)\.md$")

SITE_NAME_EN = "AI Hot Digest"
SITE_TAGLINE_ZH = "AI 热点摘要"


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
    lang_other: str
    brand_home: str


def build_site(*, content_dir: Path, output_dir: Path) -> None:
    """扫描 content_dir，写出完整静态站到 output_dir。"""
    days = _scan_days(content_dir)
    if output_dir.exists():
        _clear_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "styles.css").write_text(_stylesheet(), encoding="utf-8")

    _write(output_dir / "archive" / "index.html", _render_archive_index(days, "en"))
    _write(
        output_dir / "zh" / "archive" / "index.html",
        _render_archive_index(days, "zh"),
    )
    _write(output_dir / "disclosure.html", _render_disclosure("en"))
    _write(output_dir / "zh" / "disclosure.html", _render_disclosure("zh"))

    latest = days[0] if days else None
    if latest is None:
        _write(output_dir / "index.html", _render_empty_home("en"))
        _write(output_dir / "zh" / "index.html", _render_empty_home("zh"))
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
            )
            _write(output_dir / "archive" / day_s / "index.html", archive_page)
            if day_files.day == latest.day:
                home_page = _render_digest(
                    doc=en_doc,
                    day=day_files.day,
                    lang="en",
                    has_other_lang=has_zh,
                    links=_links_digest_home("en", day_s, has_zh),
                )
                _write(output_dir / "index.html", home_page)
        elif day_files.day == latest.day:
            _write(output_dir / "index.html", _render_missing_home("en", day_files.day))

        if zh_doc is not None:
            archive_page = _render_digest(
                doc=zh_doc,
                day=day_files.day,
                lang="zh",
                has_other_lang=has_en,
                links=_links_digest_archive("zh", day_s, has_en),
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
                )
                _write(output_dir / "zh" / "index.html", home_page)
        elif day_files.day == latest.day:
            _write(
                output_dir / "zh" / "index.html",
                _render_missing_home("zh", day_files.day),
            )


def _links_digest_home(lang: str, day_s: str, has_other: bool) -> PageLinks:
    _ = day_s
    if lang == "en":
        other = "zh/index.html" if has_other else ""
        return PageLinks(
            css="styles.css",
            home="index.html",
            archive="archive/index.html",
            disclosure="disclosure.html",
            lang_other=other,
            brand_home="index.html",
        )
    other = "../index.html" if has_other else ""
    return PageLinks(
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
        return PageLinks(
            css="../../styles.css",
            home="../../index.html",
            archive="../index.html",
            disclosure="../../disclosure.html",
            lang_other=other,
            brand_home="../../index.html",
        )
    other = f"../../../archive/{day_s}/index.html" if has_other else ""
    return PageLinks(
        css="../../../styles.css",
        home="../../index.html",
        archive="../index.html",
        disclosure="../../disclosure.html",
        lang_other=other,
        brand_home="../../index.html",
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
            return f'EN | <a href="{escape(other_href)}">中文</a>'
        return 'EN | <span class="muted">中文 N/A</span>'
    if other_href:
        return f'<a href="{escape(other_href)}">EN</a> | 中文'
    return '<span class="muted">EN N/A</span> | 中文'


def _footer(lang: str, disclosure_href: str) -> str:
    label = "disclosure" if lang == "en" else "披露说明"
    lead = (
        "Affiliate disclosures will appear here."
        if lang == "en"
        else "联盟披露将显示于此。"
    )
    see = "See" if lang == "en" else "详见"
    return f'{lead} {see} <a href="{escape(disclosure_href)}">{label}</a>.'


def _brand_sub(lang: str) -> str:
    if lang != "zh":
        return ""
    return f'<p class="tagline">{escape(SITE_TAGLINE_ZH)}</p>'


def _render_digest(
    *,
    doc: DigestDocument,
    day: date,
    lang: str,
    has_other_lang: bool,
    links: PageLinks,
) -> str:
    del has_other_lang  # encoded in links.lang_other
    day_s = day.isoformat()
    gen = escape(doc.generated_at) if doc.generated_at else "—"
    selected = doc.selected if doc.selected is not None else len(doc.items)
    if lang == "en":
        meta = f"Generated (UTC): {gen} · Selected: {selected}"
        home_l, archive_l = "Home", "Archive"
    else:
        meta = f"生成时间（UTC）：{gen} · 精选：{selected}"
        home_l, archive_l = "首页", "归档"

    items_html = "".join(_render_item(item, lang) for item in doc.items)
    if not items_html:
        items_html = (
            '<p class="muted">No items.</p>'
            if lang == "en"
            else '<p class="muted">暂无条目。</p>'
        )

    nav = (
        f'<nav><a href="{escape(links.home)}">{home_l}</a> · '
        f'<a href="{escape(links.archive)}">{archive_l}</a> · '
        f"{_lang_nav(lang, links.lang_other)}</nav>"
    )
    return _shell(
        title=f"{SITE_NAME_EN} — {day_s}",
        css_href=links.css,
        lang=lang,
        body=f"""
<header>
  <p class="brand"><a href="{escape(links.brand_home)}">{escape(SITE_NAME_EN)}</a></p>
  {_brand_sub(lang)}
  {nav}
  <h1>{escape(day_s)}</h1>
  <p class="meta">{meta}</p>
</header>
<main>
  {items_html}
</main>
<footer><p>{_footer(lang, links.disclosure)}</p></footer>
""",
    )


def _render_item(item: DigestItem, lang: str) -> str:
    labels = (
        {
            "source": "source",
            "published": "published",
            "summary": "summary",
            "why": "why",
        }
        if lang == "en"
        else {
            "source": "来源",
            "published": "发布时间",
            "summary": "摘要",
            "why": "原因",
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
    bits = ["<article>", f"<h2>{item.index}. {title_html}</h2>", "<ul>"]
    if item.source:
        bits.append(f"<li>{labels['source']}: <code>{escape(item.source)}</code></li>")
    if item.published:
        bits.append(f"<li>{labels['published']}: {escape(item.published)}</li>")
    if item.score_line:
        bits.append(f"<li>{escape(item.score_line)}</li>")
    if item.summary:
        bits.append(f"<li>{labels['summary']}: {escape(item.summary)}</li>")
    if item.reason:
        bits.append(f"<li>{labels['why']}: {escape(item.reason)}</li>")
    bits.extend(["</ul>", "</article>"])
    return "\n".join(bits)


def _render_archive_index(days: list[DayFiles], lang: str) -> str:
    if lang == "en":
        links = PageLinks(
            css="../styles.css",
            home="../index.html",
            archive="index.html",
            disclosure="../disclosure.html",
            lang_other="../zh/archive/index.html",
            brand_home="../index.html",
        )
        heading, empty = "Archive", "No digests yet."
    else:
        links = PageLinks(
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
        rows = ["<ul class='archive-list'>"]
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

    home_l = "Home" if lang == "en" else "首页"
    return _shell(
        title=f"{SITE_NAME_EN} — {heading}",
        css_href=links.css,
        lang=lang,
        body=f"""
<header>
  <p class="brand"><a href="{escape(links.brand_home)}">{escape(SITE_NAME_EN)}</a></p>
  {_brand_sub(lang)}
  <nav>
    <a href="{escape(links.home)}">{home_l}</a> ·
    {_lang_nav(lang, links.lang_other)}
  </nav>
  <h1>{heading}</h1>
</header>
<main>{lis}</main>
<footer><p>{_footer(lang, links.disclosure)}</p></footer>
""",
    )


def _render_disclosure(lang: str) -> str:
    if lang == "en":
        links = PageLinks(
            css="styles.css",
            home="index.html",
            archive="archive/index.html",
            disclosure="disclosure.html",
            lang_other="zh/disclosure.html",
            brand_home="index.html",
        )
        heading = "Disclosure"
        body_text = (
            "<p>This site may include affiliate links in the future. "
            "When that happens, we will disclose them here and in the page footer.</p>"
            "<p>No affiliate links are active in v1.</p>"
        )
    else:
        links = PageLinks(
            css="../styles.css",
            home="index.html",
            archive="archive/index.html",
            disclosure="disclosure.html",
            lang_other="../disclosure.html",
            brand_home="index.html",
        )
        heading = "披露说明"
        body_text = (
            "<p>本站未来可能包含联盟推广链接。届时将在本页与页脚披露。</p>"
            "<p>v1 尚未启用任何联盟链接。</p>"
        )
    home_l = "Home" if lang == "en" else "首页"
    return _shell(
        title=f"{SITE_NAME_EN} — {heading}",
        css_href=links.css,
        lang=lang,
        body=f"""
<header>
  <p class="brand"><a href="{escape(links.brand_home)}">{escape(SITE_NAME_EN)}</a></p>
  {_brand_sub(lang)}
  <nav>
    <a href="{escape(links.home)}">{home_l}</a> ·
    {_lang_nav(lang, links.lang_other)}
  </nav>
  <h1>{heading}</h1>
</header>
<main>{body_text}</main>
<footer><p>{_footer(lang, links.disclosure)}</p></footer>
""",
    )


def _render_empty_home(lang: str) -> str:
    if lang == "en":
        links = PageLinks(
            css="styles.css",
            home="index.html",
            archive="archive/index.html",
            disclosure="disclosure.html",
            lang_other="zh/index.html",
            brand_home="index.html",
        )
        msg = "No digests published yet. Run publish then build."
    else:
        links = PageLinks(
            css="../styles.css",
            home="index.html",
            archive="archive/index.html",
            disclosure="disclosure.html",
            lang_other="../index.html",
            brand_home="index.html",
        )
        msg = "尚无已发布摘要。请先 publish 再 build。"
    return _shell(
        title=SITE_NAME_EN,
        css_href=links.css,
        lang=lang,
        body=f"""
<header>
  <p class="brand"><a href="{escape(links.brand_home)}">{escape(SITE_NAME_EN)}</a></p>
  {_brand_sub(lang)}
  <nav>{_lang_nav(lang, links.lang_other)}</nav>
</header>
<main><p class="muted">{escape(msg)}</p></main>
<footer><p>{_footer(lang, links.disclosure)}</p></footer>
""",
    )


def _render_missing_home(lang: str, day: date) -> str:
    day_s = day.isoformat()
    if lang == "en":
        links = PageLinks(
            css="styles.css",
            home="index.html",
            archive="archive/index.html",
            disclosure="disclosure.html",
            lang_other="zh/index.html",
            brand_home="index.html",
        )
        msg = f"English digest for {day_s} is missing."
    else:
        links = PageLinks(
            css="../styles.css",
            home="index.html",
            archive="archive/index.html",
            disclosure="disclosure.html",
            lang_other="../index.html",
            brand_home="index.html",
        )
        msg = f"{day_s} 的中文摘要缺失。"
    return _shell(
        title=f"{SITE_NAME_EN} — {day_s}",
        css_href=links.css,
        lang=lang,
        body=f"""
<header>
  <p class="brand"><a href="{escape(links.brand_home)}">{escape(SITE_NAME_EN)}</a></p>
  {_brand_sub(lang)}
  <nav>{_lang_nav(lang, links.lang_other)}</nav>
  <h1>{escape(day_s)}</h1>
</header>
<main><p class="muted">{escape(msg)}</p></main>
<footer><p>{_footer(lang, links.disclosure)}</p></footer>
""",
    )


def _shell(*, title: str, css_href: str, lang: str, body: str) -> str:
    html_lang = "zh-Hans" if lang == "zh" else "en"
    fonts = (
        "https://fonts.googleapis.com/css2?"
        "family=Fraunces:opsz,wght@9..144,600&amp;"
        "family=IBM+Plex+Sans:wght@400;600&amp;display=swap"
    )
    return f"""<!DOCTYPE html>
<html lang="{html_lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
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


def _stylesheet() -> str:
    return """
:root {
  --bg: #f3f6f4;
  --ink: #14231c;
  --muted: #5c6b63;
  --accent: #0b6e4f;
  --line: #cfd8d2;
  --card: #fbfcfb;
}
* { box-sizing: border-box; }
body {
  margin: 0 auto;
  max-width: 42rem;
  padding: 1.5rem 1.25rem 3rem;
  font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
  background:
    linear-gradient(160deg, #e7f0ea 0%, transparent 42%),
    var(--bg);
  color: var(--ink);
  line-height: 1.55;
}
.brand {
  font-family: "Fraunces", "Times New Roman", serif;
  font-size: 1.75rem;
  font-weight: 600;
  margin: 0 0 0.25rem;
}
.brand a { color: inherit; text-decoration: none; }
.tagline { margin: 0 0 0.75rem; color: var(--muted); }
nav { margin: 0 0 1.25rem; color: var(--muted); font-size: 0.95rem; }
nav a { color: var(--accent); }
h1 { font-size: 1.35rem; margin: 0 0 0.35rem; }
.meta { color: var(--muted); margin: 0 0 1.5rem; font-size: 0.9rem; }
article {
  background: var(--card);
  border-top: 1px solid var(--line);
  padding: 1rem 0 1.1rem;
}
article h2 {
  font-size: 1.05rem;
  margin: 0 0 0.5rem;
  font-weight: 600;
}
article h2 a { color: var(--ink); }
article ul {
  margin: 0;
  padding-left: 1.1rem;
  color: var(--muted);
  font-size: 0.92rem;
}
.muted { color: var(--muted); }
.archive-list { padding-left: 1.1rem; }
.archive-list a { color: var(--accent); }
footer {
  margin-top: 2rem;
  padding-top: 1rem;
  border-top: 1px solid var(--line);
  color: var(--muted);
  font-size: 0.85rem;
}
footer a { color: var(--accent); }
code { font-size: 0.85em; }
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
    )
    print(f"[ai_hot] site built → {config.paths.site_output_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
