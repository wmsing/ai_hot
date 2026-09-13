"""Digest 条目关联 mp3 解析。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from src.models import AppConfig, DigestItem, PathsConfig
from src.speak_fingerprint import (
    archive_mp3_path,
    clip_sync_status,
    mp3_ready,
    speak_voice_rate,
)
from src.speak_script import SpeakLang

AudioSyncStatus = Literal["ok", "stale", "missing"]


@dataclass(frozen=True)
class AudioFileInfo:
    """一条口播 mp3 的磁盘位置与 Admin 播放 URL。"""

    content_path: str | None = None
    out_path: str | None = None
    play_url: str | None = None
    exists: bool = False
    sync_status: AudioSyncStatus = "missing"


def _audio_base(path: Path) -> Path:
    if path.name in {"zh", "en"}:
        return path.parent
    return path


def _mp3_candidates(
    roots: list[Path],
    *,
    lang: str,
    day: date,
    index: int,
) -> list[Path]:
    day_s = day.isoformat()
    name = f"{index:03d}.mp3"
    out: list[Path] = []
    for root in roots:
        base = _audio_base(root)
        out.append(base / lang / day_s / name)
    return out


def _digest_item_for_lang(
    item_en: DigestItem | None,
    item_zh: DigestItem | None,
    *,
    lang: SpeakLang,
) -> DigestItem:
    if lang == "en" and item_en is not None:
        return item_en
    if lang == "zh" and item_zh is not None:
        return item_zh
    return item_en or item_zh or DigestItem(index=0, title="", url="", source="")


def resolve_item_audio(
    paths: PathsConfig,
    *,
    day: date,
    index: int,
    item_en: DigestItem | None = None,
    item_zh: DigestItem | None = None,
    voice_en: str | None = None,
    rate: str | None = None,
    voice_zh: str | None = None,
) -> dict[str, AudioFileInfo]:
    """查找 content/out 两侧 mp3，并生成 Admin 播放 URL。"""
    content_roots = [_audio_base(Path(paths.content_audio_dir))]
    out_roots = [_audio_base(Path(paths.speak_audio_dir))]
    result: dict[str, AudioFileInfo] = {}
    for lang in ("en", "zh"):
        content_hit = _first_existing(
            _mp3_candidates(content_roots, lang=lang, day=day, index=index)
        )
        out_hit = _first_existing(
            _mp3_candidates(out_roots, lang=lang, day=day, index=index)
        )
        exists = content_hit is not None or out_hit is not None
        play_url = f"/api/audio/{day.isoformat()}/{index}/{lang}" if exists else None
        sync_status: AudioSyncStatus = "missing"
        if item_en is not None or item_zh is not None:
            digest_item = _digest_item_for_lang(item_en, item_zh, lang=lang)
            mp3_path = archive_mp3_path(
                paths.content_audio_dir,
                lang=lang,
                day=day,
                index=index,
            )
            if content_hit is not None:
                mp3_path = content_hit
            elif out_hit is not None:
                mp3_path = out_hit
            voice = voice_en if lang == "en" else voice_zh
            rate_val = rate or "+0%"
            if voice:
                sync_status = clip_sync_status(
                    digest_item,
                    lang=lang,
                    mp3_path=mp3_path,
                    voice=voice,
                    rate=rate_val,
                )
            elif not exists:
                sync_status = "missing"
            elif not mp3_ready(mp3_path):
                sync_status = "missing"
            else:
                sync_status = "stale"
        result[lang] = AudioFileInfo(
            content_path=str(content_hit) if content_hit else None,
            out_path=str(out_hit) if out_hit else None,
            play_url=play_url,
            exists=exists,
            sync_status=sync_status,
        )
    return result


def resolve_day_audio_status(
    config: AppConfig,
    *,
    day: date,
    items: Sequence[object],
) -> dict[str, object]:
    """汇总当日 mp3 同步状态。"""
    from src.admin.stores.digest import MergedDigestItem
    from src.models import DigestItem

    voice_en, rate = speak_voice_rate(config, "en")
    voice_zh, _ = speak_voice_rate(config, "zh")
    rows: list[dict[str, Any]] = []
    stale_count = 0
    missing_count = 0
    for raw in items:
        if isinstance(raw, MergedDigestItem):
            index = raw.index
            en_item = DigestItem(
                index=index,
                title=raw.title_en,
                url=raw.url,
                source=raw.source,
                summary=raw.summary_en,
                speak_summary=raw.speak_en,
            )
            zh_item = DigestItem(
                index=index,
                title=raw.title_zh,
                url=raw.url,
                source=raw.source,
                summary=raw.summary_zh,
                speak_summary=raw.speak_zh,
            )
        elif isinstance(raw, DigestItem):
            index = raw.index
            en_item = raw
            zh_item = raw
        else:
            continue
        audio = resolve_item_audio(
            config.paths,
            day=day,
            index=index,
            item_en=en_item,
            item_zh=zh_item,
            voice_en=voice_en,
            voice_zh=voice_zh,
            rate=rate,
        )
        row = {
            "index": index,
            "en": audio["en"].sync_status,
            "zh": audio["zh"].sync_status,
        }
        rows.append(row)
        for lang in ("en", "zh"):
            status = audio[lang].sync_status
            if status == "stale":
                stale_count += 1
            elif status == "missing":
                missing_count += 1
    return {
        "day": day.isoformat(),
        "stale_count": stale_count,
        "missing_count": missing_count,
        "items": rows,
    }


def resolve_play_path(
    config: AppConfig,
    *,
    day: date,
    index: int,
    lang: str,
) -> Path | None:
    """返回可流式播放的 mp3 路径（content 优先，其次 out）。"""
    paths = config.paths
    content_roots = [_audio_base(Path(paths.content_audio_dir))]
    out_roots = [_audio_base(Path(paths.speak_audio_dir))]
    content_hit = _first_existing(
        _mp3_candidates(content_roots, lang=lang, day=day, index=index)
    )
    if content_hit is not None:
        return content_hit
    return _first_existing(_mp3_candidates(out_roots, lang=lang, day=day, index=index))


def _first_existing(candidates: list[Path]) -> Path | None:
    for path in candidates:
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None
