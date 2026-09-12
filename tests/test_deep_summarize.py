"""deep_summarize：按 URL 全文 ADHD 精写（mock 网络与 LLM）。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.digest import write_digest
from src.models import AppConfig, HotItem, LlmRuntime, OllamaConfig, PathsConfig


def _item(url: str, title: str, summary: str) -> HotItem:
    return HotItem(
        source="rss:openai",
        title=title,
        url=url,
        summary=summary,
        published_at=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
        reason="test",
    )


def test_deep_summarize_updates_only_selected_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src import deep_summarize as mod

    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    en = tmp_path / "digest.md"
    zh = tmp_path / "digest.zh.md"
    a = "https://example.com/a"
    b = "https://example.com/b"
    generated = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    write_digest(
        en,
        [
            _item(a, "Keep EN A", "old en a"),
            _item(b, "Deep EN B", "old en b"),
        ],
        generated_at=generated,
    )
    write_digest(
        zh,
        [
            _item(a, "保留中文 A", "旧摘要 A"),
            _item(b, "待精写 B", "旧摘要 B"),
        ],
        generated_at=generated,
    )
    cfg = AppConfig(
        paths=PathsConfig(digest_path=str(en), digest_zh_path=str(zh)),
        ollama=OllamaConfig(model="qwen3.5:9b"),
    )
    runtime = LlmRuntime(
        provider="ollama",
        model="qwen3.5:9b",
        base_url="http://127.0.0.1:11434",
        timeout_seconds=1,
        api_key="",
    )

    def _fake_fetch(client: object, url: str, *, max_chars: int = 8000) -> str:
        assert url == b
        assert max_chars >= 100
        return "Full article body about Perplexity using Astra in production. " * 10

    def _fake_chat(*, system: str, user: str, llm: LlmRuntime) -> str:
        assert llm.model == "qwen3.5:9b"
        assert "Full article body" in user
        if "核心亮点" in system:
            return (
                "⚡️ 一句话总结\n"
                "Perplexity 把底层系统交给 Astra 来跑。\n\n"
                "🔥 核心亮点\n"
                "🤖 自动干活\n"
                "🙈 放手不管\n"
            )
        return (
            "⚡️ One-liner\n"
            "Perplexity now runs more systems on Astra with less oversight.\n\n"
            "🔥 Key takeaways\n"
            "🤖 Auto-runs production chores\n"
            "🙈 Needs less human checking\n"
        )

    en_path, zh_path, n = mod.deep_summarize_digest(
        cfg,
        urls=[b],
        runtime=runtime,
        client=object(),  # type: ignore[arg-type]
        fetch_body=_fake_fetch,
        chat=_fake_chat,
    )
    assert n == 1
    assert en_path == en
    assert zh_path == zh
    en_text = en.read_text(encoding="utf-8")
    zh_text = zh.read_text(encoding="utf-8")
    assert "old en a" in en_text
    assert "One-liner" in en_text
    assert "Key takeaways" in en_text
    assert "Perplexity now runs more systems on Astra" in en_text
    assert "- speak:" in en_text
    assert "⚡️" not in en_text.split("- speak:", 1)[1].split("\n## ", 1)[0]
    assert "保留中文 A" in zh_text
    assert "旧摘要 A" in zh_text
    assert "一句话总结" in zh_text
    assert "核心亮点" in zh_text
    assert "- speak:" in zh_text
    assert "⚡️" not in zh_text.split("- speak:", 1)[1].split("\n## ", 1)[0]
    assert "旧摘要 B" not in zh_text


def test_deep_summarize_trailing_slash_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src import deep_summarize as mod

    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    en = tmp_path / "digest.md"
    zh = tmp_path / "digest.zh.md"
    canonical = "https://example.com/story"
    generated = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    write_digest(
        en,
        [_item(canonical, "Story", "old en")],
        generated_at=generated,
    )
    write_digest(
        zh,
        [_item(canonical, "故事", "旧摘要")],
        generated_at=generated,
    )
    cfg = AppConfig(
        paths=PathsConfig(digest_path=str(en), digest_zh_path=str(zh)),
        ollama=OllamaConfig(model="qwen3.5:9b"),
    )

    def _fake_fetch(client: object, url: str, *, max_chars: int = 8000) -> str:
        assert url == canonical
        return "Article body text about the story content here. " * 12

    def _fake_chat(*, system: str, user: str, llm: LlmRuntime) -> str:
        if "核心亮点" in system:
            return "⚡️ 一句话总结\n故事很重要。\n\n🔥 核心亮点 (TL;DR)\n✅ 一条\n"
        return (
            "⚡️ One-liner\n"
            "The story matters.\n\n"
            "🔥 Key takeaways (TL;DR)\n"
            "✅ One point\n"
        )

    _, _, n = mod.deep_summarize_digest(
        cfg,
        urls=[canonical + "/"],
        runtime=LlmRuntime(
            provider="ollama",
            model="qwen3.5:9b",
            base_url="http://127.0.0.1:11434",
            timeout_seconds=1,
            api_key="",
        ),
        client=object(),  # type: ignore[arg-type]
        fetch_body=_fake_fetch,
        chat=_fake_chat,
    )
    assert n == 1
    zh_text = zh.read_text(encoding="utf-8")
    en_text = en.read_text(encoding="utf-8")
    assert "一句话总结" in zh_text
    assert "(TL;DR)" not in zh_text
    assert "One-liner" in en_text
    assert "Key takeaways" in en_text
    assert "(TL;DR)" not in en_text


def test_normalize_adhd_summary_strips_tldr() -> None:
    from src.deep_summarize import _normalize_adhd_summary

    raw = "⚡️ 一句话总结\n正文\n\n🔥 核心亮点 (TL;DR)\n🤖 一条"
    out = _normalize_adhd_summary(raw)
    assert "(TL;DR)" not in out
    assert "🔥 核心亮点\n" in out

    en_raw = "⚡️ One-liner\nBody\n\n🔥 Key takeaways (TL;DR)\n🤖 One"
    en_out = _normalize_adhd_summary(en_raw)
    assert "(TL;DR)" not in en_out
    assert "🔥 Key takeaways\n" in en_out


def test_deep_summarize_requires_url_in_digest(tmp_path: Path) -> None:
    from src import deep_summarize as mod

    en = tmp_path / "digest.md"
    zh = tmp_path / "digest.zh.md"
    write_digest(
        en,
        [_item("https://example.com/only", "Only", "sum")],
        generated_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
    )
    cfg = AppConfig(
        paths=PathsConfig(digest_path=str(en), digest_zh_path=str(zh)),
    )
    with pytest.raises(ValueError, match="not in English digest"):
        mod.deep_summarize_digest(
            cfg,
            urls=["https://example.com/missing"],
            runtime=LlmRuntime(
                provider="ollama",
                model="x",
                base_url="http://127.0.0.1:11434",
                timeout_seconds=1,
                api_key="",
            ),
            client=object(),  # type: ignore[arg-type]
            fetch_body=lambda *a, **k: "body " * 50,
            chat=lambda **k: "x",
        )
