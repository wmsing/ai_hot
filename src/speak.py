"""从 digest(.zh).md 生成口播稿 + TTS mp3 播放列表。"""

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
from src.speak_script import SpeakLang, format_item_speak, format_speak_document
from src.speak_tts import synthesize

logger = logging.getLogger(__name__)
_ITEM_MP3_RE = re.compile(r"^(\d{3})\.mp3$")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build speak script + TTS playlist from digest markdown"
    )
    parser.add_argument(
        "--lang",
        choices=("zh", "en"),
        default=None,
        help="Only zh or en; default: generate both",
    )
    parser.add_argument(
        "--input",
        default=None,
        help="Digest markdown path (default: digest_zh_path / digest_path)",
    )
    parser.add_argument(
        "--script-only",
        action="store_true",
        help="Write speak script only; skip TTS",
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
        help="edge-tts voice id (default: speak.voice / speak.voice_en)",
    )
    parser.add_argument(
        "--rate",
        default=None,
        help='Speech rate, e.g. "+0%%" or "+10%%" (default: speak.rate)',
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate all mp3 even if files already exist",
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="Only (re)generate TTS for digest items with this URL (repeatable)",
    )
    return parser.parse_args(argv)


def _normalize_url(url: str) -> str:
    text = url.strip()
    if len(text) > 8 and text.endswith("/"):
        text = text.rstrip("/")
    return text


def _url_filter_set(urls: list[str] | None) -> set[str] | None:
    if not urls:
        return None
    keys = {_normalize_url(u) for u in urls if u.strip()}
    return keys or None


def _item_tts_force(*, force: bool, url_keys: set[str] | None, item_url: str) -> bool:
    if force:
        return True
    if url_keys is None:
        return False
    return _normalize_url(item_url) in url_keys


def speak_langs(args: argparse.Namespace) -> list[SpeakLang]:
    """默认中英各生成一份；--lang 指定时只跑该语言。"""
    if args.lang is None:
        return ["en", "zh"]
    return [args.lang]


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


def _audio_base(path: Path) -> Path:
    """兼容旧配置 …/audio/zh → 根目录 …/audio。"""
    if path.name in {"zh", "en"}:
        return path.parent
    return path


def _mp3_ready(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _ensure_mp3(
    *,
    text: str,
    out_path: Path,
    content_path: Path | None,
    voice: str,
    rate: str,
    force: bool,
    label: str,
) -> bool:
    """保证 out_path 有可用 mp3。返回是否新合成。

    优先复用 out；否则复用 content（并拷到 out）；否则 TTS。
    """
    if not force and _mp3_ready(out_path):
        logger.info("skip existing %s (%s)", label, out_path)
        return False
    if (
        not force
        and content_path is not None
        and _mp3_ready(content_path)
    ):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(content_path, out_path)
        logger.info("reuse content %s → %s", label, out_path)
        return False
    synthesize(text, out_path, voice=voice, rate=rate)
    logger.info("tts %s → %s", label, out_path)
    return True


def run_speak(
    config: AppConfig,
    *,
    lang: SpeakLang = "zh",
    input_path: str | Path | None = None,
    script_only: bool = False,
    limit: int | None = None,
    voice: str | None = None,
    rate: str | None = None,
    force: bool = False,
    urls: list[str] | None = None,
) -> tuple[Path, Path | None]:
    """写口播稿；非 script_only 时再写逐条 mp3 + full.mp3 + playlist.m3u。

    默认跳过已有非空 mp3（out 或 content），只补缺；--force 全量重生成；
    urls 非空时只强制重生成匹配 URL 的条目（序号 = digest 里 ## N.）。
    """
    url_keys = _url_filter_set(urls)
    if input_path is not None:
        src = Path(input_path)
    elif lang == "en":
        src = Path(config.paths.digest_path)
    else:
        src = Path(config.paths.digest_zh_path)
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

    speak_path = Path(
        config.paths.speak_en_path if lang == "en" else config.paths.speak_zh_path
    )
    speak_path.parent.mkdir(parents=True, exist_ok=True)
    script = format_speak_document(doc, lang=lang)
    speak_path.write_text(script, encoding="utf-8")
    logger.info("wrote script %s (%d items)", speak_path, len(doc.items))

    if script_only:
        return speak_path, None

    if voice:
        voice_id = voice
    elif lang == "en":
        voice_id = config.speak.voice_en
    else:
        voice_id = config.speak.voice
    rate_val = rate or config.speak.rate
    day_s = _audio_day(doc).isoformat()
    audio_dir = _audio_base(Path(config.paths.speak_audio_dir)) / lang / day_s
    audio_dir.mkdir(parents=True, exist_ok=True)
    content_day = _audio_base(Path(config.paths.content_audio_dir)) / lang / day_s
    content_day.mkdir(parents=True, exist_ok=True)

    item_paths: list[Path] = []
    made_new = 0
    intro = (
        f"Today's AI highlights: {len(doc.items)} items."
        if lang == "en"
        else f"今日 AI 热点共 {len(doc.items)} 条。"
    )
    intro_path = audio_dir / "000_intro.mp3"
    if _ensure_mp3(
        text=intro,
        out_path=intro_path,
        content_path=None,
        voice=voice_id,
        rate=rate_val,
        force=force,
        label="intro",
    ):
        made_new += 1
    item_paths.append(intro_path)

    for item in doc.items:
        clip = format_item_speak(item, lang=lang)
        name = f"{item.index:03d}.mp3"
        out = audio_dir / name
        item_force = _item_tts_force(
            force=force, url_keys=url_keys, item_url=item.url
        )
        if _ensure_mp3(
            text=clip,
            out_path=out,
            content_path=content_day / name,
            voice=voice_id,
            rate=rate_val,
            force=item_force,
            label=f"item {item.index}",
        ):
            made_new += 1
        item_paths.append(out)

    full_path = audio_dir / "full.mp3"
    # full 是整稿 TTS：缺文件或本轮有新 clip 时重生成，避免旧 full 缺新条
    force_full = force or made_new > 0 or not _mp3_ready(full_path)
    if force_full:
        synthesize(script, full_path, voice=voice_id, rate=rate_val)
        logger.info("wrote full %s", full_path)
    else:
        logger.info("skip existing full %s", full_path)

    playlist_path = audio_dir / "playlist.m3u"
    _write_playlist(playlist_path, item_paths)
    logger.info("wrote playlist %s", playlist_path)

    for path in item_paths:
        if not _ITEM_MP3_RE.match(path.name):
            continue
        if int(path.stem) <= 0:
            continue
        dest = content_day / path.name
        if (
            force
            or not _mp3_ready(dest)
            or path.stat().st_mtime > dest.stat().st_mtime
        ):
            shutil.copy2(path, dest)
    logger.info(
        "synced site audio → %s (new_tts=%s force=%s url_filter=%s)",
        content_day,
        made_new,
        force,
        bool(url_keys),
    )

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
    langs = speak_langs(args)
    last_speak: Path | None = None
    for lang in langs:
        speak_path, audio_dir = run_speak(
            config,
            lang=lang,
            input_path=args.input,
            script_only=args.script_only,
            limit=args.limit,
            voice=args.voice,
            rate=args.rate,
            force=args.force,
            urls=args.url or None,
        )
        last_speak = speak_path
        if audio_dir is None:
            print(f"[ai_hot] speak script → {speak_path} (script-only lang={lang})")
        else:
            print(
                f"[ai_hot] speak script → {speak_path}; "
                f"audio playlist → {audio_dir / 'playlist.m3u'} (lang={lang})"
            )
    if len(langs) > 1 and last_speak is not None:
        print(f"[ai_hot] speak done langs={','.join(langs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
