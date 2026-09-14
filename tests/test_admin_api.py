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


def test_admin_spa_routes(client: TestClient) -> None:
    root = client.get("/", follow_redirects=False)
    assert root.status_code == 307
    assert root.headers["location"].rstrip("/") == "/digest"

    for path in ("/digest/", "/digest", "/digest/2026-09-13", "/recent"):
        res = client.get(path)
        assert res.status_code == 200
        assert "AI Hot Admin" in res.text


def test_meta(client: TestClient) -> None:
    res = client.get("/api/meta")
    assert res.status_code == 200
    data = res.json()
    assert "hot_topics_path" in data
    assert "hot_page_enabled" in data
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
    assert data["items"][0]["archive_day"] == "2026-09-13"


def test_digest_timeline_days_and_get(client: TestClient) -> None:
    res = client.get("/api/digest-timeline/days")
    assert res.status_code == 200
    assert isinstance(res.json(), list)

    res = client.get("/api/digest-timeline/2026-09-13")
    assert res.status_code == 200
    data = res.json()
    assert data["published_day"] == "2026-09-13"
    assert isinstance(data["items"], list)


def test_digest_recent(client: TestClient) -> None:
    res = client.get("/api/digest-recent?limit=5")
    assert res.status_code == 200
    data = res.json()
    assert data["limit"] == 5
    assert isinstance(data["published_days"], list)
    assert isinstance(data["items"], list)
    if data["items"]:
        assert "published_day" in data["items"][0]
        assert "archive_day" in data["items"][0]


def test_digest_flags_hot_topic_match(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.config import load_app_config

    hot_path = tmp_path / "hot_topics" / "latest.json"
    digests_dir = tmp_path / "digests"
    day = date(2026, 9, 13)
    day_s = day.isoformat()
    shared_url = "https://example.com/nvidia"
    (digests_dir / f"{day_s}.en.md").write_text(
        f"""# ai_hot digest

Generated (UTC): 2026-09-13T10:00:00+00:00
Selected: 1

## 2. Nvidia is the central bank of AI

- source: `hn`
- url: {shared_url}
- summary: plain probe summary
""",
        encoding="utf-8",
    )
    (digests_dir / f"{day_s}.zh.md").write_text(
        f"""# ai_hot digest

Generated (UTC): 2026-09-13T10:00:00+00:00
Selected: 1

## 2. 英伟达是人工智能的央行

- source: `hn`
- url: {shared_url}
- summary: 普通摘要
""",
        encoding="utf-8",
    )
    hot_topics_store.add_item(
        hot_path,
        HotTopicSnapshotItem(
            heat=9.5,
            source="google_news:ai",
            title="Nvidia is the central bank of AI",
            title_zh="英伟达是人工智能的中央银行",
            url=shared_url,
            summary_en="⚡️ One-liner\nNvidia powers AI.\n\n🔥 Key takeaways\n✅ Chips",
            summary_zh="⚡️ 一句话总结\n英伟达撑起 AI。\n\n🔥 核心亮点\n✅ 芯片",
        ),
    )
    config = load_app_config()
    monkeypatch.setattr(config.paths, "hot_topics_path", str(hot_path))
    monkeypatch.setattr(config.paths, "content_digests_dir", str(digests_dir))
    monkeypatch.setattr("src.admin.app.load_app_config", lambda: config)

    res = client.get("/api/digests/2026-09-13")
    assert res.status_code == 200
    item = res.json()["items"][0]
    assert item["hot_topic_match"] is True
    assert item["can_copy_hot_adhd"] is True
    assert item["has_adhd"] is False


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
    captured: dict[str, object] = {}

    def _fake_adhd(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"path": "x", "changed": 3, "urls": kwargs.get("urls") or []}

    monkeypatch.setattr(
        "src.admin.app.generate_all_hot_topic_adhd",
        lambda *args, **kwargs: _fake_adhd(**kwargs),
    )
    res = client.post(
        "/api/hot-topics/items/adhd-all",
        json={"lang": "zh", "urls": ["https://example.com/hot"]},
    )
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
    assert captured["urls"] == ["https://example.com/hot"]


def test_digest_adhd_batch_job(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_batch(**kwargs: object) -> dict[str, object]:
        return {"day": "2026-09-13", "changed": 2, "indices": [1, 2]}

    monkeypatch.setattr(
        "src.admin.app.generate_digest_adhd_batch",
        lambda *args, **kwargs: _fake_batch(),
    )
    res = client.post(
        "/api/digests/2026-09-13/items/adhd-batch",
        json={"indices": [1, 2], "force": True},
    )
    assert res.status_code == 200
    job_id = res.json()["id"]
    import time

    for _ in range(20):
        status = client.get(f"/api/jobs/{job_id}").json()
        if status["status"] in {"done", "error", "cancelled"}:
            break
        time.sleep(0.05)
    assert status["status"] == "done"
    assert status["result"]["changed"] == 2


def test_digest_translate_titles_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_translate(**kwargs: object) -> dict[str, object]:
        return {"day": "2026-09-13", "changed": 2}

    monkeypatch.setattr(
        "src.admin.app.translate_digest_day_titles",
        lambda *args, **kwargs: _fake_translate(),
    )
    res = client.post("/api/digests/2026-09-13/translate-titles", json={})
    assert res.status_code == 200
    job_id = res.json()["id"]
    import time

    for _ in range(20):
        status = client.get(f"/api/jobs/{job_id}").json()
        if status["status"] in {"done", "error", "cancelled"}:
            break
        time.sleep(0.05)
    assert status["status"] == "done"
    assert status["result"]["changed"] == 2


def test_copy_hot_topic_to_digest_api(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_copy(**kwargs: object) -> dict[str, object]:
        return {
            "day": "2026-09-13",
            "index": 2,
            "created": True,
            "url": "https://example.com/hot",
        }

    monkeypatch.setattr(
        "src.admin.app.copy_hot_topic_to_digest",
        lambda *args, **kwargs: _fake_copy(),
    )
    res = client.post(
        "/api/hot-topics/items/copy-to-digest",
        json={"url": "https://example.com/hot", "day": "2026-09-13"},
    )
    assert res.status_code == 200
    assert res.json()["index"] == 2


def test_pull_data_job(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_pull(**kwargs: object) -> dict[str, object]:
        return {
            "hot_topics_count": 5,
            "digest_selected": 3,
            "archived": [],
        }

    monkeypatch.setattr(
        "src.admin.app.run_pull_data",
        lambda *args, **kwargs: _fake_pull(),
    )
    res = client.post("/api/pull", json={})
    assert res.status_code == 200
    job_id = res.json()["id"]
    import time

    for _ in range(20):
        status = client.get(f"/api/jobs/{job_id}").json()
        if status["status"] in {"done", "error", "cancelled"}:
            break
        time.sleep(0.05)
    assert status["status"] == "done"
    assert status["result"]["hot_topics_count"] == 5
    assert status["result"]["digest_selected"] == 3


def test_digest_translate_summaries_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_translate(**kwargs: object) -> dict[str, object]:
        return {"day": "2026-09-13", "changed": 2}

    monkeypatch.setattr(
        "src.admin.app.translate_digest_day_summaries",
        lambda *args, **kwargs: _fake_translate(),
    )
    res = client.post("/api/digests/2026-09-13/translate-summaries", json={})
    assert res.status_code == 200
    job_id = res.json()["id"]
    import time

    for _ in range(20):
        status = client.get(f"/api/jobs/{job_id}").json()
        if status["status"] in {"done", "error", "cancelled"}:
            break
        time.sleep(0.05)
    assert status["status"] == "done"
    assert status["result"]["changed"] == 2


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
