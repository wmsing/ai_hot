"""normalize / filter / digest 单测（无真实网络）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.digest import write_digest
from src.models import HotItem
from src.normalize import normalize_url, title_key
from src.storage import ItemStore


def test_normalize_url_strips_tracking() -> None:
    url = "https://Example.com/Path/?utm_source=x&id=1#frag"
    assert normalize_url(url) == "https://example.com/Path?id=1"


def test_title_key_strips_punct() -> None:
    assert title_key("Hello, World!!!") == "hello world"


def test_store_dedup_url_or_title(tmp_path: Path) -> None:
    store = ItemStore(tmp_path / "t.db")
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    item = HotItem(
        source="hn",
        title="Cool AI Model",
        url="https://example.com/a",
        score=200,
        comments=50,
        reason="test",
    )
    store.upsert_seen(item, now=now)

    assert store.is_seen(
        "https://example.com/a?utm_source=y",
        "Other Title",
        cooldown_hours=24,
        now=now + timedelta(hours=1),
    )
    assert store.is_seen(
        "https://other.com/b",
        "Cool AI Model!!!",
        cooldown_hours=24,
        now=now + timedelta(hours=1),
    )
    assert not store.is_seen(
        "https://other.com/b",
        "Totally Different",
        cooldown_hours=24,
        now=now + timedelta(hours=1),
    )
    # 冷却过期
    assert not store.is_seen(
        "https://example.com/a",
        "Cool AI Model",
        cooldown_hours=24,
        now=now + timedelta(hours=25),
    )
    store.close()


def test_write_digest(tmp_path: Path) -> None:
    path = tmp_path / "digest.md"
    items = [
        HotItem(
            source="hn",
            title="Example",
            url="https://example.com",
            score=120,
            comments=30,
            reason="hn score>=100",
        )
    ]
    write_digest(
        path,
        items,
        generated_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
    )
    text = path.read_text(encoding="utf-8")
    assert "Example" in text
    assert "why: hn score>=100" in text
    assert "summary: n/a" in text
    assert "published: n/a" in text


def test_digest_includes_published(tmp_path: Path) -> None:
    path = tmp_path / "digest.md"
    write_digest(
        path,
        [
            HotItem(
                source="hn",
                title="T",
                url="https://example.com",
                published_at=datetime(2026, 9, 10, 8, 0, 0, tzinfo=timezone.utc),
                reason="test",
            )
        ],
        generated_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
    )
    assert "published: 2026-09-10T08:00:00+00:00" in path.read_text(encoding="utf-8")


def test_from_unix() -> None:
    from src.timeutil import format_published, from_unix

    dt = from_unix(1_725_955_200)
    assert dt is not None
    assert format_published(dt).startswith("2024-")


def test_digest_includes_summary(tmp_path: Path) -> None:
    path = tmp_path / "digest.md"
    write_digest(
        path,
        [
            HotItem(
                source="rss:openai",
                title="T",
                url="https://example.com",
                summary="A short blurb about the news.",
                reason="rss_new",
            )
        ],
        generated_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
    )
    assert "summary: A short blurb about the news." in path.read_text(encoding="utf-8")


def test_resolve_llm_model() -> None:
    from src.pipeline import resolve_llm_model

    assert resolve_llm_model(None, "qwen3:4b-instruct") is None
    assert resolve_llm_model("qwen", "qwen3:4b-instruct") == "qwen3:4b-instruct"
    assert resolve_llm_model("qwen3:8b", "qwen3:4b-instruct") == "qwen3:8b"


def test_strip_html_truncate() -> None:
    from src.textutil import strip_html, truncate

    assert strip_html("<p>Hello <b>World</b></p>") == "Hello World"
    assert truncate("abcd", 3) == "ab…"


def test_qbitai_keyword_filter() -> None:
    from src.keywords import matched_keyword, passes_keywords

    kws = ["MiniMax", "Seedance", "Kimi"]
    hit = HotItem(
        source="rss:qbitai",
        title="MiniMax 新模型发布",
        url="https://example.com/a",
        summary="无关",
    )
    miss = HotItem(
        source="rss:qbitai",
        title="某手机发布会",
        url="https://example.com/b",
        summary="消费电子",
    )
    assert passes_keywords(hit, kws)
    assert matched_keyword(hit, kws) == "MiniMax"
    assert not passes_keywords(miss, kws)
    assert passes_keywords(miss, [])  # 无白名单不过滤


def test_mock_hn_http() -> None:
    """示范外部 HTTP Mock，避免测试真打 HN。"""
    client = MagicMock()
    client.get.return_value.json.return_value = [1]
    client.get.return_value.raise_for_status = MagicMock()
    assert client.get("x").json() == [1]


def test_translate_digest_file_mocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.models import AppConfig, OllamaConfig, PathsConfig
    from src.ollama_translate import translate_digest_file

    src = tmp_path / "digest.md"
    dst = tmp_path / "digest.zh.md"
    src.write_text("# Hello\n\n- url: https://x.com\n", encoding="utf-8")
    cfg = AppConfig(
        paths=PathsConfig(digest_path=str(src), digest_zh_path=str(dst)),
        ollama=OllamaConfig(model="qwen3:4b-instruct"),
    )

    def _fake_translate(text: str, ollama: OllamaConfig) -> str:
        assert "Hello" in text
        assert ollama.model == "qwen3:4b-instruct"
        return "# 你好\n\n- url: https://x.com\n"

    monkeypatch.setattr("src.ollama_translate.translate_markdown", _fake_translate)
    out = translate_digest_file(cfg)
    assert out == dst
    assert "你好" in dst.read_text(encoding="utf-8")
