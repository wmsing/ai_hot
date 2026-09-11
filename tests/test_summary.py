"""摘要优化：套话检测、RSS 优先、重试逻辑（无真实网络）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.models import HotItem, LlmRuntime
from src.ollama_client import (
    is_usable_source_summary,
    summarize_item,
    summary_has_cliches,
)
from src.pipeline import _enrich_with_llm


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
