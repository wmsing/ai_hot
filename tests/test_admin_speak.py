"""Admin digest speak API 测试。"""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from src.admin.app import create_app
from src.speak_fingerprint import speak_clip_fingerprint, speak_clip_text, write_mp3_meta
from src.config import load_app_config
from src.models import DigestItem
from src.speak_fingerprint import speak_voice_rate


@pytest.fixture
def speak_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    day = date(2026, 9, 14)
    digests = tmp_path / "digests"
    audio = tmp_path / "audio"
    digests.mkdir()
    day_s = day.isoformat()
    (digests / f"{day_s}.en.md").write_text(
        f"""# ai_hot digest

Generated (UTC): 2026-09-14T10:00:00+00:00
Selected: 1

## 1. Sample

- source: `hn`
- url: https://example.com/speak
- summary: hello
""",
        encoding="utf-8",
    )
    (digests / f"{day_s}.zh.md").write_text(
        f"""# ai_hot digest

Generated (UTC): 2026-09-14T10:00:00+00:00
Selected: 1

## 1. 样例

- source: `hn`
- url: https://example.com/speak
- summary: 你好
""",
        encoding="utf-8",
    )
    mp3 = audio / "en" / day_s / "001.mp3"
    mp3.parent.mkdir(parents=True)
    mp3.write_bytes(b"OLD")
    item = DigestItem(
        index=1,
        title="Sample",
        url="https://example.com/speak",
        source="hn",
        summary="hello",
    )
    config = load_app_config()
    voice, rate = speak_voice_rate(config, "en")
    write_mp3_meta(
        mp3,
        hash_value=speak_clip_fingerprint(
            speak_clip_text(item, lang="en"), voice=voice, rate=rate
        ),
        voice=voice,
        rate=rate,
    )

    monkeypatch.setattr(config.paths, "content_digests_dir", str(digests))
    monkeypatch.setattr(config.paths, "content_audio_dir", str(audio))
    monkeypatch.setattr(config.paths, "speak_audio_dir", str(tmp_path / "out_audio"))
    monkeypatch.setattr(config.paths, "hot_topics_path", str(tmp_path / "hot.json"))
    monkeypatch.setattr("src.admin.app.load_app_config", lambda: config)
    monkeypatch.setattr(
        "src.speak.synthesize",
        lambda text, path, **_kw: path.write_bytes(b"NEW"),
    )

    return TestClient(create_app())


def test_digest_includes_sync_status(speak_client: TestClient) -> None:
    res = speak_client.get("/api/digests/2026-09-14")
    assert res.status_code == 200
    item = res.json()["items"][0]
    assert item["audio_en"]["sync_status"] == "ok"
    assert item["audio_zh"]["sync_status"] == "missing"


def test_audio_status_counts(speak_client: TestClient) -> None:
    res = speak_client.get("/api/digests/2026-09-14/audio-status")
    assert res.status_code == 200
    body = res.json()
    assert body["missing_count"] == 1
    assert body["stale_count"] == 0


def _wait_job(client: TestClient, job_id: str) -> dict[str, object]:
    deadline = time.time() + 3.0
    while time.time() < deadline:
        res = client.get(f"/api/jobs/{job_id}")
        body = res.json()
        if body["status"] in {"done", "error", "cancelled"}:
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish")


def test_digest_speak_job(speak_client: TestClient) -> None:
    res = speak_client.post(
        "/api/digests/2026-09-14/items/speak",
        json={"indices": [1], "force": True, "langs": ["zh"]},
    )
    assert res.status_code == 200
    job = _wait_job(speak_client, res.json()["id"])
    assert job["status"] == "done"
    assert job["result"]["generated"] >= 1
