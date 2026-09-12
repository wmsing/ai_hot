"""YouTube RSS 过滤 / max_age / 站点 embed。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import httpx

from src.models import FeedConfig, RssConfig
from src.site_build import build_site, youtube_video_id
from src.sources.rss import fetch_rss_candidates

_YT_FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
 <title>OpenAI</title>
 <entry>
  <id>yt:video:ZlvkQYZo3ZE</id>
  <title>GPT-6 Astra added unexpected details</title>
  <link rel="alternate" href="https://www.youtube.com/shorts/ZlvkQYZo3ZE"/>
  <published>2026-09-11T21:00:04+00:00</published>
  <media:group>
   <media:thumbnail url="https://i.ytimg.com/vi/ZlvkQYZo3ZE/hqdefault.jpg"/>
   <media:description>short</media:description>
  </media:group>
 </entry>
 <entry>
  <id>yt:video:OSaP6bJoU44</id>
  <title>GPT-Live-1 is now in the API</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=OSaP6bJoU44"/>
  <published>2026-09-11T17:06:25+00:00</published>
  <media:group>
   <media:thumbnail url="https://i.ytimg.com/vi/OSaP6bJoU44/hqdefault.jpg"/>
   <media:description>GPT-Live-1 is now available in the API.</media:description>
  </media:group>
 </entry>
 <entry>
  <id>yt:video:2YHa1vhnmK0</id>
  <title>Introducing the Agents API</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=2YHa1vhnmK0"/>
  <published>2026-09-10T12:00:00+00:00</published>
  <media:group>
   <media:thumbnail url="https://i.ytimg.com/vi/2YHa1vhnmK0/hqdefault.jpg"/>
   <media:description>Agents API overview.</media:description>
  </media:group>
 </entry>
</feed>
"""


def test_youtube_video_id() -> None:
    assert youtube_video_id("https://www.youtube.com/watch?v=OSaP6bJoU44") == (
        "OSaP6bJoU44"
    )
    assert (
        youtube_video_id("https://www.youtube.com/watch?v=OSaP6bJoU44&t=12")
        == "OSaP6bJoU44"
    )
    assert youtube_video_id("https://youtu.be/OSaP6bJoU44") == "OSaP6bJoU44"
    assert youtube_video_id("https://www.youtube.com/shorts/ZlvkQYZo3ZE") is None
    assert youtube_video_id("https://example.com/a") is None


def test_within_max_age_last_day() -> None:
    from src.pipeline import _within_max_age

    now = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    assert _within_max_age(
        now - timedelta(hours=23),
        now=now,
        max_age_hours=24,
    )
    assert not _within_max_age(
        now - timedelta(hours=25),
        now=now,
        max_age_hours=24,
    )
    assert not _within_max_age(None, now=now, max_age_hours=24)


def test_config_youtube_feeds_latest_one() -> None:
    from src.config import load_app_config

    cfg = load_app_config()
    yt = {
        f.name: f
        for f in cfg.rss.feeds
        if f.name in {"openai_youtube", "claude_youtube", "grok_youtube"}
    }
    assert set(yt) == {"openai_youtube", "claude_youtube", "grok_youtube"}
    for name, feed in yt.items():
        assert feed.max_new == 1, name
        assert feed.max_age_hours is None, name
        assert "/shorts/" in feed.exclude_url_contains
        assert feed.tag == "video"
        assert "channel_id=" in str(feed.url)


def test_fetch_rss_skips_shorts_and_respects_max_fetch(monkeypatch) -> None:
    cfg = RssConfig(
        max_new_per_feed=5,
        feeds=[
            FeedConfig(
                name="openai_youtube",
                url="https://www.youtube.com/feeds/videos.xml?channel_id=UCXZCJLdBC09xxGZ6gcdrc6A",
                max_new=1,
                exclude_url_contains=["/shorts/"],
                tag="video",
            )
        ],
    )

    def fake_get(self: httpx.Client, url: str, **kwargs: object) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.text = _YT_FEED_XML
        return resp

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    with httpx.Client() as client:
        items = fetch_rss_candidates(client, cfg)

    assert len(items) == 1  # Shorts 已滤；只要最新 1 条长视频
    assert items[0].url == "https://www.youtube.com/watch?v=OSaP6bJoU44"
    assert items[0].source == "rss:openai_youtube"
    assert items[0].tag == "video"
    assert items[0].image_url and "OSaP6bJoU44" in items[0].image_url
    assert all("/shorts/" not in i.url for i in items)


def test_build_site_embeds_youtube(tmp_path: Path) -> None:
    content = tmp_path / "digests"
    content.mkdir()
    (content / "2026-09-12.en.md").write_text(
        """# ai_hot digest

Generated (UTC): 2026-09-12T05:00:00+00:00
Selected: 1

## 1. GPT-Live-1 is now in the API

- source: `rss:openai_youtube`
- url: https://www.youtube.com/watch?v=OSaP6bJoU44
- published: 2026-09-11T17:06:25+00:00
- tag: video
- image: https://i.ytimg.com/vi/OSaP6bJoU44/hqdefault.jpg
- summary: GPT-Live-1 is now available in the API.
""",
        encoding="utf-8",
    )
    (content / "2026-09-12.zh.md").write_text(
        """# ai_hot 消息摘要

生成时间（UTC）：2026-09-12T05:00:00+00:00
精选：1

## 1. GPT-Live-1 现已登陆 API

- 来源：`rss:openai_youtube`
- 链接：https://www.youtube.com/watch?v=OSaP6bJoU44
- 发布时间：2026-09-11T17:06:25+00:00
- 标签：video
- 图片：https://i.ytimg.com/vi/OSaP6bJoU44/hqdefault.jpg
- 摘要：GPT-Live-1 现已在 API 中可用。
""",
        encoding="utf-8",
    )
    out = tmp_path / "public"
    build_site(content_dir=content, output_dir=out)
    home = (out / "index.html").read_text(encoding="utf-8")
    assert 'class="item-thumb item-thumb-video"' in home
    assert 'data-yt="OSaP6bJoU44"' in home
    assert 'class="yt-facade"' in home
    assert "i.ytimg.com/vi/OSaP6bJoU44" in home
    assert "youtube-nocookie.com/embed" not in home
    assert 'name="referrer" content="strict-origin-when-cross-origin"' in home
    assert 'data-tag="video"' in home
    assert 'class="feed-filter"' in home
    assert 'data-filter="video"' in home
    assert 'data-filter="openai"' in home
    assert ">Video<" in home
    # sticky / 排序跟真实发布日，不跟归档日 2026-09-12
    assert 'data-day="2026-09-11"' in home
    assert 'data-day="2026-09-12"' not in home
    styles = (out / "styles.css").read_text(encoding="utf-8")
    assert ".yt-facade" in styles
    assert ".item-thumb iframe" in styles
    assert 'data-tag="video"' in styles
    assert ".feed-filter" in styles
    feed_js = (out / "feed.js").read_text(encoding="utf-8")
    assert "applyTagFilter" in feed_js
    assert "data-filter" in feed_js
    assert 'searchParams.set("source"' in feed_js
    assert "mountYoutube" in feed_js
    assert "youtube.com/embed/" in feed_js
    assert (out / "_headers").is_file()
    assert "Referrer-Policy: strict-origin-when-cross-origin" in (
        out / "_headers"
    ).read_text(encoding="utf-8")
    assert 'data-source="rss:openai_youtube"' in styles or (
        "rss:openai_youtube" in styles
    )
