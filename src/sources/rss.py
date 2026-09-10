"""RSS 数据源。"""

from __future__ import annotations

import logging
from typing import Any

import feedparser
import httpx

from src.models import HotItem, RssConfig
from src.textutil import strip_html, truncate
from src.timeutil import from_rss_entry

logger = logging.getLogger(__name__)


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
