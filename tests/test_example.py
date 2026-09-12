"""normalize / filter / digest 单测（无真实网络）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.digest import (
    has_usable_digest_summary,
    load_hot_items,
    merge_by_url,
    prune_empty_summaries,
    same_utc_day,
    write_digest,
)
from src.models import HotItem
from src.normalize import normalize_url, title_key
from src.storage import ItemStore


def test_has_usable_digest_summary_rejects_empty() -> None:
    assert has_usable_digest_summary(
        "OpenAI shipped Agents API for multi-step tool use in apps."
    )
    assert not has_usable_digest_summary("n/a")
    assert not has_usable_digest_summary("无内容")
    assert not has_usable_digest_summary("")
    junk = "Help Center Skip to main contentAPI docsRelease notesHow to get support"
    assert not has_usable_digest_summary(junk, title="Age")


def test_prune_empty_summaries_keeps_index(
    tmp_path: Path,
) -> None:
    path = tmp_path / "digest.md"
    path.write_text(
        "# ai_hot digest\n\nGenerated (UTC): 2026-09-11T12:00:00+00:00\n"
        "Selected: 2\n\n"
        "## 1. Keep\n\n- source: `hn`\n- url: https://a.example/1\n"
        "- summary: A real usable summary about shipping an API today.\n\n"
        "## 115. Drop\n\n- source: `hn`\n- url: https://a.example/115\n"
        "- summary: n/a\n",
        encoding="utf-8",
    )
    assert prune_empty_summaries(path) == 1
    text = path.read_text(encoding="utf-8")
    assert "## 1. Keep" in text
    assert "## 115." not in text
    assert "Selected: 1" in text
    assert "n/a" not in text


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


def test_resolve_llm_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.llm import resolve_llm_model
    from src.models import AppConfig, OllamaConfig, OpenRouterConfig

    monkeypatch.delenv("LLM_PROVIDER", raising=False)
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


def test_openrouter_fallback_on_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.models import LlmRuntime
    from src.ollama_client import llm_chat

    calls: list[str] = []

    class _Resp:
        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    class _Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, headers: dict, json: dict) -> _Resp:
            model = str(json["model"])
            calls.append(model)
            if model == "primary:free":
                return _Resp(
                    {
                        "model": "primary:free",
                        "choices": [{"message": {"content": ""}}],
                    }
                )
            return _Resp(
                {
                    "model": "openrouter/free",
                    "choices": [{"message": {"content": "ok zh"}}],
                }
            )

    monkeypatch.setattr("src.ollama_client.httpx.Client", _Client)
    runtime = LlmRuntime(
        provider="openrouter",
        model="primary:free",
        base_url="https://openrouter.ai/api/v1",
        api_key="test-key",
        fallback_model="openrouter/free",
    )
    assert llm_chat(system="s", user="u", llm=runtime) == "ok zh"
    assert calls == ["primary:free", "openrouter/free"]


def test_ollama_chat_sends_num_ctx(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.models import LlmRuntime
    from src.ollama_client import llm_chat

    captured: dict[str, object] = {}

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"message": {"content": "one line summary"}}

    class _Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, json: dict) -> _Resp:
            captured["url"] = url
            captured["json"] = json
            return _Resp()

    monkeypatch.setattr("src.ollama_client.httpx.Client", _Client)
    runtime = LlmRuntime(
        provider="ollama",
        model="qwen3:4b-instruct",
        base_url="http://127.0.0.1:11434",
        num_ctx=8192,
        think=False,
    )
    assert llm_chat(system="s", user="u", llm=runtime) == "one line summary"
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["options"] == {"num_ctx": 8192}
    assert payload["think"] is False


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
    assert _display_tag("video", "en") == "Video"
    assert _display_tag("video", "zh") == "视频"
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
    from src.models import AppConfig, LlmRuntime, OllamaConfig, PathsConfig
    from src.ollama_translate import translate_digest_file

    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    src = tmp_path / "digest.md"
    dst = tmp_path / "digest.zh.md"
    src.write_text(
        "# ai_hot digest\n\nGenerated (UTC): 2026-09-11T00:00:00+00:00\n"
        "Selected: 1\n\n## 1. Hello\n\n- source: `hn`\n"
        "- url: https://x.com\n- summary: Hello body\n",
        encoding="utf-8",
    )
    cfg = AppConfig(
        paths=PathsConfig(digest_path=str(src), digest_zh_path=str(dst)),
        ollama=OllamaConfig(model="qwen3:4b-instruct"),
    )

    def _fake_translate(text: str, llm: LlmRuntime | OllamaConfig) -> str:
        assert "Hello" in text
        assert isinstance(llm, LlmRuntime)
        assert llm.provider == "ollama"
        assert llm.model == "qwen3:4b-instruct"
        return (
            "# ai_hot digest\n\nGenerated (UTC): 2026-09-11T00:00:00+00:00\n"
            "Selected: 1\n\n## 1. 你好\n\n- source: `hn`\n"
            "- url: https://x.com\n- summary: 你好正文\n"
        )

    monkeypatch.setattr("src.ollama_translate.translate_markdown", _fake_translate)
    out = translate_digest_file(cfg)
    assert out == dst
    text = dst.read_text(encoding="utf-8")
    assert "你好" in text
    assert "https://x.com" in text


def test_translate_digest_file_incremental_reuses_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.models import AppConfig, LlmRuntime, OllamaConfig, PathsConfig
    from src.ollama_translate import translate_digest_file

    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    src = tmp_path / "digest.md"
    dst = tmp_path / "digest.zh.md"
    src.write_text(
        "# ai_hot digest\n\nGenerated (UTC): 2026-09-11T01:00:00+00:00\n"
        "Selected: 2\n\n"
        "## 1. Old EN\n\n- source: `hn`\n- url: https://a.example/old\n"
        "- summary: old en summary\n\n"
        "## 2. New EN\n\n- source: `hn`\n- url: https://a.example/new\n"
        "- summary: new en summary\n",
        encoding="utf-8",
    )
    dst.write_text(
        "# ai_hot digest\n\nGenerated (UTC): 2026-09-11T00:00:00+00:00\n"
        "Selected: 1\n\n"
        "## 1. 旧中文\n\n- source: `hn`\n- url: https://a.example/old\n"
        "- summary: 旧摘要\n",
        encoding="utf-8",
    )
    cfg = AppConfig(
        paths=PathsConfig(digest_path=str(src), digest_zh_path=str(dst)),
        ollama=OllamaConfig(model="qwen3:4b-instruct"),
    )
    seen: list[str] = []

    def _fake_translate(text: str, llm: LlmRuntime | OllamaConfig) -> str:
        seen.append(text)
        assert "https://a.example/new" in text
        assert "https://a.example/old" not in text
        assert isinstance(llm, LlmRuntime)
        return (
            "# ai_hot digest\n\nGenerated (UTC): 2026-09-11T01:00:00+00:00\n"
            "Selected: 1\n\n"
            "## 1. 新中文\n\n- source: `hn`\n- url: https://a.example/new\n"
            "- summary: 新摘要\n"
        )

    monkeypatch.setattr("src.ollama_translate.translate_markdown", _fake_translate)
    translate_digest_file(cfg)
    assert len(seen) == 1
    out = dst.read_text(encoding="utf-8")
    assert "旧中文" in out
    assert "旧摘要" in out
    assert "新中文" in out
    assert "新摘要" in out
    assert out.index("旧中文") < out.index("新中文")


def test_translate_digest_file_batches_llm_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.models import AppConfig, LlmRuntime, OllamaConfig, PathsConfig
    from src.ollama_translate import translate_digest_file

    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    src = tmp_path / "digest.md"
    dst = tmp_path / "digest.zh.md"
    blocks = [
        "# ai_hot digest\n\nGenerated (UTC): 2026-09-11T01:00:00+00:00\nSelected: 5\n"
    ]
    for i in range(1, 6):
        blocks.append(
            f"## {i}. Item {i}\n\n- source: `hn`\n"
            f"- url: https://ex.example/{i}\n- summary: body {i}\n"
        )
    src.write_text("\n".join(blocks), encoding="utf-8")
    cfg = AppConfig(
        paths=PathsConfig(digest_path=str(src), digest_zh_path=str(dst)),
        ollama=OllamaConfig(model="qwen3:4b-instruct", translate_batch_size=2),
    )
    calls: list[str] = []

    def _fake_translate(text: str, llm: LlmRuntime | OllamaConfig) -> str:
        calls.append(text)
        assert isinstance(llm, LlmRuntime)
        # 原样回传即可被 parse；标题加 ZH 标记方便断言
        return text.replace("Item ", "条目 ")

    monkeypatch.setattr("src.ollama_translate.translate_markdown", _fake_translate)
    translate_digest_file(cfg)
    assert len(calls) == 3  # 2+2+1
    assert "https://ex.example/1" in calls[0]
    assert "https://ex.example/2" in calls[0]
    assert "https://ex.example/5" in calls[2]
    out = dst.read_text(encoding="utf-8")
    assert "条目 1" in out
    assert "条目 5" in out


def test_translate_digest_file_retries_english_placeholder_zh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.models import AppConfig, LlmRuntime, OllamaConfig, PathsConfig
    from src.ollama_translate import translate_digest_file

    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    src = tmp_path / "digest.md"
    dst = tmp_path / "digest.zh.md"
    src.write_text(
        "# ai_hot digest\n\nGenerated (UTC): 2026-09-11T01:00:00+00:00\n"
        "Selected: 1\n\n"
        "## 1. Still EN\n\n- source: `hn`\n- url: https://a.example/stale\n"
        "- summary: still english summary\n",
        encoding="utf-8",
    )
    dst.write_text(
        "# ai_hot digest\n\nGenerated (UTC): 2026-09-11T00:00:00+00:00\n"
        "Selected: 1\n\n"
        "## 1. Still EN\n\n- source: `hn`\n- url: https://a.example/stale\n"
        "- summary: still english summary\n",
        encoding="utf-8",
    )
    cfg = AppConfig(
        paths=PathsConfig(digest_path=str(src), digest_zh_path=str(dst)),
        ollama=OllamaConfig(model="qwen3:4b-instruct"),
    )

    def _fake_translate(text: str, llm: LlmRuntime | OllamaConfig) -> str:
        assert "still english summary" in text
        return (
            "# ai_hot digest\n\nGenerated (UTC): 2026-09-11T01:00:00+00:00\n"
            "Selected: 1\n\n"
            "## 1. 已是中文\n\n- source: `hn`\n- url: https://a.example/stale\n"
            "- summary: 已是中文摘要\n"
        )

    monkeypatch.setattr("src.ollama_translate.translate_markdown", _fake_translate)
    translate_digest_file(cfg)
    out = dst.read_text(encoding="utf-8")
    assert "已是中文" in out
    assert "已是中文摘要" in out
    assert "still english summary" not in out


def test_translate_digest_file_no_llm_when_all_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.models import AppConfig, LlmRuntime, OllamaConfig, PathsConfig
    from src.ollama_translate import translate_digest_file

    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    src = tmp_path / "digest.md"
    dst = tmp_path / "digest.zh.md"
    body = (
        "# ai_hot digest\n\nGenerated (UTC): 2026-09-11T02:00:00+00:00\n"
        "Selected: 1\n\n"
        "## 1. Same\n\n- source: `hn`\n- url: https://a.example/same\n"
        "- summary: same en\n"
    )
    src.write_text(body, encoding="utf-8")
    dst.write_text(
        "# ai_hot digest\n\nGenerated (UTC): 2026-09-11T01:00:00+00:00\n"
        "Selected: 1\n\n"
        "## 1. 已译\n\n- source: `hn`\n- url: https://a.example/same\n"
        "- summary: 已译摘要\n",
        encoding="utf-8",
    )
    cfg = AppConfig(
        paths=PathsConfig(digest_path=str(src), digest_zh_path=str(dst)),
        ollama=OllamaConfig(model="qwen3:4b-instruct"),
    )

    def _boom(text: str, llm: LlmRuntime | OllamaConfig) -> str:
        raise AssertionError("should not call LLM when all URLs reused")

    monkeypatch.setattr("src.ollama_translate.translate_markdown", _boom)
    translate_digest_file(cfg)
    out = dst.read_text(encoding="utf-8")
    assert "已译" in out
    assert "已译摘要" in out


def test_translate_digest_file_model_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.models import AppConfig, LlmRuntime, OllamaConfig, PathsConfig
    from src.ollama_translate import translate_digest_file

    src = tmp_path / "digest.md"
    dst = tmp_path / "digest.zh.md"
    src.write_text(
        "# ai_hot digest\n\nGenerated (UTC): 2026-09-11T00:00:00+00:00\n"
        "Selected: 1\n\n## 1. Hi\n\n- source: `hn`\n"
        "- url: https://y.com\n- summary: hi\n",
        encoding="utf-8",
    )
    cfg = AppConfig(
        paths=PathsConfig(digest_path=str(src), digest_zh_path=str(dst)),
        ollama=OllamaConfig(model="qwen3:4b-instruct"),
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    seen: list[str] = []

    def _fake_translate(text: str, llm: LlmRuntime | OllamaConfig) -> str:
        assert isinstance(llm, LlmRuntime)
        seen.append(llm.model)
        assert llm.provider == "openrouter"
        return (
            "# ai_hot digest\n\nGenerated (UTC): 2026-09-11T00:00:00+00:00\n"
            "Selected: 1\n\n## 1. 嗨\n\n- source: `hn`\n"
            "- url: https://y.com\n- summary: 嗨\n"
        )

    monkeypatch.setattr("src.ollama_translate.translate_markdown", _fake_translate)
    translate_digest_file(cfg, model="nvidia/nemotron-3-ultra-550b-a55b:free")
    assert seen == ["nvidia/nemotron-3-ultra-550b-a55b:free"]


def test_translate_cli_model_flag() -> None:
    from src.translate import _parse_args

    args = _parse_args(["--model", "nvidia/nemotron-3-ultra-550b-a55b:free"])
    assert args.model == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert _parse_args([]).model is None


def test_main_should_translate_defaults() -> None:
    from src.main import _parse_args, should_translate

    assert should_translate(_parse_args(["--llm", "qwen"]))
    assert should_translate(_parse_args(["--llm"]))
    assert not should_translate(_parse_args([]))
    assert should_translate(_parse_args(["--llm", "qwen", "--translate"]))
    assert not should_translate(_parse_args(["--llm", "qwen", "--no-translate"]))


def test_main_runs_translate_after_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.main import main
    from src.models import AppConfig, HotItem

    calls: list[str] = []
    item = HotItem(source="hn", title="T", url="https://x.com", summary="s")

    monkeypatch.setattr("src.main.load_app_config", lambda: AppConfig())
    monkeypatch.setattr("src.main.run_once", lambda *a, **k: [item])
    monkeypatch.setattr(
        "src.main.translate_digest_file",
        lambda config, *, model=None: calls.append(model or "") or Path("out/digest.zh.md"),
    )

    assert main(["--llm", "qwen"]) == 0
    assert calls == ["qwen"]

    calls.clear()
    assert main(["--llm", "qwen", "--no-translate"]) == 0
    assert calls == []
