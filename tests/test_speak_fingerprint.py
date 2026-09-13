"""口播指纹与归档 TTS 单测。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.models import AppConfig, DigestItem, PathsConfig
from src.speak import run_speak_archive
from src.speak_fingerprint import (
    clip_sync_status,
    speak_clip_fingerprint,
    speak_clip_text,
    write_mp3_meta,
)


def test_speak_clip_fingerprint_changes_with_title() -> None:
    item_a = DigestItem(index=1, title="A", url="https://x", source="hn", summary="one")
    item_b = DigestItem(index=1, title="B", url="https://x", source="hn", summary="one")
    voice, rate = "zh-CN-XiaoxiaoNeural", "+0%"
    hash_a = speak_clip_fingerprint(
        speak_clip_text(item_a, lang="zh"), voice=voice, rate=rate
    )
    hash_b = speak_clip_fingerprint(
        speak_clip_text(item_b, lang="zh"), voice=voice, rate=rate
    )
    assert hash_a != hash_b


def test_clip_sync_status_ok_with_meta(tmp_path: Path) -> None:
    item = DigestItem(index=1, title="标题", url="https://x", source="hn", summary="摘要")
    voice, rate = "zh-CN-XiaoxiaoNeural", "+0%"
    mp3 = tmp_path / "001.mp3"
    mp3.write_bytes(b"ID3")
    text = speak_clip_text(item, lang="zh")
    write_mp3_meta(
        mp3,
        hash_value=speak_clip_fingerprint(text, voice=voice, rate=rate),
        voice=voice,
        rate=rate,
    )
    assert (
        clip_sync_status(item, lang="zh", mp3_path=mp3, voice=voice, rate=rate) == "ok"
    )


def test_clip_sync_status_stale_when_title_changes(tmp_path: Path) -> None:
    item = DigestItem(index=1, title="旧标题", url="https://x", source="hn", summary="摘要")
    voice, rate = "zh-CN-XiaoxiaoNeural", "+0%"
    mp3 = tmp_path / "001.mp3"
    mp3.write_bytes(b"ID3")
    text = speak_clip_text(item, lang="zh")
    write_mp3_meta(
        mp3,
        hash_value=speak_clip_fingerprint(text, voice=voice, rate=rate),
        voice=voice,
        rate=rate,
    )
    item_new = item.model_copy(update={"title": "新标题"})
    assert (
        clip_sync_status(item_new, lang="zh", mp3_path=mp3, voice=voice, rate=rate)
        == "stale"
    )


def test_run_speak_archive_generates_and_skips_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    day = date(2026, 9, 13)
    digests = tmp_path / "digests"
    digests.mkdir()
    digest = digests / f"{day.isoformat()}.zh.md"
    digest.write_text(
        f"""# ai_hot digest

Generated (UTC): 2026-09-13T10:00:00+00:00
Selected: 1

## 1. 样例

- source: `hn`
- url: https://example.com/1
- summary: 摘要
""",
        encoding="utf-8",
    )
    cfg = AppConfig(
        paths=PathsConfig(
            content_digests_dir=str(digests),
            content_audio_dir=str(tmp_path / "audio"),
        )
    )
    calls: list[str] = []

    from src.speak_fingerprint import speak_voice_rate

    voice, rate = speak_voice_rate(cfg, "zh")

    def _fake_synthesize(text: str, path: Path, **_kwargs: object) -> None:
        calls.append(path.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"NEW")
        write_mp3_meta(
            path,
            hash_value=speak_clip_fingerprint(text, voice=voice, rate=rate),
            voice=voice,
            rate=rate,
        )

    monkeypatch.setattr("src.speak.synthesize", _fake_synthesize)
    first = run_speak_archive(cfg, day=day, lang="zh")
    second = run_speak_archive(cfg, day=day, lang="zh")

    assert first["generated"] == 1
    assert second["generated"] == 0
    assert calls == ["001.mp3"]
    meta = tmp_path / "audio" / "zh" / day.isoformat() / "001.mp3.meta.json"
    assert meta.is_file()
