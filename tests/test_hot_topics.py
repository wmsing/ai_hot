"""Reddit / Google News / Trends / Threads / hot_score 测试。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx

from src.hot_score import cluster_and_rank, heat_score, source_family
from src.models import (
    GoogleNewsConfig,
    GoogleNewsQuery,
    HotItem,
    HotTopicsConfig,
    RedditConfig,
    ThreadsConfig,
    TrendsConfig,
)
from src.sources.google_news import fetch_google_news_candidates
from src.sources.reddit import fetch_reddit_candidates
from src.sources.threads import fetch_threads_candidates
from src.sources.trends import fetch_related_queries, fetch_trends_daily_candidates


def _mock_response(payload: Any, *, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "err",
            request=MagicMock(),
            response=MagicMock(status_code=status_code),
        )
    if isinstance(payload, str):
        resp.text = payload
        resp.json.side_effect = ValueError("not json")
    else:
        resp.text = json.dumps(payload)
        resp.json.return_value = payload
    return resp


def test_source_family() -> None:
    assert source_family("reddit:LocalLLaMA") == "reddit"
    assert source_family("hn") == "hn"


def test_cluster_and_rank_prefers_higher_heat() -> None:
    now = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    a = HotItem(
        source="hn",
        title="Same Story",
        url="https://example.com/a?utm_source=x",
        score=200,
        comments=50,
        published_at=now - timedelta(hours=1),
        reason="hn",
    )
    b = HotItem(
        source="reddit:OpenAI",
        title="Same Story",
        url="https://example.com/a",
        score=10,
        comments=1,
        published_at=now - timedelta(hours=1),
        reason="reddit",
    )
    ranked = cluster_and_rank(
        [a, b],
        HotTopicsConfig(top_n=5),
        now=now,
        related_queries={"same story"},
    )
    assert len(ranked) == 1
    assert ranked[0][1].source == "hn"
    assert ranked[0][1].sources == ["hn", "reddit"]
    assert "merged_sources=hn+reddit" in ranked[0][1].reason
    assert "trends_related" in ranked[0][1].reason


def test_cluster_and_rank_single_source() -> None:
    now = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    item = HotItem(
        source="hn",
        title="Only HN",
        url="https://example.com/only",
        score=100,
        comments=10,
        published_at=now,
        reason="hn",
    )
    ranked = cluster_and_rank([item], HotTopicsConfig(top_n=5), now=now)
    assert len(ranked) == 1
    assert ranked[0][1].sources == ["hn"]
    assert "merged_sources" not in ranked[0][1].reason


def test_cluster_and_rank_three_sources() -> None:
    now = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    url = "https://example.com/story"
    items = [
        HotItem(
            source="hn",
            title="Story",
            url=url,
            score=300,
            comments=50,
            published_at=now,
            reason="hn",
        ),
        HotItem(
            source="reddit:OpenAI",
            title="Story",
            url=url,
            score=20,
            comments=5,
            published_at=now,
            reason="reddit",
        ),
        HotItem(
            source="google_news:ai_en",
            title="Story",
            url=url,
            score=10,
            comments=0,
            published_at=now,
            reason="google_news",
        ),
    ]
    ranked = cluster_and_rank(items, HotTopicsConfig(top_n=5), now=now)
    assert len(ranked) == 1
    assert ranked[0][1].sources == ["hn", "reddit", "google_news"]
    assert "merged_sources=hn+reddit+google_news" in ranked[0][1].reason


def test_heat_score_trends_boost() -> None:
    now = datetime(2026, 9, 12, tzinfo=timezone.utc)
    item = HotItem(
        source="google_news:ai_en",
        title="LLM news",
        url="https://example.com/1",
        score=20,
        comments=0,
        published_at=now,
        reason="g",
    )
    cfg = HotTopicsConfig()
    base = heat_score(item, cfg, now=now, trends_hit=False)
    boosted = heat_score(item, cfg, now=now, trends_hit=True)
    assert boosted == base + cfg.trends_boost


def test_fetch_reddit_candidates() -> None:
    payload = {
        "data": {
            "children": [
                {
                    "data": {
                        "title": "New open LLM release",
                        "score": 120,
                        "num_comments": 40,
                        "permalink": "/r/LocalLLaMA/comments/abc/new/",
                        "url": "https://example.com/paper",
                        "selftext": "details here",
                        "created_utc": 1725000000,
                    }
                },
                {
                    "data": {
                        "title": "low score",
                        "score": 1,
                        "num_comments": 0,
                        "permalink": "/r/LocalLLaMA/comments/x/low/",
                        "url": "https://example.com/low",
                        "selftext": "",
                        "created_utc": 1725000000,
                    }
                },
            ]
        }
    }
    client = MagicMock()
    client.get.return_value = _mock_response(payload)
    items = fetch_reddit_candidates(
        client,
        RedditConfig(subreddits=["LocalLLaMA"], min_score=20, limit=10),
    )
    assert len(items) == 1
    assert items[0].source == "reddit:LocalLLaMA"
    assert items[0].score == 120
    assert "reddit.com" in items[0].url


def test_fetch_google_news_candidates() -> None:
    rss = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>AI</title>
<item>
  <title>OpenAI ships new model</title>
  <link>https://news.example.com/openai</link>
  <pubDate>Fri, 12 Sep 2026 10:00:00 GMT</pubDate>
  <description>A short blurb about the model.</description>
</item>
</channel></rss>
"""
    client = MagicMock()
    client.get.return_value = _mock_response(rss)
    cfg = GoogleNewsConfig(
        queries=[
            GoogleNewsQuery(name="ai_en", query="artificial intelligence when:1d")
        ],
        max_per_query=5,
    )
    items = fetch_google_news_candidates(client, cfg)
    assert len(items) == 1
    assert items[0].source == "google_news:ai_en"
    assert items[0].title.startswith("OpenAI")


def test_fetch_trends_daily_filters_ai() -> None:
    rss = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:ht="https://trends.google.com/trends/trendingsearches/daily">
<channel>
<item>
  <title>ChatGPT update</title>
  <link>https://trends.google.com/chatgpt</link>
  <ht:approx_traffic>200,000+</ht:approx_traffic>
</item>
<item>
  <title>Sports final</title>
  <link>https://trends.google.com/sports</link>
</item>
</channel></rss>
"""
    client = MagicMock()
    client.get.return_value = _mock_response(rss)
    items = fetch_trends_daily_candidates(client, TrendsConfig(geo="US"))
    assert len(items) == 1
    assert items[0].source == "trends"
    assert "ChatGPT" in items[0].title


def test_fetch_related_queries_soft_fail() -> None:
    client = MagicMock()
    client.get.side_effect = httpx.ConnectError("down")
    assert fetch_related_queries(client, TrendsConfig(), keyword="AI") == []


def test_fetch_reddit_rss_fallback() -> None:
    rss = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
 <entry>
  <title>RSS LLM thread</title>
  <link href="https://www.reddit.com/r/LocalLLaMA/comments/abc/rss/"/>
  <updated>2026-09-12T10:00:00+00:00</updated>
  <content type="html">submitted by user 88 points 12 comments</content>
 </entry>
</feed>
"""
    client = MagicMock()
    blocked = _mock_response("blocked", status_code=403)
    ok = _mock_response(rss)
    client.get.side_effect = [blocked, blocked, ok]
    items = fetch_reddit_candidates(
        client,
        RedditConfig(subreddits=["LocalLLaMA"], min_score=20, limit=10),
    )
    assert len(items) == 1
    assert items[0].title == "RSS LLM thread"
    assert "rss" in items[0].reason


def test_fetch_threads_requires_token() -> None:
    client = MagicMock()
    items = fetch_threads_candidates(
        client,
        ThreadsConfig(enabled=True, seed_tags=["AI"]),
        access_token="",
    )
    assert items == []
    client.get.assert_not_called()


def test_load_hot_topics_snapshot_roundtrip(tmp_path: Path) -> None:
    from src.hot_topics_probe import load_hot_topics_snapshot, save_hot_topics_snapshot
    from src.models import HotItem

    path = tmp_path / "latest.json"
    item = HotItem(
        source="hn",
        title="Test topic",
        url="https://example.com/t",
        score=100,
        comments=20,
    )
    save_hot_topics_snapshot(path, [(8.5, item)])
    loaded = load_hot_topics_snapshot(path)
    assert loaded is not None
    assert len(loaded.items) == 1
    assert loaded.items[0].title == "Test topic"
    assert loaded.items[0].heat == 8.5


def test_fetch_threads_candidates() -> None:
    payload = {
        "data": [
            {
                "id": "1",
                "text": "Claude just dropped a huge update",
                "permalink": "https://www.threads.net/@u/post/1",
                "timestamp": "2026-09-12T10:00:00+0000",
                "username": "u",
            }
        ]
    }
    client = MagicMock()
    client.get.return_value = _mock_response(payload)
    items = fetch_threads_candidates(
        client,
        ThreadsConfig(enabled=True, seed_tags=["Claude"], limit=10),
        access_token="tok",
    )
    assert len(items) == 1
    assert items[0].source == "threads:Claude"
    assert items[0].url.endswith("/post/1")
