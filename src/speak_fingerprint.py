"""口播 mp3 指纹与 .meta.json sidecar。"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from src.models import AppConfig, DigestItem
from src.speak_script import SpeakLang, format_item_speak

logger = logging.getLogger(__name__)

AudioSyncStatus = Literal["ok", "stale", "missing"]


def speak_clip_text(item: DigestItem, *, lang: SpeakLang) -> str:
    return format_item_speak(item, lang=lang)


def speak_clip_fingerprint(text: str, *, voice: str, rate: str) -> str:
    payload = f"{text.strip()}\n{voice}\n{rate}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def mp3_meta_path(mp3_path: Path) -> Path:
    return mp3_path.with_name(f"{mp3_path.name}.meta.json")


def mp3_ready(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def read_mp3_meta(mp3_path: Path) -> dict[str, str] | None:
    meta_path = mp3_meta_path(mp3_path)
    if not meta_path.is_file():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return {str(k): str(v) for k, v in data.items()}


def write_mp3_meta(
    mp3_path: Path,
    *,
    hash_value: str,
    voice: str,
    rate: str,
) -> None:
    meta_path = mp3_meta_path(mp3_path)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "hash": hash_value,
        "voice": voice,
        "rate": rate,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    meta_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def delete_mp3_meta(mp3_path: Path) -> None:
    meta_path = mp3_meta_path(mp3_path)
    if meta_path.is_file():
        meta_path.unlink()


def _audio_base(path: Path) -> Path:
    if path.name in {"zh", "en"}:
        return path.parent
    return path


def archive_mp3_path(
    paths_content_audio: str | Path,
    *,
    lang: SpeakLang,
    day: date,
    index: int,
) -> Path:
    base = _audio_base(Path(paths_content_audio))
    return base / lang / day.isoformat() / f"{index:03d}.mp3"


def speak_voice_rate(config: AppConfig, lang: SpeakLang) -> tuple[str, str]:
    if lang == "en":
        return config.speak.voice_en, config.speak.rate
    return config.speak.voice, config.speak.rate


def clip_sync_status(
    item: DigestItem,
    *,
    lang: SpeakLang,
    mp3_path: Path,
    voice: str,
    rate: str,
) -> AudioSyncStatus:
    text = speak_clip_text(item, lang=lang)
    if not text.strip():
        return "missing"
    if not mp3_ready(mp3_path):
        return "missing"
    expected = speak_clip_fingerprint(text, voice=voice, rate=rate)
    meta = read_mp3_meta(mp3_path)
    if meta is None or meta.get("hash") != expected:
        return "stale"
    return "ok"


def needs_tts_regeneration(
    item: DigestItem,
    *,
    lang: SpeakLang,
    mp3_path: Path,
    voice: str,
    rate: str,
    force: bool,
) -> bool:
    if force:
        return True
    status = clip_sync_status(
        item,
        lang=lang,
        mp3_path=mp3_path,
        voice=voice,
        rate=rate,
    )
    return status in {"stale", "missing"}


def invalidate_archive_item_audio(
    content_audio_dir: str | Path,
    *,
    day: date,
    index: int,
) -> None:
    """正文变更后删除 meta（mp3 保留，UI 标 stale）。"""
    base = _audio_base(Path(content_audio_dir))
    day_s = day.isoformat()
    for lang in ("en", "zh"):
        mp3 = base / lang / day_s / f"{index:03d}.mp3"
        delete_mp3_meta(mp3)
