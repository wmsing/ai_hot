"""本地 Ollama /api/chat 封装。"""

from __future__ import annotations

import logging

import httpx

from src.models import HotItem, OllamaConfig

logger = logging.getLogger(__name__)


def ollama_chat(
    *,
    system: str,
    user: str,
    ollama: OllamaConfig,
) -> str:
    """调用 Ollama chat，返回 assistant content。"""
    url = f"{ollama.base_url.rstrip('/')}/api/chat"
    payload = {
        "model": ollama.model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    with httpx.Client(timeout=ollama.timeout_seconds) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    message = data.get("message") or {}
    content = str(message.get("content") or "").strip()
    if not content:
        raise RuntimeError("ollama returned empty content")
    return content


_SUMMARY_SYSTEM = """You write one-sentence English blurbs for tech news digests.
Rules:
1. Output exactly one or two short sentences in English
2. No markdown, no quotes, no prefix like Summary:
3. Focus on what happened / why it matters
4. If context is thin, infer cautiously from the title only"""


def summarize_item(item: HotItem, ollama: OllamaConfig) -> str:
    """用 LLM 为单条热点生成英文简介。"""
    hint = item.summary or ""
    published = item.published_at.isoformat() if item.published_at else "(unknown)"
    user = (
        f"Title: {item.title}\n"
        f"URL: {item.url}\n"
        f"Source: {item.source}\n"
        f"Published: {published}\n"
        f"Existing snippet: {hint or '(none)'}\n"
    )
    logger.info("llm summarize source=%s title=%s", item.source, item.title[:60])
    return ollama_chat(system=_SUMMARY_SYSTEM, user=user, ollama=ollama)


_TO_EN_SYSTEM = """You translate Chinese AI/tech news fields into English for a digest.
Rules:
1. Output exactly two lines in this format (no other text):
TITLE: <English title>
SUMMARY: <English summary; one or two short sentences; use n/a if input summary empty>
2. Keep product names (MiniMax, OpenAI, etc.) recognizable
3. No markdown, no quotes around the whole line"""


def translate_item_to_english(
    item: HotItem, ollama: OllamaConfig
) -> tuple[str, str | None]:
    """把条目 title/summary 译成英文，返回 (title, summary)。"""
    summary_in = item.summary.strip() if item.summary else ""
    user = (
        f"Title: {item.title}\n"
        f"Summary: {summary_in or '(none)'}\n"
        f"Source: {item.source}\n"
    )
    logger.info("llm to-en source=%s title=%s", item.source, item.title[:60])
    raw = ollama_chat(system=_TO_EN_SYSTEM, user=user, ollama=ollama)
    title_out, summary_out = _parse_title_summary(raw)
    if not title_out:
        raise RuntimeError(f"ollama to-en missing TITLE: {raw[:120]!r}")
    if not summary_in:
        return title_out, None
    cleaned = summary_out.strip()
    if cleaned.lower() in {"", "n/a", "(none)", "none"}:
        raise RuntimeError(f"ollama to-en missing SUMMARY: {raw[:120]!r}")
    return title_out, cleaned


def _parse_title_summary(raw: str) -> tuple[str, str]:
    title = ""
    summary = ""
    for line in raw.splitlines():
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("TITLE:"):
            title = stripped.split(":", 1)[1].strip()
        elif upper.startswith("SUMMARY:"):
            summary = stripped.split(":", 1)[1].strip()
    return title, summary
