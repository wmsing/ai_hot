"""Google Trends 非官方辅助：日榜 RSS + related queries；失败则空列表。"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import quote

import feedparser
import httpx

from src.models import HotItem, TrendsConfig
from src.timeutil import from_rss_entry

logger = logging.getLogger(__name__)

_XSSI_PREFIX = re.compile(r"^\)\]\}',?\s*")


def fetch_trends_daily_candidates(
    client: httpx.Client, cfg: TrendsConfig
) -> list[HotItem]:
    """拉取 Trends 日榜 RSS，按 AI 关键词过滤。失败返回 []。"""
    if not cfg.enabled:
        return []

    geo = (cfg.geo or "US").strip() or "US"
    url = (
        f"https://trends.google.com/trends/trendingsearches/daily/rss?geo={quote(geo)}"
    )
    try:
        resp = client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("trends daily rss failed geo=%s err=%s", geo, exc)
        return []

    parsed: Any = feedparser.parse(resp.text)
    entries = list(getattr(parsed, "entries", []) or [])
    keywords = [k.casefold() for k in cfg.ai_keywords if k.strip()]
    items: list[HotItem] = []
    for rank, entry in enumerate(entries, start=1):
        title = str(getattr(entry, "title", "") or "").strip()
        if not title:
            continue
        blob = title.casefold()
        if keywords and not any(k in blob for k in keywords):
            continue
        link = str(getattr(entry, "link", "") or "").strip()
        if not link:
            link = (
                "https://trends.google.com/trends/explore?"
                f"q={quote(title)}&geo={quote(geo)}"
            )
        traffic = _approx_traffic(entry)
        items.append(
            HotItem(
                source="trends",
                title=title,
                url=link,
                score=traffic or max(100 - rank, 1),
                comments=0,
                summary=None,
                published_at=from_rss_entry(entry),
                reason=f"trends daily geo={geo} rank={rank}",
            )
        )
    logger.info("trends daily ai candidates: %s", len(items))
    return items


def fetch_related_queries(
    client: httpx.Client,
    cfg: TrendsConfig,
    *,
    keyword: str,
) -> list[str]:
    """非官方 related queries；任意步骤失败返回 []。"""
    if not cfg.enabled:
        return []
    term = keyword.strip()
    if not term:
        return []

    try:
        # 暖 cookie；429 仍可能带 Set-Cookie
        client.get("https://trends.google.com/trends/explore", timeout=20.0)
        req = {
            "comparisonItem": [
                {
                    "keyword": term,
                    "geo": cfg.geo or "",
                    "time": "now 7-d",
                }
            ],
            "category": 0,
            "property": "",
        }
        explore = client.get(
            "https://trends.google.com/trends/api/explore",
            params={
                "hl": "en-US",
                "tz": "0",
                "req": json.dumps(req, separators=(",", ":")),
            },
            timeout=20.0,
        )
        if explore.status_code >= 400:
            logger.warning(
                "trends explore http=%s keyword=%s", explore.status_code, term
            )
            return []
        widgets = _parse_trends_json(explore.text)
        if not isinstance(widgets, dict):
            return []
        related_token = None
        related_req = None
        for widget in widgets.get("widgets") or []:
            if not isinstance(widget, dict):
                continue
            if widget.get("id") == "RELATED_QUERIES":
                related_token = widget.get("token")
                related_req = widget.get("request")
                break
        if not related_token or related_req is None:
            return []
        related = client.get(
            "https://trends.google.com/trends/api/widgetdata/relatedsearches",
            params={
                "hl": "en-US",
                "tz": "0",
                "req": json.dumps(related_req, separators=(",", ":")),
                "token": related_token,
            },
            timeout=20.0,
        )
        if related.status_code >= 400:
            logger.warning(
                "trends related http=%s keyword=%s", related.status_code, term
            )
            return []
        payload = _parse_trends_json(related.text)
        return _extract_related_titles(payload)
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        logger.warning("trends related failed keyword=%s err=%s", term, exc)
        return []


def collect_related_query_set(client: httpx.Client, cfg: TrendsConfig) -> set[str]:
    """对种子词拉 related，合并为小写集合；全部失败则为空。"""
    out: set[str] = set()
    if not cfg.enabled:
        return out
    for seed in cfg.seed_keywords:
        for q in fetch_related_queries(client, cfg, keyword=seed):
            cleaned = q.strip().casefold()
            if cleaned:
                out.add(cleaned)
    logger.info("trends related queries: %s", len(out))
    return out


def _parse_trends_json(text: str) -> Any:
    cleaned = _XSSI_PREFIX.sub("", text.strip())
    return json.loads(cleaned)


def _extract_related_titles(payload: Any) -> list[str]:
    titles: list[str] = []
    if not isinstance(payload, dict):
        return titles
    default = payload.get("default")
    if not isinstance(default, dict):
        return titles
    ranked = default.get("rankedList")
    if not isinstance(ranked, list):
        return titles
    for block in ranked:
        if not isinstance(block, dict):
            continue
        for row in block.get("rankedKeyword") or []:
            if not isinstance(row, dict):
                continue
            query = row.get("query")
            if isinstance(query, str) and query.strip():
                titles.append(query.strip())
    return titles


def _approx_traffic(entry: Any) -> int | None:
    """日榜 RSS 的 ht:approx_traffic 如 '200,000+'。"""
    raw = getattr(entry, "ht_approx_traffic", None) or getattr(
        entry, "approx_traffic", None
    )
    if raw is None and hasattr(entry, "get"):
        raw = entry.get("ht_approx_traffic")
    text = str(raw or "").replace(",", "").replace("+", "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None
