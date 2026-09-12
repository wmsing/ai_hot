"""Reddit 公开列表：先试 JSON，失败则回退 Atom RSS。"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import feedparser
import httpx

from src.models import HotItem, RedditConfig
from src.textutil import strip_html, truncate
from src.timeutil import from_rss_entry, from_unix

logger = logging.getLogger(__name__)

_REDDIT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
_HOSTS = (
    "https://www.reddit.com",
    "https://old.reddit.com",
)
_SCORE_RE = re.compile(r"(\d+)\s+points?", re.IGNORECASE)
_COMMENTS_RE = re.compile(r"(\d+)\s+comments?", re.IGNORECASE)


def fetch_reddit_candidates(client: httpx.Client, cfg: RedditConfig) -> list[HotItem]:
    """拉取各 subreddit；JSON 403/失败时改走 Atom RSS。"""
    if not cfg.enabled:
        return []

    items: list[HotItem] = []
    for idx, sub in enumerate(cfg.subreddits):
        name = sub.strip().removeprefix("r/")
        if not name:
            continue
        if idx:
            time.sleep(0.6)
        sub_items = _fetch_subreddit(client, cfg, name)
        items.extend(sub_items)
    logger.info("reddit candidates: %s", len(items))
    return items


def _fetch_subreddit(
    client: httpx.Client, cfg: RedditConfig, name: str
) -> list[HotItem]:
    payload = _fetch_json(client, cfg, name)
    if payload is not None:
        return _items_from_json(payload, cfg, name)
    return _items_from_rss(client, cfg, name)


def _headers() -> dict[str, str]:
    return {
        "User-Agent": _REDDIT_UA,
        "Accept": (
            "application/json, application/atom+xml, application/xml;q=0.9, */*;q=0.8"
        ),
    }


def _fetch_json(
    client: httpx.Client, cfg: RedditConfig, name: str
) -> dict[str, Any] | None:
    params: dict[str, str | int] = {"limit": cfg.limit, "raw_json": 1}
    if cfg.listing == "top":
        params["t"] = cfg.time_filter
    last_err: Exception | None = None
    for host in _HOSTS:
        url = f"{host}/r/{name}/{cfg.listing}.json"
        try:
            resp = client.get(url, params=params, headers=_headers())
            resp.raise_for_status()
            payload = resp.json()
            if isinstance(payload, dict):
                return payload
            return None
        except (httpx.HTTPError, ValueError) as exc:
            last_err = exc
            continue
    logger.info("reddit json unavailable sub=%s err=%s; try rss", name, last_err)
    return None


def _items_from_json(
    payload: dict[str, Any], cfg: RedditConfig, name: str
) -> list[HotItem]:
    children = (payload.get("data") or {}).get("children")
    if not isinstance(children, list):
        return []
    items: list[HotItem] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        data = child.get("data")
        if not isinstance(data, dict):
            continue
        title = str(data.get("title") or "").strip()
        if not title:
            continue
        score = int(data.get("score") or 0)
        if score < cfg.min_score:
            continue
        comments = int(data.get("num_comments") or 0)
        permalink = str(data.get("permalink") or "").strip()
        external = str(data.get("url") or "").strip()
        if permalink:
            link = f"https://www.reddit.com{permalink}"
        elif external:
            link = external
        else:
            continue
        selftext = str(data.get("selftext") or "").strip()
        summary = truncate(selftext, 280) if selftext else None
        items.append(
            HotItem(
                source=f"reddit:{name}",
                title=title,
                url=link,
                score=score,
                comments=comments,
                summary=summary,
                published_at=from_unix(data.get("created_utc")),
                reason=(
                    f"reddit r/{name} {cfg.listing} "
                    f"(score={score}, comments={comments})"
                ),
            )
        )
    return items


def _entry_blob(entry: Any) -> str:
    summary = str(getattr(entry, "summary", "") or "")
    if summary:
        return strip_html(summary)
    content = getattr(entry, "content", None)
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict):
            return strip_html(str(first.get("value") or ""))
    return ""


def _items_from_rss(
    client: httpx.Client, cfg: RedditConfig, name: str
) -> list[HotItem]:
    """Atom RSS 回退；score 尽量从正文解析，否则用位次近似。"""
    params: dict[str, str | int] = {"limit": cfg.limit}
    if cfg.listing == "top":
        params["t"] = cfg.time_filter
        path = f"/r/{name}/top/.rss"
    else:
        path = f"/r/{name}/.rss"
    last_err: Exception | None = None
    text: str | None = None
    for host in _HOSTS:
        url = f"{host}{path}"
        try:
            resp = client.get(url, params=params, headers=_headers())
            resp.raise_for_status()
            text = resp.text
            break
        except httpx.HTTPError as exc:
            last_err = exc
            continue
    if text is None:
        logger.warning("reddit rss failed sub=%s err=%s", name, last_err)
        return []

    parsed: Any = feedparser.parse(text)
    entries = list(getattr(parsed, "entries", []) or [])
    items: list[HotItem] = []
    for rank, entry in enumerate(entries[: cfg.limit], start=1):
        title = str(getattr(entry, "title", "") or "").strip()
        link = str(getattr(entry, "link", "") or "").strip()
        if not title or not link:
            continue
        blob = _entry_blob(entry)
        score_m = _SCORE_RE.search(blob)
        comments_m = _COMMENTS_RE.search(blob)
        if score_m:
            score = int(score_m.group(1))
            if score < cfg.min_score:
                continue
        else:
            score = max(cfg.limit - rank + 1, 1) * 5
        comments = int(comments_m.group(1)) if comments_m else 0
        summary = truncate(blob, 280) if blob else None
        items.append(
            HotItem(
                source=f"reddit:{name}",
                title=title,
                url=link,
                score=score,
                comments=comments,
                summary=summary,
                published_at=from_rss_entry(entry),
                reason=f"reddit r/{name} rss rank={rank}",
            )
        )
    return items
