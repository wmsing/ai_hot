"""热搜复制到 Digest。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.admin.stores import digest as digest_store
from src.admin.stores import hot_topics as hot_topics_store
from src.models import AppConfig, HotTopicSnapshotItem, PathsConfig


def _hot_item(**kwargs: object) -> HotTopicSnapshotItem:
    base = {
        "heat": 9.5,
        "source": "google_news:ai",
        "title": "Nvidia is the central bank of AI",
        "url": "https://example.com/nvidia",
        "title_zh": "英伟达是人工智能的中央银行",
        "summary_en": "⚡️ One-liner\nNvidia powers the AI economy.\n\n🔥 Key takeaways\n✅ Chips",
        "summary_zh": "⚡️ 一句话总结\n英伟达撑起 AI 经济。\n\n🔥 核心亮点\n✅ 芯片",
    }
    base.update(kwargs)
    return HotTopicSnapshotItem(**base)


def test_copy_hot_topic_to_digest_creates_item(tmp_path: Path) -> None:
    from src.admin.services.copy_hot_to_digest import copy_hot_topic_to_digest

    hot_path = tmp_path / "hot_topics" / "latest.json"
    digests_dir = tmp_path / "digests"
    digests_dir.mkdir(parents=True)
    day = date(2026, 9, 13)
    hot_topics_store.add_item(hot_path, _hot_item())
    cfg = AppConfig(
        paths=PathsConfig(
            hot_topics_path=str(hot_path),
            content_digests_dir=str(digests_dir),
        )
    )

    result = copy_hot_topic_to_digest(
        cfg,
        day=day,
        url="https://example.com/nvidia",
    )
    assert result["created"] is True
    assert result["index"] == 1
    view = digest_store.get_day(digests_dir, day)
    item = view.items[0]
    assert item.title_en == "Nvidia is the central bank of AI"
    assert item.title_zh == "英伟达是人工智能的中央银行"
    assert "One-liner" in item.summary_en
    assert "一句话总结" in item.summary_zh
    assert item.speak_en
    assert item.speak_zh
    assert "⚡️" not in item.speak_en


def test_copy_hot_topic_to_digest_updates_existing_url(tmp_path: Path) -> None:
    from src.admin.services.copy_hot_to_digest import copy_hot_topic_to_digest

    hot_path = tmp_path / "hot_topics" / "latest.json"
    digests_dir = tmp_path / "digests"
    digests_dir.mkdir(parents=True)
    day = date(2026, 9, 13)
    hot_topics_store.add_item(hot_path, _hot_item())
    digest_store.add_item(
        digests_dir,
        day,
        title_en="Old title",
        title_zh="旧标题",
        url="https://example.com/nvidia",
        source="manual",
        summary_en="old summary",
        summary_zh="旧摘要",
    )
    cfg = AppConfig(
        paths=PathsConfig(
            hot_topics_path=str(hot_path),
            content_digests_dir=str(digests_dir),
        )
    )

    result = copy_hot_topic_to_digest(
        cfg,
        day=day,
        url="https://example.com/nvidia/",
    )
    assert result["created"] is False
    assert result["index"] == 1
    view = digest_store.get_day(digests_dir, day)
    assert len(view.items) == 1
    assert view.items[0].title_zh == "英伟达是人工智能的中央银行"
    assert "一句话总结" in view.items[0].summary_zh


def test_match_hot_topic_for_digest_detects_copyable_item() -> None:
    from src.admin.services.copy_hot_to_digest import match_hot_topic_for_digest
    from src.admin.stores.digest import MergedDigestItem

    hot = _hot_item()
    digest = MergedDigestItem(
        index=2,
        title_en="Nvidia is the central bank of AI",
        title_zh="英伟达是人工智能的央行",
        url="https://example.com/nvidia",
        source="hn",
        published="",
        score_line="",
        summary_en="plain en",
        summary_zh="普通摘要",
        speak_en="",
        speak_zh="",
    )
    match, can_copy = match_hot_topic_for_digest(digest, hot)
    assert match is True
    assert can_copy is True


def test_match_hot_topic_for_digest_skips_when_digest_has_adhd() -> None:
    from src.admin.services.copy_hot_to_digest import match_hot_topic_for_digest
    from src.admin.stores.digest import MergedDigestItem

    hot = _hot_item()
    digest = MergedDigestItem(
        index=2,
        title_en="Nvidia is the central bank of AI",
        title_zh="英伟达是人工智能的央行",
        url="https://example.com/nvidia",
        source="hn",
        published="",
        score_line="",
        summary_en="⚡️ One-liner\nDone.\n\n🔥 Key takeaways\n✅ One",
        summary_zh="⚡️ 一句话总结\n完成。\n\n🔥 核心亮点\n✅ 一条",
        speak_en="",
        speak_zh="",
    )
    match, can_copy = match_hot_topic_for_digest(digest, hot)
    assert match is True
    assert can_copy is False


def test_copy_hot_topic_missing_url(tmp_path: Path) -> None:
    from src.admin.services.copy_hot_to_digest import copy_hot_topic_to_digest

    cfg = AppConfig(
        paths=PathsConfig(
            hot_topics_path=str(tmp_path / "hot_topics" / "latest.json"),
            content_digests_dir=str(tmp_path / "digests"),
        )
    )
    with pytest.raises(ValueError, match="not found"):
        copy_hot_topic_to_digest(cfg, day=date(2026, 9, 13), url="https://missing.test")


