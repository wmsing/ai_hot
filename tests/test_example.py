"""normalize / filter / digest 单测（无真实网络）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.digest import (
    load_hot_items,
    merge_by_url,
    same_utc_day,
    write_digest,
)
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
    assert "why:" not in text
    assert "score=120 | comments=30" in text
    assert "summary: n/a" in text
    assert "published:" not in text


def test_write_digest_omits_empty_score(tmp_path: Path) -> None:
    path = tmp_path / "digest.md"
    write_digest(
        path,
        [
            HotItem(
                source="rss:openai",
                title="T",
                url="https://example.com",
                summary="blurb",
                published_at=datetime(2026, 9, 10, 1, 58, 0, tzinfo=timezone.utc),
                reason="rss_new feed=openai",
            )
        ],
        generated_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
    )
    text = path.read_text(encoding="utf-8")
    assert "published: 2026-09-10 01:00 UTC" in text
    assert "score=" not in text
    assert "why:" not in text


def test_write_digest_includes_image(tmp_path: Path) -> None:
    path = tmp_path / "digest.md"
    write_digest(
        path,
        [
            HotItem(
                source="rss:google_ai",
                title="T",
                url="https://example.com",
                image_url="https://cdn.example/a.webp",
                summary="blurb",
                reason="r",
            )
        ],
        generated_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
    )
    text = path.read_text(encoding="utf-8")
    assert "- image: https://cdn.example/a.webp" in text


def test_entry_image_from_media_and_html() -> None:
    from types import SimpleNamespace

    from src.sources.rss import _entry_image

    media_entry = SimpleNamespace(
        media_thumbnail=[{"url": "https://cdn.example/thumb.jpg"}],
        media_content=[],
        enclosures=[],
        summary="",
        content=[],
    )
    assert _entry_image(media_entry) == "https://cdn.example/thumb.jpg"

    html_entry = SimpleNamespace(
        media_thumbnail=[],
        media_content=[],
        enclosures=[],
        summary='<p><img src="https://cdn.example/from-html.png" /></p>',
        content=[],
    )
    assert _entry_image(html_entry) == "https://cdn.example/from-html.png"

    empty = SimpleNamespace(
        media_thumbnail=[],
        media_content=[],
        enclosures=[],
        summary="no image here",
        content=[],
    )
    assert _entry_image(empty) is None


def test_merge_by_url_appends_and_dedupes() -> None:
    existing = [
        HotItem(source="hn", title="A", url="https://example.com/a", reason="r1"),
        HotItem(source="hn", title="B", url="https://example.com/b", reason="r2"),
    ]
    new = [
        HotItem(source="hn", title="B dup", url="https://example.com/b", reason="r2"),
        HotItem(source="rss:x", title="C", url="https://example.com/c", reason="r3"),
    ]
    merged = merge_by_url(existing, new)
    assert [i.url for i in merged] == [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    ]
    assert len(merged) >= len(existing)


def test_same_utc_day() -> None:
    day = datetime(2026, 9, 10, 1, 0, 0, tzinfo=timezone.utc)
    assert same_utc_day(day, datetime(2026, 9, 10, 23, 0, 0, tzinfo=timezone.utc))
    assert not same_utc_day(day, datetime(2026, 9, 11, 0, 0, 0, tzinfo=timezone.utc))


def test_load_and_merge_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "digest.md"
    t0 = datetime(2026, 9, 10, 8, 0, 0, tzinfo=timezone.utc)
    write_digest(
        path,
        [
            HotItem(
                source="hn",
                title="One",
                url="https://example.com/1",
                score=100,
                comments=20,
                summary="first",
                published_at=t0,
                reason="r1",
            ),
            HotItem(
                source="rss:openai",
                title="Two",
                url="https://example.com/2",
                summary="second",
                reason="r2",
            ),
        ],
        generated_at=t0,
    )
    prev_at, prev_items = load_hot_items(path)
    assert prev_at is not None
    assert same_utc_day(prev_at, t0)
    assert len(prev_items) == 2

    new = [
        HotItem(
            source="hn",
            title="Two again",
            url="https://example.com/2",
            reason="dup",
        ),
        HotItem(
            source="hn",
            title="Three",
            url="https://example.com/3",
            score=150,
            comments=40,
            reason="r3",
        ),
    ]
    merged = merge_by_url(prev_items, new)
    assert len(merged) == 3
    assert merged[-1].url == "https://example.com/3"
    assert merged[0].summary == "first"
    assert merged[0].score == 100


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
    assert "published: 2026-09-10 08:00 UTC" in path.read_text(encoding="utf-8")


def test_from_unix() -> None:
    from src.timeutil import format_published, from_unix

    dt = from_unix(1_725_955_200)
    assert dt is not None
    assert format_published(dt).endswith("UTC")
    assert format_published(dt).count(":") == 1


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
    from src.llm import resolve_llm_model
    from src.models import AppConfig, OllamaConfig, OpenRouterConfig

    cfg = AppConfig(
        ollama=OllamaConfig(model="qwen3:4b-instruct"),
        openrouter=OpenRouterConfig(model="openrouter/free"),
    )
    assert resolve_llm_model(None, cfg) is None
    assert resolve_llm_model("qwen", cfg) == "qwen3:4b-instruct"
    assert resolve_llm_model("qwen3:8b", cfg) == "qwen3:8b"
    assert resolve_llm_model("openrouter", cfg) == "openrouter/free"


def test_resolve_provider_openrouter_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.llm import resolve_provider
    from src.models import AppConfig

    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert resolve_provider("openrouter", AppConfig()) == "openrouter"
    assert resolve_provider("qwen", AppConfig()) == "ollama"
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    assert resolve_provider("qwen", AppConfig()) == "openrouter"


def test_openrouter_content_parse() -> None:
    from src.ollama_client import _openrouter_content

    assert (
        _openrouter_content({"choices": [{"message": {"content": "  hello  "}}]})
        == "hello"
    )
    assert _openrouter_content({"choices": []}) == ""


def test_write_digest_tag(tmp_path: Path) -> None:
    path = tmp_path / "digest.md"
    write_digest(
        path,
        [
            HotItem(
                source="rss:apple_ml",
                title="A Paper",
                url="https://example.com/p",
                tag="paper",
                summary="About ML",
                reason="r",
            )
        ],
        generated_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
    )
    text = path.read_text(encoding="utf-8")
    assert "- tag: paper" in text
    from src.digest import load_hot_items

    _, items = load_hot_items(path)
    assert items[0].tag == "paper"


def test_display_tag_paper() -> None:
    from src.site_build import _display_tag

    assert _display_tag("paper", "en") == "Paper"
    assert _display_tag("paper", "zh") == "论文"
    assert _display_tag("", "en") == ""


def test_contains_cjk() -> None:
    from src.textutil import contains_cjk

    assert contains_cjk("实测星火X2.5")
    assert contains_cjk("Hello 世界")
    assert not contains_cjk("SkyProduction MiniMax")


def test_translate_cjk_fields_to_english_mocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.digest_en import translate_cjk_fields_to_english
    from src.models import OllamaConfig

    items = [
        HotItem(
            source="rss:qbitai",
            title="实测星火X2.5：手搓粒子月亮",
            url="https://example.com/a",
            summary="赶上了API限时五折",
            reason="rss_new feed=qbitai",
        ),
        HotItem(
            source="rss:openai",
            title="An Alien Mind",
            url="https://example.com/b",
            summary="English already",
            reason="rss_new feed=openai",
        ),
    ]

    def _fake(item: HotItem, ollama: OllamaConfig) -> tuple[str, str | None]:
        assert "星火" in item.title
        return ("Hands-on Spark X2.5", "API half-price promo")

    monkeypatch.setattr("src.digest_en.translate_item_to_english", _fake)
    out = translate_cjk_fields_to_english(items, OllamaConfig())
    assert out[0].title == "Hands-on Spark X2.5"
    assert out[0].summary == "API half-price promo"
    assert out[1].title == "An Alien Mind"
    assert out[1].summary == "English already"


def test_rewrite_digest_english_mocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.digest_en import rewrite_digest_english
    from src.models import AppConfig, OllamaConfig, PathsConfig

    path = tmp_path / "digest.md"
    write_digest(
        path,
        [
            HotItem(
                source="rss:qbitai",
                title="实测星火",
                url="https://example.com/a",
                summary="限时五折",
                reason="r",
            ),
            HotItem(
                source="hn",
                title="Hello",
                url="https://example.com/b",
                summary="ok",
                reason="r",
            ),
        ],
        generated_at=datetime(2026, 9, 10, 8, 0, 0, tzinfo=timezone.utc),
    )

    def _fake(item: HotItem, ollama: OllamaConfig) -> tuple[str, str | None]:
        return ("Spark hands-on", "Half-price API")

    monkeypatch.setattr("src.digest_en.translate_item_to_english", _fake)
    cfg = AppConfig(
        paths=PathsConfig(digest_path=str(path)),
        ollama=OllamaConfig(),
    )
    out, n = rewrite_digest_english(cfg)
    assert out == path
    assert n == 1
    text = path.read_text(encoding="utf-8")
    assert "Spark hands-on" in text
    assert "实测" not in text
    assert "Hello" in text


def test_parse_title_summary() -> None:
    from src.ollama_client import _parse_title_summary

    title, summary = _parse_title_summary(
        "TITLE: Hello World\nSUMMARY: A short blurb.\n"
    )
    assert title == "Hello World"
    assert summary == "A short blurb."


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
