"""RSS 数据源。"""

from __future__ import annotations

import logging
import re
from typing import Any

import feedparser
import httpx

from src.models import HotItem, RssConfig
from src.textutil import strip_html, truncate
from src.timeutil import from_rss_entry

logger = logging.getLogger(__name__)

_IMG_SRC_RE = re.compile(
    r"""<img[^>]+src=["']([^"']+)["']""",
    re.IGNORECASE,
)


def fetch_rss_candidates(client: httpx.Client, cfg: RssConfig) -> list[HotItem]:
    """按源抓取 RSS；多取若干条供 pipeline 去重后再截断 max_new_per_feed。"""
    results: list[HotItem] = []
    for feed in cfg.feeds:
        # 有关键词白名单时多抓，避免筛完后凑不满 max_new_per_feed
        if feed.keywords:
            fetch_cap = max(cfg.max_new_per_feed * 20, 40)
        else:
            fetch_cap = max(cfg.max_new_per_feed * 4, cfg.max_new_per_feed)
        try:
            resp = client.get(str(feed.url))
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("rss fetch failed name=%s err=%s", feed.name, exc)
            continue

        parsed: Any = feedparser.parse(resp.text)
        entries = list(getattr(parsed, "entries", []) or [])
        taken = 0
        for entry in entries:
            if taken >= fetch_cap:
                break
            title = str(getattr(entry, "title", "") or "").strip()
            link = _entry_link(entry)
            if not title or not link:
                continue
            results.append(
                HotItem(
                    source=f"rss:{feed.name}",
                    title=title,
                    url=link,
                    score=None,
                    comments=None,
                    summary=_entry_summary(entry),
                    image_url=_entry_image(entry),
                    published_at=from_rss_entry(entry),
                    reason=f"rss_new feed={feed.name}",
                )
            )
            taken += 1
        logger.info("rss feed=%s fetched=%s", feed.name, taken)
    return results


def _entry_link(entry: Any) -> str:
    link = str(getattr(entry, "link", "") or "").strip()
    if link:
        return link
    # Hugging Face 等源偶发只有 guid
    guid = getattr(entry, "guid", None) or getattr(entry, "id", None)
    if guid and str(guid).startswith("http"):
        return str(guid).strip()
    return ""


def _entry_summary(entry: Any) -> str | None:
    raw = getattr(entry, "summary", None) or getattr(entry, "description", None) or ""
    text = strip_html(str(raw))
    if not text:
        return None
    return truncate(text, 280)


def _entry_image(entry: Any) -> str | None:
    """从 media / enclosure / HTML 摘要里取首张可用图。"""
    for thumb in getattr(entry, "media_thumbnail", None) or []:
        url = _abs_http_url(_mapping_get(thumb, "url"))
        if url:
            return url
    for media in getattr(entry, "media_content", None) or []:
        medium = str(_mapping_get(media, "medium") or "")
        typ = str(_mapping_get(media, "type") or "")
        url = _abs_http_url(_mapping_get(media, "url"))
        if url and (medium == "image" or typ.startswith("image/")):
            return url
        if url and _looks_like_image_url(url):
            return url
    for enc in getattr(entry, "enclosures", None) or []:
        typ = str(_mapping_get(enc, "type") or "")
        if typ.startswith("image/"):
            url = _abs_http_url(_mapping_get(enc, "href") or _mapping_get(enc, "url"))
            if url:
                return url
    html_bits: list[str] = []
    summary = getattr(entry, "summary", None) or getattr(entry, "description", None)
    if summary:
        html_bits.append(str(summary))
    for block in getattr(entry, "content", None) or []:
        val = _mapping_get(block, "value")
        if val:
            html_bits.append(str(val))
    for html in html_bits:
        match = _IMG_SRC_RE.search(html)
        if match:
            url = _abs_http_url(match.group(1))
            if url:
                return url
    return None


def _mapping_get(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _abs_http_url(raw: Any) -> str | None:
    text = str(raw or "").strip()
    if text.startswith("//"):
        text = "https:" + text
    if text.startswith("http://") or text.startswith("https://"):
        return text
    return None


def _looks_like_image_url(url: str) -> bool:
    path = url.split("?", 1)[0].lower()
    return path.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg"))
