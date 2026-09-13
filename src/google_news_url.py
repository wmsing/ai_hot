"""把 Google News 包装链接解析为媒体原文 URL。"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import quote, urlparse

import httpx

logger = logging.getLogger(__name__)

_GOOGLE_NEWS_HOST = "news.google.com"
_SIG_RE = re.compile(r'data-n-a-sg="([^"]+)"')
_TS_RE = re.compile(r'data-n-a-ts="([^"]+)"')


def is_google_news_article_url(url: str) -> bool:
    return google_news_article_id(url) is not None


def google_news_article_id(url: str) -> str | None:
    parsed = urlparse(url.strip())
    if parsed.hostname != _GOOGLE_NEWS_HOST:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[-2] not in {"articles", "read"}:
        return None
    return parts[-1]


def decode_google_news_url(client: httpx.Client, url: str) -> str | None:
    """解析 Google News 文章链接；失败返回 None。"""
    article_id = google_news_article_id(url)
    if not article_id:
        return None
    params = _fetch_decoding_params(client, article_id)
    if params is None:
        return None
    return _decode_with_batchexecute(
        client,
        article_id=article_id,
        signature=params["signature"],
        timestamp=params["timestamp"],
    )


def _fetch_decoding_params(
    client: httpx.Client,
    article_id: str,
) -> dict[str, str] | None:
    for prefix in ("articles", "rss/articles"):
        try:
            resp = client.get(f"https://news.google.com/{prefix}/{article_id}")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.info(
                "google_news decode params failed prefix=%s err=%s",
                prefix,
                exc,
            )
            continue
        signature = _first_match(resp.text, _SIG_RE)
        timestamp = _first_match(resp.text, _TS_RE)
        if signature and timestamp and timestamp.isdigit():
            return {"signature": signature, "timestamp": timestamp}
    return None


def _decode_with_batchexecute(
    client: httpx.Client,
    *,
    article_id: str,
    signature: str,
    timestamp: str,
) -> str | None:
    payload = [
        "Fbv4je",
        (
            '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",'
            "null,1,null,null,null,null,null,0,1],\"X\",\"X\",1,[1,1,1],"
            f'1,1,null,0,0,null,0],"{article_id}",{timestamp},"{signature}"]'
        ),
    ]
    body = f"f.req={quote(json.dumps([[payload]]))}"
    try:
        resp = client.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            content=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            },
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.info("google_news batchexecute failed err=%s", exc)
        return None
    try:
        chunk = resp.text.split("\n\n", 1)[1]
        parsed = json.loads(chunk)[:-2]
        decoded = json.loads(parsed[0][2])[1]
    except (IndexError, json.JSONDecodeError, TypeError, KeyError) as exc:
        logger.info("google_news batchexecute parse failed err=%s", exc)
        return None
    if not isinstance(decoded, str) or not decoded.startswith(("http://", "https://")):
        return None
    return decoded


def _first_match(text: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.search(text)
    return match.group(1) if match else None
