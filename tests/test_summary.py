"""摘要优化：套话检测、RSS 优先、junk 强制重写（无真实网络）。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.models import AppConfig, HotItem, LlmRuntime, PathsConfig
from src.ollama_client import (
    is_junk_summary,
    is_usable_source_summary,
    summarize_item,
    summary_has_cliches,
)
from src.pipeline import _enrich_with_llm
from src.resummarize import resummarize_digest


def test_summary_has_cliches_detects_common_filler() -> None:
    assert summary_has_cliches("This marks a major step toward autonomous agents.")
    assert summary_has_cliches("The release positions it as a strong contender.")
    assert not summary_has_cliches("OpenAI shipped Agents API for multi-step tool use.")


def test_is_usable_source_summary_length_and_title() -> None:
    long = (
        "OpenAI released an Agents API so developers can build apps that "
        "run multi-step research and tool calls without hand-written loops."
    )
    assert is_usable_source_summary(long, title="OpenAI Agents API")
    assert not is_usable_source_summary("Too short.", title="x")
    assert not is_usable_source_summary(long, title=long)


def test_is_junk_summary_detects_help_center_chrome() -> None:
    junk = (
        "Age assurance on Claude | Claude Help Center Skip to main content"
        "API docsRelease notesHow to get supportEnglishFrançais"
        "How do I change the email address associated with my account?"
        "Delete your Claude accountWhy is a coupon"
    )
    assert is_junk_summary(
        junk, title="Claude is only available to people over 18 years"
    )
    assert not is_usable_source_summary(
        junk, title="Claude is only available to people over 18 years"
    )
    good = (
        "Anthropic requires age assurance for Claude accounts so access is "
        "limited to people 18 and older in supported regions."
    )
    assert not is_junk_summary(good)


def test_summarize_item_retries_once_on_cliche() -> None:
    item = HotItem(
        source="hn",
        title="OpenAI Agents API",
        url="https://example.com/agents",
        reason="test",
        summary="thin",
    )
    runtime = LlmRuntime(
        provider="ollama",
        model="dummy",
        base_url="http://127.0.0.1:11434",
        timeout_seconds=1,
        api_key="",
    )
    bad = "This marks a major step for agent frameworks."
    good = "OpenAI launched Agents API for multi-step tool-using apps."
    with patch(
        "src.ollama_client.llm_chat",
        side_effect=[bad, good],
    ) as chat:
        out = summarize_item(item, runtime)
    assert out == good
    assert chat.call_count == 2


def test_summarize_item_falls_back_to_source_after_two_cliches() -> None:
    source = "Official blurb kept when model stays fluffy twice."
    item = HotItem(
        source="rss:openai",
        title="Agents",
        url="https://example.com/a",
        reason="test",
        summary=source,
    )
    runtime = LlmRuntime(
        provider="ollama",
        model="dummy",
        base_url="http://127.0.0.1:11434",
        timeout_seconds=1,
        api_key="",
    )
    bad = "This is an exciting development and a game-changer."
    with patch("src.ollama_client.llm_chat", return_value=bad):
        out = summarize_item(item, runtime)
    assert out == source


def test_summarize_item_drops_junk_instead_of_keeping_chrome() -> None:
    junk = (
        "Claude Help Center Skip to main contentAPI docsRelease notes"
        "How to get supportEnglishFrançaisDelete your Claude account"
    )
    item = HotItem(
        source="hn",
        title="Claude is only available to people over 18 years",
        url="https://support.claude.com/en/articles/x",
        reason="test",
        summary=junk,
    )
    runtime = LlmRuntime(
        provider="ollama",
        model="dummy",
        base_url="http://127.0.0.1:11434",
        timeout_seconds=1,
        api_key="",
    )
    bad = "This marks a major step for age assurance."
    with patch("src.ollama_client.llm_chat", return_value=bad):
        out = summarize_item(item, runtime)
    assert out == ""


def test_enrich_skips_llm_when_rss_summary_usable() -> None:
    long = (
        "Google DeepMind published a blog post describing a new training "
        "recipe that cuts inference cost for long-context models by half."
    )
    item = HotItem(
        source="rss:deepmind",
        title="Cheaper long context",
        url="https://example.com/dm",
        reason="test",
        summary=long,
    )
    llm = MagicMock()
    with patch("src.pipeline.summarize_item") as summarize:
        out = _enrich_with_llm([item], llm)
    summarize.assert_not_called()
    assert out[0].summary == long


def test_enrich_forces_llm_on_junk_rss_summary() -> None:
    junk = (
        "Product docs Skip to main contentAPI docsRelease notesHow to get "
        "supportEnglishFrançaisDeutsch"
    )
    item = HotItem(
        source="rss:openai",
        title="Age rules",
        url="https://example.com/age",
        reason="test",
        summary=junk,
    )
    llm = MagicMock()
    with patch(
        "src.pipeline.summarize_item",
        return_value="Claude access is limited to adults 18+.",
    ) as summarize:
        out = _enrich_with_llm([item], llm)
    summarize.assert_called_once()
    assert out[0].summary == "Claude access is limited to adults 18+."


def test_resummarize_digest_rewrites_junk_only(tmp_path: Path) -> None:
    digest = tmp_path / "digest.md"
    junk = (
        "Help Center Skip to main contentAPI docsRelease notesHow to get "
        "supportEnglishFrançais"
    )
    digest.write_text(
        "# ai_hot digest\n\nGenerated (UTC): 2026-09-11T12:00:00+00:00\n"
        "Selected: 2\n\n"
        "## 1. Good item\n\n- source: `rss:openai`\n"
        "- url: https://example.com/good\n"
        "- summary: OpenAI shipped a short usable blurb about Agents API for "
        "developers building multi-step tools in production apps today.\n\n"
        "## 2. Claude age\n\n- source: `hn`\n"
        "- url: https://example.com/claude-age\n"
        f"- summary: {junk}\n",
        encoding="utf-8",
    )
    cfg = AppConfig(paths=PathsConfig(digest_path=str(digest)))

    def _fake_enrich(items: list[HotItem], llm: object) -> list[HotItem]:
        assert len(items) == 1
        assert items[0].url == "https://example.com/claude-age"
        return [
            items[0].model_copy(
                update={"summary": "Claude requires users to be 18 or older."}
            )
        ]

    with patch("src.resummarize._enrich_with_llm", side_effect=_fake_enrich):
        with patch("src.resummarize.build_llm_runtime", return_value=MagicMock()):
            path, n = resummarize_digest(cfg)
    assert path == digest
    assert n == 1
    text = digest.read_text(encoding="utf-8")
    assert "Claude requires users to be 18 or older." in text
    assert "Skip to main content" not in text
    assert "OpenAI shipped a short usable blurb" in text
