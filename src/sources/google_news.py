"""Google News RSS 搜索源。"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus, urlencode

import feedparser
import httpx

from src.models import GoogleNewsConfig, GoogleNewsQuery, HotItem
from src.textutil import strip_html, truncate
from src.timeutil import from_rss_entry

logger = logging.getLogger(__name__)


def _rss_url(q: GoogleNewsQuery) -> str:
    raw = q.query.strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    params = urlencode(
        {
            "q": raw,
            "hl": q.hl,
            "gl": q.gl,
            "ceid": q.ceid,
        },
        quote_via=quote_plus,
    )
    return f"https://news.google.com/rss/search?{params}"


def fetch_google_news_candidates(
    client: httpx.Client, cfg: GoogleNewsConfig
) -> list[HotItem]:
    """按查询拉 Google News RSS；无原生 score，用列表位次近似。"""
    if not cfg.enabled:
        return []

    results: list[HotItem] = []
    for query in cfg.queries:
        url = _rss_url(query)
        try:
            resp = client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("google_news fetch failed name=%s err=%s", query.name, exc)
            continue

        parsed: Any = feedparser.parse(resp.text)
        entries = list(getattr(parsed, "entries", []) or [])
        taken = 0
        for rank, entry in enumerate(entries, start=1):
            if taken >= cfg.max_per_query:
                break
            title = str(getattr(entry, "title", "") or "").strip()
            link = str(getattr(entry, "link", "") or "").strip()
            if not title or not link:
                continue
            # 位次越前 engagement 越高（供跨源打分）
            engagement = max(cfg.max_per_query - rank + 1, 1) * 10
            summary_raw = str(
                getattr(entry, "summary", None)
                or getattr(entry, "description", None)
                or ""
            )
            summary = truncate(strip_html(summary_raw), 280) if summary_raw else None
            results.append(
                HotItem(
                    source=f"google_news:{query.name}",
                    title=title,
                    url=link,
                    score=engagement,
                    comments=0,
                    summary=summary,
                    published_at=from_rss_entry(entry),
                    reason=f"google_news {query.name} rank={rank}",
                )
            )
            taken += 1
    logger.info("google_news candidates: %s", len(results))
    return results
