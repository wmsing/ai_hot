"""从 digest.zh.md 生成口播稿 + TTS mp3 播放列表。"""

from __future__ import annotations

import argparse
import logging
import re
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from src.config import load_app_config, settings
from src.models import AppConfig, DigestDocument
from src.site_parse import parse_digest_markdown
from src.speak_script import format_item_speak, format_speak_document
from src.speak_tts import synthesize

logger = logging.getLogger(__name__)
_ITEM_MP3_RE = re.compile(r"^(\d{3})\.mp3$")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build speak script + TTS playlist from digest.zh.md"
    )
    parser.add_argument(
        "--input",
        default=None,
        help="Digest markdown path (default: paths.digest_zh_path)",
    )
    parser.add_argument(
        "--script-only",
        action="store_true",
        help="Write speak.zh.md only; skip TTS",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only first N items (debug)",
    )
    parser.add_argument(
        "--voice",
        default=None,
        help="edge-tts voice id (default: speak.voice)",
    )
    parser.add_argument(
        "--rate",
        default=None,
        help='Speech rate, e.g. "+0%%" or "+10%%" (default: speak.rate)',
    )
    return parser.parse_args(argv)


def _audio_day(doc: DigestDocument) -> date:
    """用 generated_at 的 UTC 日作为音频子目录名。"""
    raw = doc.generated_at.strip()
    if raw:
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).date()
        except ValueError:
            pass
    return datetime.now(timezone.utc).date()


def run_speak(
    config: AppConfig,
    *,
    input_path: str | Path | None = None,
    script_only: bool = False,
    limit: int | None = None,
    voice: str | None = None,
    rate: str | None = None,
) -> tuple[Path, Path | None]:
    """写口播稿；非 script_only 时再写逐条 mp3 + full.mp3 + playlist.m3u。"""
    src = Path(input_path or config.paths.digest_zh_path)
    if not src.is_file():
        raise FileNotFoundError(f"digest not found: {src}")
    text = src.read_text(encoding="utf-8")
    doc = parse_digest_markdown(text)
    if limit is not None:
        if limit < 0:
            raise ValueError("--limit must be >= 0")
        doc = DigestDocument(
            title=doc.title,
            generated_at=doc.generated_at,
            selected=min(limit, len(doc.items)),
            items=doc.items[:limit],
        )

    speak_path = Path(config.paths.speak_zh_path)
    speak_path.parent.mkdir(parents=True, exist_ok=True)
    script = format_speak_document(doc)
    speak_path.write_text(script, encoding="utf-8")
    logger.info("wrote script %s (%d items)", speak_path, len(doc.items))

    if script_only:
        return speak_path, None

    voice_id = voice or config.speak.voice
    rate_val = rate or config.speak.rate
    day_s = _audio_day(doc).isoformat()
    audio_dir = Path(config.paths.speak_audio_dir) / day_s
    audio_dir.mkdir(parents=True, exist_ok=True)

    item_paths: list[Path] = []
    intro = f"今日 AI 热点共 {len(doc.items)} 条。"
    intro_path = audio_dir / "000_intro.mp3"
    synthesize(intro, intro_path, voice=voice_id, rate=rate_val)
    item_paths.append(intro_path)

    for item in doc.items:
        clip = format_item_speak(item)
        out = audio_dir / f"{item.index:03d}.mp3"
        synthesize(clip, out, voice=voice_id, rate=rate_val)
        item_paths.append(out)
        logger.info("tts item %d → %s", item.index, out)

    full_path = audio_dir / "full.mp3"
    synthesize(script, full_path, voice=voice_id, rate=rate_val)
    logger.info("wrote full %s", full_path)

    playlist_path = audio_dir / "playlist.m3u"
    _write_playlist(playlist_path, item_paths)
    logger.info("wrote playlist %s", playlist_path)

    # 站点部署用：只同步条目 mp3 到 content/audio（可进 git）
    content_day = Path(config.paths.content_audio_dir) / day_s
    content_day.mkdir(parents=True, exist_ok=True)
    for path in item_paths:
        if not _ITEM_MP3_RE.match(path.name):
            continue
        if int(path.stem) <= 0:
            continue
        shutil.copy2(path, content_day / path.name)
    logger.info("synced site audio → %s", content_day)

    return speak_path, audio_dir


def _write_playlist(path: Path, clips: list[Path]) -> None:
    """相对路径 m3u，便于本地播放器顺序播。"""
    lines = ["#EXTM3U"]
    for clip in clips:
        lines.append(clip.name)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_app_config()
    speak_path, audio_dir = run_speak(
        config,
        input_path=args.input,
        script_only=args.script_only,
        limit=args.limit,
        voice=args.voice,
        rate=args.rate,
    )
    if audio_dir is None:
        print(f"[ai_hot] speak script → {speak_path} (script-only)")
    else:
        print(
            f"[ai_hot] speak script → {speak_path}; "
            f"audio playlist → {audio_dir / 'playlist.m3u'}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
