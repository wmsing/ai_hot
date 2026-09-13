"""扫描 content/digests/ 日期归档。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

_DIGEST_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.(en|zh)\.md$")


@dataclass(frozen=True)
class DayFiles:
    day: date
    en: Path | None
    zh: Path | None


def list_digest_days(content_dir: Path) -> list[DayFiles]:
    """列出 content/digests 下所有归档日（新→旧）。"""
    if not content_dir.is_dir():
        return []
    by_day: dict[date, dict[str, Path]] = {}
    for path in sorted(content_dir.iterdir()):
        if not path.is_file():
            continue
        match = _DIGEST_NAME_RE.match(path.name)
        if not match:
            continue
        day = date.fromisoformat(match.group(1))
        by_day.setdefault(day, {})[match.group(2)] = path
    return [
        DayFiles(day=day, en=files.get("en"), zh=files.get("zh"))
        for day in sorted(by_day.keys(), reverse=True)
        for files in [by_day[day]]
    ]


def day_paths(content_dir: Path, day: date) -> DayFiles:
    """返回指定日的 en/zh 路径（文件可能尚不存在）。"""
    day_s = day.isoformat()
    en = content_dir / f"{day_s}.en.md"
    zh = content_dir / f"{day_s}.zh.md"
    return DayFiles(
        day=day,
        en=en if en.is_file() else None,
        zh=zh if zh.is_file() else None,
    )


@dataclass(frozen=True)
class DayWritePaths:
    day: date
    en: Path
    zh: Path


def day_write_paths(content_dir: Path, day: date) -> DayWritePaths:
    """返回指定日应写入的 en/zh 路径（不存在也会给出目标路径）。"""
    day_s = day.isoformat()
    return DayWritePaths(
        day=day,
        en=content_dir / f"{day_s}.en.md",
        zh=content_dir / f"{day_s}.zh.md",
    )
