"""页面片段提取与 HN 摘要止血（无真实网络）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from src.fetch_page import (
    extract_page_body,
    extract_page_snippet,
    fetch_page_snippet,
)
from src.models import HotItem, LlmRuntime
from src.ollama_client import summarize_item
from src.pipeline import _attach_hn_page_snippets, _enrich_with_llm


def test_extract_prefers_og_description() -> None:
    html = """
    <html><head>
      <meta name="description" content="meta fallback only">
      <meta property="og:description" content="OG says Shopify returns to native apps.">
    </head><body><p>Long body text ignored when OG exists.</p></body></html>
    """
    assert extract_page_snippet(html) == "OG says Shopify returns to native apps."


def test_extract_falls_back_to_meta_then_body() -> None:
    html_meta = """
    <html><head>
      <meta name="description" content="Meta description about the release.">
    </head><body><p>body</p></body></html>
    """
    assert extract_page_snippet(html_meta) == "Meta description about the release."

    html_body = """
    <html><body><script>ignore()</script>
    <p>Body paragraph with enough plain text for a snippet.</p>
    </body></html>
    """
    out = extract_page_snippet(html_body)
    assert out is not None
    assert "Body paragraph" in out
    assert "ignore" not in out


def test_extract_empty_html_returns_none() -> None:
    assert extract_page_snippet("<html><head></head><body></body></html>") is None


def test_extract_page_body_prefers_article_over_og() -> None:
    html = (
        """
    <html><head>
      <meta property="og:description" content="Short OG only.">
    </head><body>
      <nav>Home About</nav>
      <article>
        <h1>Long story</h1>
        <p>"""
        + ("Body sentence about Astra and Perplexity. " * 20)
        + """</p>
      </article>
      <footer>copyright</footer>
    </body></html>
    """
    )
    body = extract_page_body(html, max_chars=8000)
    assert body is not None
    assert "Astra and Perplexity" in body
    assert "Short OG only" not in body
    assert len(body) > len("Short OG only.")
    snippet = extract_page_snippet(html)
    assert snippet == "Short OG only."


def test_extract_page_body_falls_back_when_no_article() -> None:
    html = (
        "<html><body><p>"
        + ("Plain page text without article tags. " * 15)
        + "</p></body></html>"
    )
    body = extract_page_body(html, max_chars=500)
    assert body is not None
    assert "Plain page text" in body


def test_fetch_page_snippet_uses_client_html() -> None:
    html = (
        '<html><head><meta property="og:description" '
        'content="Fetched OG blurb from page."></head></html>'
    )
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.raise_for_status = MagicMock()
    response.headers = {"content-type": "text/html; charset=utf-8"}
    response.charset_encoding = "utf-8"
    response.iter_bytes = MagicMock(return_value=[html.encode("utf-8")])

    client = MagicMock(spec=httpx.Client)
    client.stream = MagicMock(return_value=response)

    assert fetch_page_snippet(client, "https://example.com/a") == (
        "Fetched OG blurb from page."
    )


def test_summarize_item_no_snippet_skips_llm() -> None:
    item = HotItem(
        source="hn",
        title="Only a title",
        url="https://example.com/x",
        reason="test",
        summary=None,
    )
    runtime = LlmRuntime(
        provider="ollama",
        model="dummy",
        base_url="http://127.0.0.1:11434",
        timeout_seconds=1,
        api_key="",
    )
    with patch("src.ollama_client.llm_chat") as chat:
        out = summarize_item(item, runtime)
    assert out == ""
    chat.assert_not_called()


def test_attach_hn_fills_from_page_when_empty() -> None:
    item = HotItem(
        source="hn",
        title="Story",
        url="https://example.com/story",
        reason="test",
    )
    client = MagicMock(spec=httpx.Client)
    with patch(
        "src.pipeline.fetch_page_snippet",
        return_value="Grounded page description for the story.",
    ) as fetch:
        out = _attach_hn_page_snippets([item], client, max_chars=280)
    fetch.assert_called_once()
    assert out[0].summary == "Grounded page description for the story."


def test_attach_hn_skips_fetch_when_ask_text_usable() -> None:
    long = (
        "Ask HN: looking for tools that evaluate agent traces across "
        "multi-step workflows without vendor lock-in for small teams."
    )
    item = HotItem(
        source="hn",
        title="Ask HN: agent eval tools",
        url="https://news.ycombinator.com/item?id=1",
        reason="test",
        summary=long,
    )
    client = MagicMock(spec=httpx.Client)
    with patch("src.pipeline.fetch_page_snippet") as fetch:
        out = _attach_hn_page_snippets([item], client)
    fetch.assert_not_called()
    assert out[0].summary == long


def test_enrich_hn_with_snippet_calls_llm() -> None:
    item = HotItem(
        source="hn",
        title="Shopify native",
        url="https://example.com/s",
        reason="test",
        summary="Shopify is moving mobile apps from React Native back to Swift.",
    )
    llm = MagicMock()
    with patch(
        "src.pipeline.summarize_item",
        return_value="Shopify is dropping React Native for Swift and Kotlin.",
    ) as summarize:
        out = _enrich_with_llm([item], llm)
    summarize.assert_called_once()
    assert "Swift" in (out[0].summary or "")


def test_enrich_keeps_empty_when_summarize_blank() -> None:
    item = HotItem(
        source="hn",
        title="No page",
        url="https://example.com/none",
        reason="test",
        summary=None,
    )
    llm = MagicMock()
    with patch("src.pipeline.summarize_item", return_value=""):
        out = _enrich_with_llm([item], llm)
    assert out[0].summary is None
