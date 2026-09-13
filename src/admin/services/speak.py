"""Digest 归档口播 TTS 服务。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from src.admin.stores import digest as digest_store
from src.models import AppConfig
from src.speak import run_speak_archive
from src.speak_fingerprint import invalidate_archive_item_audio
from src.speak_script import SpeakLang


def invalidate_digest_audio(
    config: AppConfig,
    *,
    day: date,
    indices: list[int],
) -> None:
    for index in indices:
        if index <= 0:
            continue
        invalidate_archive_item_audio(
            config.paths.content_audio_dir,
            day=day,
            index=index,
        )


def run_digest_speak(
    config: AppConfig,
    *,
    day: date,
    indices: list[int] | None = None,
    urls: list[str] | None = None,
    langs: list[SpeakLang] | None = None,
    force: bool = False,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, object]:
    """对归档 digest 生成 mp3；langs 默认 en+zh。"""
    run_langs: list[SpeakLang] = langs if langs else ["en", "zh"]
    total_generated = 0
    total_skipped = 0
    per_lang: dict[str, dict[str, object]] = {}
    for lang in run_langs:
        if should_stop and should_stop():
            break
        result = run_speak_archive(
            config,
            day=day,
            lang=lang,
            indices=indices,
            urls=urls,
            force=force,
        )
        per_lang[lang] = result
        total_generated += int(str(result["generated"]))
        total_skipped += int(str(result["skipped"]))
    return {
        "day": day.isoformat(),
        "generated": total_generated,
        "skipped": total_skipped,
        "langs": per_lang,
        "indices": indices,
        "urls": urls or [],
    }


def digest_audio_status(
    config: AppConfig,
    *,
    day: date,
) -> dict[str, object]:
    """汇总当日各条 mp3 同步状态（ok / stale / missing）。"""
    from src.admin.services.audio import resolve_day_audio_status

    view = digest_store.get_day(Path(config.paths.content_digests_dir), day)
    return resolve_day_audio_status(config, day=day, items=list(view.items))
