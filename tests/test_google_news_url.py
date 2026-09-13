"""Google News URL 解码。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import pytest

from src.google_news_url import (
    decode_google_news_url,
    google_news_article_id,
    is_google_news_article_url,
)
from src.models import GoogleNewsConfig, GoogleNewsQuery
from src.sources.google_news import fetch_google_news_candidates


def test_google_news_article_id_from_rss_link() -> None:
    url = "https://news.google.com/rss/articles/CBMiTEST?oc=5"
    assert google_news_article_id(url) == "CBMiTEST"
    assert is_google_news_article_url(url)


def test_decode_google_news_url_returns_publisher_link() -> None:
    article_id = "CBMiTEST"
    google_url = f"https://news.google.com/rss/articles/{article_id}?oc=5"
    publisher_url = "https://www.aljazeera.com/news/2026/9/13/example"
    inner = json.dumps(["garturlres", publisher_url])

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and f"/articles/{article_id}" in request.url.path:
            html = '<div data-n-a-sg="sig123" data-n-a-ts="1789316544"></div>'
            return httpx.Response(200, text=html)
        if request.method == "POST" and "batchexecute" in str(request.url):
            body = json.dumps(
                [
                    ["wrb.fr", "Fbv4je", inner, None, None, None, [3], "generic"],
                    ["di", 13],
                    ["af.httprm", 10, "1504922693333604431", 7],
                ]
            )
            return httpx.Response(200, text=")]}'\n\n" + body)
        return httpx.Response(404)

    transport = httpx.MockTransport(_handler)
    client = httpx.Client(transport=transport)
    assert decode_google_news_url(client, google_url) == publisher_url


def test_fetch_google_news_candidates_resolves_article_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rss = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>AI</title>
<item>
  <title>Al Jazeera story</title>
  <link>https://news.google.com/rss/articles/CBMiTEST?oc=5</link>
  <pubDate>Fri, 12 Sep 2026 10:00:00 GMT</pubDate>
  <description>Blurb</description>
</item>
</channel></rss>
"""
    client = MagicMock()
    client.get.return_value = MagicMock(
        status_code=200,
        raise_for_status=MagicMock(),
        text=rss,
    )
    monkeypatch.setattr(
        "src.sources.google_news.decode_google_news_url",
        lambda _client, url: "https://www.aljazeera.com/news/example",
    )
    cfg = GoogleNewsConfig(
        queries=[GoogleNewsQuery(name="ai_en", query="artificial intelligence")],
        max_per_query=5,
    )
    items = fetch_google_news_candidates(client, cfg)
    assert len(items) == 1
    assert items[0].url == "https://www.aljazeera.com/news/example"
