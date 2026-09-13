"""Admin API 路由测试。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from src.admin.app import create_app
from src.admin.stores import hot_topics as hot_topics_store
from src.models import HotTopicSnapshotItem


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    hot_path = tmp_path / "hot_topics" / "latest.json"
    digests_dir = tmp_path / "digests"
    digests_dir.mkdir(parents=True)
    day = date(2026, 9, 13)
    day_s = day.isoformat()
    (digests_dir / f"{day_s}.en.md").write_text(
        f"""# ai_hot digest

Generated (UTC): 2026-09-13T10:00:00+00:00
Selected: 1

## 1. API sample

- source: `manual`
- url: https://example.com/api
- summary: en summary
""",
        encoding="utf-8",
    )
    (digests_dir / f"{day_s}.zh.md").write_text(
        f"""# ai_hot digest

Generated (UTC): 2026-09-13T10:00:00+00:00
Selected: 1

## 1. API 样例

- source: `manual`
- url: https://example.com/api
- summary: 中文摘要
""",
        encoding="utf-8",
    )

    hot_topics_store.add_item(
        hot_path,
        HotTopicSnapshotItem(
            heat=2.0,
            source="manual",
            title="Hot API",
            url="https://example.com/hot",
            reason="test",
        ),
    )

    from src.config import load_app_config

    config = load_app_config()
    monkeypatch.setattr(config.paths, "hot_topics_path", str(hot_path))
    monkeypatch.setattr(config.paths, "content_digests_dir", str(digests_dir))
    monkeypatch.setattr(
        "src.admin.app.load_app_config",
        lambda: config,
    )

    app = create_app()
    return TestClient(app)


def test_meta(client: TestClient) -> None:
    res = client.get("/api/meta")
    assert res.status_code == 200
    data = res.json()
    assert "hot_topics_path" in data
    assert data["hot_topics_llm_busy"] is False


def test_hot_topics_list(client: TestClient) -> None:
    res = client.get("/api/hot-topics")
    assert res.status_code == 200
    data = res.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["title"] == "Hot API"


def test_hot_topics_update(client: TestClient) -> None:
    res = client.put(
        "/api/hot-topics/items",
        json={"url": "https://example.com/hot", "title_zh": "热搜"},
    )
    assert res.status_code == 200
    assert res.json()["items"][0]["title_zh"] == "热搜"


def test_digest_days_and_get(client: TestClient) -> None:
    res = client.get("/api/digests/days")
    assert res.status_code == 200
    days = res.json()
    assert "2026-09-13" in days

    res = client.get("/api/digests/2026-09-13")
    assert res.status_code == 200
    data = res.json()
    assert data["items"][0]["title_en"] == "API sample"


def test_digest_update(client: TestClient) -> None:
    res = client.put(
        "/api/digests/2026-09-13/items/1",
        json={"summary_zh": "更新摘要"},
    )
    assert res.status_code == 200
    assert res.json()["summary_zh"] == "更新摘要"


def test_index_html(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "AI Hot Admin" in res.text


def test_publish_status(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.admin.app.publish_status",
        lambda: {"repo_root": "/tmp", "pending": [], "has_changes": False},
    )
    res = client.get("/api/publish/status")
    assert res.status_code == 200
    assert res.json()["has_changes"] is False


def test_hot_topics_adhd_all_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_adhd(**kwargs: object) -> dict[str, object]:
        return {"path": "x", "changed": 3}

    monkeypatch.setattr(
        "src.admin.app.generate_all_hot_topic_adhd",
        lambda *args, **kwargs: _fake_adhd(),
    )
    res = client.post("/api/hot-topics/items/adhd-all", json={"lang": "zh"})
    assert res.status_code == 200
    job_id = res.json()["id"]
    import time

    for _ in range(20):
        status = client.get(f"/api/jobs/{job_id}").json()
        if status["status"] in {"done", "error"}:
            break
        time.sleep(0.05)
    assert status["status"] == "done"
    assert status["result"]["changed"] == 3


def test_cancel_running_job(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import threading
    import time

    gate = threading.Event()

    def _slow_adhd(**kwargs: object) -> dict[str, object]:
        gate.wait(timeout=2.0)
        return {"path": "x", "changed": 0}

    monkeypatch.setattr(
        "src.admin.app.generate_all_hot_topic_adhd",
        lambda *args, **kwargs: _slow_adhd(),
    )
    res = client.post("/api/hot-topics/items/adhd-all", json={"lang": "zh"})
    job_id = res.json()["id"]
    deadline = time.time() + 2.0
    while time.time() < deadline:
        status = client.get(f"/api/jobs/{job_id}").json()
        if status["status"] == "running":
            break
        time.sleep(0.02)
    cancel = client.post(f"/api/jobs/{job_id}/cancel")
    assert cancel.status_code == 200
    gate.set()
    deadline = time.time() + 2.0
    while time.time() < deadline:
        status = client.get(f"/api/jobs/{job_id}").json()
        if status["status"] == "cancelled":
            break
        time.sleep(0.02)
    assert status["status"] == "cancelled"


def test_hot_topics_translate_titles_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_translate(**kwargs: object) -> dict[str, object]:
        return {"path": "x", "changed": 1}

    monkeypatch.setattr(
        "src.admin.app.translate_all_hot_topic_titles",
        lambda *args, **kwargs: _fake_translate(),
    )
    res = client.post("/api/hot-topics/translate-titles", json={})
    assert res.status_code == 200
    job_id = res.json()["id"]
    import time

    for _ in range(20):
        status = client.get(f"/api/jobs/{job_id}").json()
        if status["status"] in {"done", "error"}:
            break
        time.sleep(0.05)
    assert status["status"] == "done"
    assert status["result"]["changed"] == 1
