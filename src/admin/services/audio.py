"""Digest 条目关联 mp3 解析。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src.models import AppConfig, PathsConfig


@dataclass(frozen=True)
class AudioFileInfo:
    """一条口播 mp3 的磁盘位置与 Admin 播放 URL。"""

    content_path: str | None = None
    out_path: str | None = None
    play_url: str | None = None
    exists: bool = False


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


def resolve_item_audio(
    paths: PathsConfig,
    *,
    day: date,
    index: int,
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
        result[lang] = AudioFileInfo(
            content_path=str(content_hit) if content_hit else None,
            out_path=str(out_hit) if out_hit else None,
            play_url=play_url,
            exists=exists,
        )
    return result


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
