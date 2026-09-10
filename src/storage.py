"""SQLite 持久化：去重冷却与历史条目。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.models import HotItem
from src.normalize import normalize_url, title_key
from src.timeutil import format_published


class ItemStore:
    """热点条目存储。"""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                url_key TEXT NOT NULL,
                title_key TEXT NOT NULL,
                score INTEGER,
                comments INTEGER,
                summary TEXT,
                reason TEXT NOT NULL DEFAULT '',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            )
            """
        )
        self._ensure_column("summary", "TEXT")
        self._ensure_column("published_at", "TEXT")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_items_url_key ON items(url_key)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_items_title_key ON items(title_key)"
        )
        self._conn.commit()

    def _ensure_column(self, name: str, col_type: str) -> None:
        rows = self._conn.execute("PRAGMA table_info(items)").fetchall()
        existing = {str(row["name"]) for row in rows}
        if name not in existing:
            self._conn.execute(f"ALTER TABLE items ADD COLUMN {name} {col_type}")

    def is_seen(
        self, url: str, title: str, *, cooldown_hours: int, now: datetime | None = None
    ) -> bool:
        """冷却窗内 URL 或标题命中任一即视为已见。"""
        moment = now or datetime.now(timezone.utc)
        cutoff = (moment - timedelta(hours=cooldown_hours)).isoformat(
            timespec="seconds"
        )
        uk = normalize_url(url)
        tk = title_key(title)
        row = self._conn.execute(
            """
            SELECT 1 FROM items
            WHERE (url_key = ? OR title_key = ?)
              AND last_seen_at >= ?
            LIMIT 1
            """,
            (uk, tk, cutoff),
        ).fetchone()
        return row is not None

    def upsert_seen(self, item: HotItem, *, now: datetime | None = None) -> None:
        """记录入选条目（同 url_key 更新 last_seen）。"""
        moment = now or datetime.now(timezone.utc)
        ts = moment.isoformat(timespec="seconds")
        uk = normalize_url(item.url)
        tk = title_key(item.title)
        existing = self._conn.execute(
            "SELECT id FROM items WHERE url_key = ? LIMIT 1",
            (uk,),
        ).fetchone()
        published = format_published(item.published_at)
        published_db = None if published == "n/a" else published
        if existing:
            self._conn.execute(
                """
                UPDATE items
                SET title = ?, title_key = ?, score = ?, comments = ?,
                    summary = ?, published_at = ?, reason = ?,
                    last_seen_at = ?, source = ?
                WHERE id = ?
                """,
                (
                    item.title,
                    tk,
                    item.score,
                    item.comments,
                    item.summary,
                    published_db,
                    item.reason,
                    ts,
                    item.source,
                    existing["id"],
                ),
            )
        else:
            self._conn.execute(
                """
                INSERT INTO items (
                    source, url, title, url_key, title_key,
                    score, comments, summary, published_at, reason,
                    first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.source,
                    item.url,
                    item.title,
                    uk,
                    tk,
                    item.score,
                    item.comments,
                    item.summary,
                    published_db,
                    item.reason,
                    ts,
                    ts,
                ),
            )
        self._conn.commit()
