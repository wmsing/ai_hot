"""Threads Keyword / Topic Tag Search（需 access token）。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from src.models import HotItem, ThreadsConfig
from src.textutil import truncate

logger = logging.getLogger(__name__)

_GRAPH = "https://graph.threads.net/v1.0/keyword_search"


def fetch_threads_candidates(
    client: httpx.Client,
    cfg: ThreadsConfig,
    *,
    access_token: str,
) -> list[HotItem]:
    """对种子 tag 拉 TOP/RECENT；无 token 或关闭时返回 []。"""
    if not cfg.enabled:
        return []
    token = access_token.strip()
    if not token:
        logger.info("threads skipped: no THREADS_ACCESS_TOKEN")
        return []

    items: list[HotItem] = []
    for tag in cfg.seed_tags:
        q = tag.strip().lstrip("#")
        if not q:
            continue
        params: dict[str, str | int] = {
            "q": q,
            "search_mode": "TAG",
            "search_type": cfg.search_type,
            "limit": min(cfg.limit, 100),
            "fields": "id,text,permalink,timestamp,username,media_type",
            "access_token": token,
        }
        try:
            resp = client.get(_GRAPH, params=params)
            resp.raise_for_status()
            payload: dict[str, Any] = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("threads search failed tag=%s err=%s", q, exc)
            continue

        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            text = str(row.get("text") or "").strip()
            permalink = str(row.get("permalink") or "").strip()
            if not permalink:
                continue
            title = truncate(text.replace("\n", " "), 120) if text else f"#{q}"
            published = _parse_ts(row.get("timestamp"))
            username = str(row.get("username") or "").strip()
            items.append(
                HotItem(
                    source=f"threads:{q}",
                    title=title or f"#{q}",
                    url=permalink,
                    score=None,
                    comments=None,
                    summary=truncate(text, 280) if text else None,
                    published_at=published,
                    reason=(
                        f"threads tag=#{q} type={cfg.search_type}"
                        + (f" @{username}" if username else "")
                    ),
                )
            )
    logger.info("threads candidates: %s", len(items))
    return items


def _parse_ts(raw: Any) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith("+0000"):
        text = text[:-5] + "+00:00"
    elif text.endswith("-0000"):
        text = text[:-5] + "+00:00"
    text = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
