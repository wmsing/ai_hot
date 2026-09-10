"""旁路归档：out/digest*.md → content/digests/YYYY-MM-DD.{en,zh}.md。"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from src.config import load_app_config, settings

logger = logging.getLogger(__name__)


def archive_digests(
    *,
    digest_en: Path,
    digest_zh: Path | None,
    content_dir: Path,
    day: date | None = None,
) -> list[Path]:
    """覆盖写入当日英/中归档文件；缺源文件则跳过该语言。"""
    target_day = day or datetime.now(timezone.utc).date()
    content_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    en_dst = content_dir / f"{target_day.isoformat()}.en.md"
    if not digest_en.is_file():
        raise FileNotFoundError(f"digest not found: {digest_en}")
    en_dst.write_text(digest_en.read_text(encoding="utf-8"), encoding="utf-8")
    written.append(en_dst)

    if digest_zh is not None:
        zh_dst = content_dir / f"{target_day.isoformat()}.zh.md"
        if digest_zh.is_file():
            zh_dst.write_text(digest_zh.read_text(encoding="utf-8"), encoding="utf-8")
            written.append(zh_dst)
        else:
            logger.warning("zh digest missing, skip: %s", digest_zh)

    return written


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Archive out/digest*.md into content/digests/ (UTC day)."
    )
    parser.add_argument(
        "--day",
        default=None,
        help="UTC day YYYY-MM-DD (default: today UTC)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_app_config()
    day: date | None = None
    if args.day:
        day = date.fromisoformat(args.day)

    written = archive_digests(
        digest_en=Path(config.paths.digest_path),
        digest_zh=Path(config.paths.digest_zh_path),
        content_dir=Path(config.paths.content_digests_dir),
        day=day,
    )
    for path in written:
        print(f"[ai_hot] archived {path}")
    print(
        "[ai_hot] next: git add content/digests && git commit && git push "
        "(Actions → Cloudflare Pages)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
