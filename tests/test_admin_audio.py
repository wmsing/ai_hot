"""Admin 音频解析测试。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from src.admin.app import create_app
from src.admin.services.audio import resolve_item_audio, resolve_play_path
from src.models import PathsConfig


def test_resolve_item_audio_finds_content_mp3(tmp_path: Path) -> None:
    day = date(2026, 9, 12)
    mp3 = tmp_path / "audio" / "en" / day.isoformat() / "002.mp3"
    mp3.parent.mkdir(parents=True)
    mp3.write_bytes(b"ID3")

    paths = PathsConfig(
        content_audio_dir=str(tmp_path / "audio"),
        speak_audio_dir=str(tmp_path / "out_audio"),
    )
    audio = resolve_item_audio(paths, day=day, index=2)
    assert audio["en"].exists is True
    assert audio["en"].play_url == "/api/audio/2026-09-12/2/en"
    assert audio["zh"].exists is False


def test_resolve_play_path_prefers_content(tmp_path: Path) -> None:
    day = date(2026, 9, 12)
    content_mp3 = tmp_path / "audio" / "zh" / day.isoformat() / "001.mp3"
    out_mp3 = tmp_path / "out" / "zh" / day.isoformat() / "001.mp3"
    content_mp3.parent.mkdir(parents=True)
    out_mp3.parent.mkdir(parents=True)
    content_mp3.write_bytes(b"ID3-content")
    out_mp3.write_bytes(b"ID3-out")

    from src.config import load_app_config

    config = load_app_config()
    config.paths.content_audio_dir = str(tmp_path / "audio")
    config.paths.speak_audio_dir = str(tmp_path / "out")

    hit = resolve_play_path(config, day=day, index=1, lang="zh")
    assert hit == content_mp3


@pytest.fixture
def audio_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    day = date(2026, 9, 13)
    mp3 = tmp_path / "audio" / "en" / day.isoformat() / "001.mp3"
    mp3.parent.mkdir(parents=True)
    mp3.write_bytes(b"ID3")

    from src.config import load_app_config

    config = load_app_config()
    monkeypatch.setattr(config.paths, "content_audio_dir", str(tmp_path / "audio"))
    monkeypatch.setattr(config.paths, "speak_audio_dir", str(tmp_path / "out"))
    monkeypatch.setattr(config.paths, "content_digests_dir", str(tmp_path / "digests"))
    monkeypatch.setattr(config.paths, "hot_topics_path", str(tmp_path / "hot.json"))
    monkeypatch.setattr("src.admin.app.load_app_config", lambda: config)

    digests_dir = tmp_path / "digests"
    digests_dir.mkdir()
    day_s = day.isoformat()
    (digests_dir / f"{day_s}.en.md").write_text(
        f"""# ai_hot digest

Generated (UTC): 2026-09-13T10:00:00+00:00
Selected: 1

## 1. Audio sample

- source: `hn`
- url: https://example.com/audio
- summary: sample
""",
        encoding="utf-8",
    )
    (digests_dir / f"{day_s}.zh.md").write_text(
        f"""# ai_hot digest

Generated (UTC): 2026-09-13T10:00:00+00:00
Selected: 1

## 1. 音频样例

- source: `hn`
- url: https://example.com/audio
- summary: 样例
""",
        encoding="utf-8",
    )

    return TestClient(create_app())


def test_digest_includes_audio_fields(audio_client: TestClient) -> None:
    res = audio_client.get("/api/digests/2026-09-13")
    assert res.status_code == 200
    item = res.json()["items"][0]
    assert item["audio_en"]["exists"] is True
    assert item["audio_en"]["play_url"] == "/api/audio/2026-09-13/1/en"


def test_play_audio_endpoint(audio_client: TestClient) -> None:
    res = audio_client.get("/api/audio/2026-09-13/1/en")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("audio/mpeg")
