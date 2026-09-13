"""Admin store CRUD 单元测试。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.admin.stores import digest as digest_store
from src.admin.stores import hot_topics as hot_topics_store
from src.models import HotTopicSnapshotItem


def test_hot_topics_crud(tmp_path: Path) -> None:
    path = tmp_path / "latest.json"
    item = HotTopicSnapshotItem(
        heat=1.5,
        source="manual",
        title="Hello",
        url="https://example.com/a",
        reason="test",
    )
    hot_topics_store.add_item(path, item)
    loaded = hot_topics_store.load_snapshot(path)
    assert len(loaded.items) == 1
    assert loaded.items[0].title == "Hello"

    hot_topics_store.update_item(
        path,
        "https://example.com/a",
        updates={"title_zh": "你好"},
    )
    updated = hot_topics_store.find_item(path, "https://example.com/a")
    assert updated is not None
    assert updated.title_zh == "你好"

    hot_topics_store.delete_item(path, "https://example.com/a")
    assert hot_topics_store.load_snapshot(path).items == []


def test_hot_topics_duplicate_url(tmp_path: Path) -> None:
    path = tmp_path / "latest.json"
    item = HotTopicSnapshotItem(
        heat=1.0,
        source="manual",
        title="A",
        url="https://example.com/a",
    )
    hot_topics_store.add_item(path, item)
    with pytest.raises(ValueError, match="already exists"):
        hot_topics_store.add_item(path, item)


def test_digest_crud(tmp_path: Path) -> None:
    day = date(2026, 9, 13)
    _write_sample_digest(tmp_path, day)
    content_dir = tmp_path

    view = digest_store.get_day(content_dir, day)
    base_count = len(view.items)

    added = digest_store.add_item(
        content_dir,
        day,
        title_en="New item",
        title_zh="新条目",
        url="https://example.com/new",
        source="manual",
        summary_en="short",
        summary_zh="短摘要",
    )
    assert added.index == (view.items[-1].index if view.items else 0) + 1

    updated = digest_store.update_item(
        content_dir,
        day,
        added.index,
        summary_zh="更新后的摘要",
    )
    assert "更新后的摘要" in updated.summary_zh

    digest_store.delete_item(content_dir, day, added.index)
    after = digest_store.get_day(content_dir, day)
    assert len(after.items) == base_count


def _write_sample_digest(tmp_path: Path, day: date) -> None:
    day_s = day.isoformat()
    en = f"""# ai_hot digest

Generated (UTC): 2026-09-13T10:00:00+00:00
Selected: 1

## 1. Sample title

- source: `manual`
- url: https://example.com/sample
- summary: Sample summary
"""
    zh = f"""# ai_hot digest

Generated (UTC): 2026-09-13T10:00:00+00:00
Selected: 1

## 1. 示例标题

- source: `manual`
- url: https://example.com/sample
- summary: 示例摘要
"""
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / f"{day_s}.en.md").write_text(en, encoding="utf-8")
    (tmp_path / f"{day_s}.zh.md").write_text(zh, encoding="utf-8")


def test_has_adhd_summary() -> None:
    assert digest_store.has_adhd_summary("⚡️ 一句话总结\nfoo\n🔥 核心亮点")
    assert not digest_store.has_adhd_summary("plain summary")
