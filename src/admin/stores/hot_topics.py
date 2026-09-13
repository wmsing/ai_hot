"""今日热搜快照 CRUD。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.hot_topics_probe import load_hot_topics_snapshot
from src.models import HotTopicSnapshot, HotTopicSnapshotItem
from src.normalize import normalize_url


def load_snapshot(path: Path) -> HotTopicSnapshot:
    snapshot = load_hot_topics_snapshot(path)
    if snapshot is None:
        return HotTopicSnapshot(generated_at=datetime.now(timezone.utc), items=[])
    return snapshot


def save_snapshot(path: Path, snapshot: HotTopicSnapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")


def add_item(path: Path, item: HotTopicSnapshotItem) -> HotTopicSnapshot:
    snapshot = load_snapshot(path)
    key = normalize_url(item.url)
    for existing in snapshot.items:
        if normalize_url(existing.url) == key:
            raise ValueError(f"URL already exists: {item.url}")
    updated = snapshot.model_copy(
        update={
            "generated_at": datetime.now(timezone.utc),
            "items": [*snapshot.items, item],
        }
    )
    save_snapshot(path, updated)
    return updated


def update_item(
    path: Path,
    url: str,
    *,
    updates: dict[str, object],
) -> HotTopicSnapshot:
    snapshot = load_snapshot(path)
    key = normalize_url(url)
    found = False
    new_items: list[HotTopicSnapshotItem] = []
    for item in snapshot.items:
        if normalize_url(item.url) != key:
            new_items.append(item)
            continue
        found = True
        new_items.append(item.model_copy(update=updates))
    if not found:
        raise ValueError(f"URL not found: {url}")
    updated = snapshot.model_copy(
        update={
            "generated_at": datetime.now(timezone.utc),
            "items": new_items,
        }
    )
    save_snapshot(path, updated)
    return updated


def delete_item(path: Path, url: str) -> HotTopicSnapshot:
    snapshot = load_snapshot(path)
    key = normalize_url(url)
    new_items = [item for item in snapshot.items if normalize_url(item.url) != key]
    if len(new_items) == len(snapshot.items):
        raise ValueError(f"URL not found: {url}")
    updated = snapshot.model_copy(
        update={
            "generated_at": datetime.now(timezone.utc),
            "items": new_items,
        }
    )
    save_snapshot(path, updated)
    return updated


def find_item(path: Path, url: str) -> HotTopicSnapshotItem | None:
    key = normalize_url(url)
    for item in load_snapshot(path).items:
        if normalize_url(item.url) == key:
            return item
    return None
