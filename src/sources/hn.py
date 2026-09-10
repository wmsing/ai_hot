"""Hacker News 数据源（官方 Firebase API）。"""

from __future__ import annotations

import logging

import httpx

from src.models import HnConfig, HotItem
from src.textutil import strip_html, truncate
from src.timeutil import from_unix

logger = logging.getLogger(__name__)

_TOP_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{id}.json"


def fetch_hn_candidates(client: httpx.Client, cfg: HnConfig) -> list[HotItem]:
    """拉取 Top N，按分数/评论阈值筛成候选（未做去重）。"""
    if not cfg.enabled:
        return []

    resp = client.get(_TOP_URL)
    resp.raise_for_status()
    story_ids: list[int] = resp.json()[: cfg.top_n]

    items: list[HotItem] = []
    for story_id in story_ids:
        item_resp = client.get(_ITEM_URL.format(id=story_id))
        item_resp.raise_for_status()
        raw = item_resp.json()
        if not raw or raw.get("type") != "story":
            continue
        title = str(raw.get("title") or "").strip()
        url = str(raw.get("url") or f"https://news.ycombinator.com/item?id={story_id}")
        score = int(raw.get("score") or 0)
        comments = int(raw.get("descendants") or 0)
        if score < cfg.min_score or comments < cfg.min_comments:
            continue
        reason = (
            f"hn score>={cfg.min_score} comments>={cfg.min_comments} "
            f"(score={score}, comments={comments})"
        )
        # Ask HN 等可能有 text；外链帖通常无正文
        body = strip_html(str(raw.get("text") or ""))
        summary = truncate(body, 280) if body else None
        items.append(
            HotItem(
                source="hn",
                title=title,
                url=url,
                score=score,
                comments=comments,
                summary=summary,
                published_at=from_unix(raw.get("time")),
                reason=reason,
            )
        )
    logger.info("hn candidates: %s", len(items))
    return items
