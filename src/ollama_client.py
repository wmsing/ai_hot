"""LLM chat：本地 Ollama 或 OpenRouter（OpenAI 兼容）。"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from src.llm import runtime_from_ollama
from src.models import HotItem, LlmRuntime, OllamaConfig

logger = logging.getLogger(__name__)


def llm_chat(
    *,
    system: str,
    user: str,
    llm: LlmRuntime,
) -> str:
    """调用当前 provider，返回 assistant content。"""
    if llm.provider == "openrouter":
        return _openrouter_chat(system=system, user=user, llm=llm)
    return _ollama_chat(system=system, user=user, llm=llm)


def ollama_chat(
    *,
    system: str,
    user: str,
    ollama: OllamaConfig,
) -> str:
    """兼容旧调用：仅 Ollama。"""
    return llm_chat(system=system, user=user, llm=runtime_from_ollama(ollama))


def _ollama_chat(*, system: str, user: str, llm: LlmRuntime) -> str:
    url = f"{llm.base_url.rstrip('/')}/api/chat"
    payload = {
        "model": llm.model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    with httpx.Client(timeout=llm.timeout_seconds) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    message = data.get("message") or {}
    content = str(message.get("content") or "").strip()
    if not content:
        raise RuntimeError("ollama returned empty content")
    return content


def _openrouter_chat(*, system: str, user: str, llm: LlmRuntime) -> str:
    if not llm.api_key:
        raise RuntimeError("OPENROUTER_API_KEY missing")
    models = [llm.model]
    fallback = (llm.fallback_model or "").strip()
    if fallback and fallback != llm.model:
        models.append(fallback)
    last_error: Exception | None = None
    for index, model in enumerate(models):
        try:
            return _openrouter_chat_once(system=system, user=user, llm=llm, model=model)
        except (RuntimeError, httpx.HTTPError) as exc:
            last_error = exc
            if index + 1 >= len(models):
                break
            logger.warning(
                "openrouter model=%s failed (%s); retry fallback=%s",
                model,
                exc,
                models[index + 1],
            )
    assert last_error is not None
    raise last_error


def _openrouter_chat_once(
    *, system: str, user: str, llm: LlmRuntime, model: str
) -> str:
    url = f"{llm.base_url.rstrip('/')}/chat/completions"
    headers: dict[str, str] = {
        "Authorization": f"Bearer {llm.api_key}",
        "Content-Type": "application/json",
    }
    if llm.http_referer:
        headers["HTTP-Referer"] = llm.http_referer
    if llm.app_title:
        headers["X-Title"] = llm.app_title
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    with httpx.Client(timeout=llm.timeout_seconds) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    content = _openrouter_content(data)
    if not content:
        routed = str(data.get("model") or model)
        raise RuntimeError(f"openrouter returned empty content (model={routed})")
    return content


def _openrouter_content(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return str(message.get("content") or "").strip()


_SUMMARY_SYSTEM = """You write factual English blurbs for an AI/tech news digest.
Rules:
1. Output exactly one or two short sentences in English (≤40 words total)
2. No markdown, no quotes, no prefix like Summary:
3. Lead with who/what + concrete action or result (shipped X, raised Y, banned Z)
4. Do not restate the title verbatim; add a fact from the snippet when present
5. Ban filler: "major step", "strong contender", "growing trend", "game-changer",
   "paradigm shift", "exciting development", "this marks", "positions it as",
   "highlights the", "underscores the", "could revolutionize"
6. Use only facts present in Existing snippet—never invent from the title alone
7. If the snippet is empty, do not invent; the caller will skip you"""

_CLICHE_RE = re.compile(
    r"(?i)\b("
    r"major\s+step|strong\s+contender|growing\s+trend|game[\s-]?changer|"
    r"paradigm\s+shift|exciting\s+development|this\s+marks|positions\s+it\s+as|"
    r"highlights\s+the|underscores\s+the|could\s+revolutionize|"
    r"looks\s+set\s+to|in\s+an\s+era\s+of"
    r")\b"
)

# RSS/原生简介够长且非标题复读时，跳过 LLM 重写
_MIN_SOURCE_SUMMARY_CHARS = 80

_RETRY_NUDGE = (
    "Rewrite the blurb. Avoid marketing filler and banned phrases. "
    "Keep one or two short factual sentences only.\n\n"
)


def summary_has_cliches(text: str) -> bool:
    """简介是否含常见套话（用于硬规则校验）。"""
    return bool(_CLICHE_RE.search(text.strip()))


def is_usable_source_summary(text: str, *, title: str = "") -> bool:
    """RSS/AskHN 原生简介是否足够好，可跳过 LLM 重写。"""
    cleaned = " ".join(text.split()).strip()
    if len(cleaned) < _MIN_SOURCE_SUMMARY_CHARS:
        return False
    if title and cleaned.casefold() == title.casefold():
        return False
    return True


def summarize_item(item: HotItem, llm: LlmRuntime | OllamaConfig) -> str:
    """用 LLM 为单条热点生成英文简介；无原文片段则空串（禁止凭标题编造）。"""
    runtime = llm if isinstance(llm, LlmRuntime) else runtime_from_ollama(llm)
    hint = (item.summary or "").strip()
    if not hint:
        logger.info(
            "skip llm summarize; no source snippet source=%s title=%s",
            item.source,
            item.title[:60],
        )
        return ""
    published = item.published_at.isoformat() if item.published_at else "(unknown)"
    base_user = (
        f"Title: {item.title}\n"
        f"URL: {item.url}\n"
        f"Source: {item.source}\n"
        f"Published: {published}\n"
        f"Existing snippet: {hint}\n"
    )
    logger.info(
        "llm summarize provider=%s model=%s source=%s title=%s",
        runtime.provider,
        runtime.model,
        item.source,
        item.title[:60],
    )
    blurb = llm_chat(system=_SUMMARY_SYSTEM, user=base_user, llm=runtime).strip()
    if not summary_has_cliches(blurb):
        return blurb

    logger.info("llm summarize cliché hit; retry once title=%s", item.title[:60])
    retry = llm_chat(
        system=_SUMMARY_SYSTEM,
        user=_RETRY_NUDGE + base_user,
        llm=runtime,
    ).strip()
    if not summary_has_cliches(retry):
        return retry
    if hint:
        logger.info("llm summarize still cliché; keep source snippet")
        return hint
    return retry


_TO_EN_SYSTEM = """You translate Chinese AI/tech news fields into English for a digest.
Rules:
1. Output exactly two lines in this format (no other text):
TITLE: <English title>
SUMMARY: <English summary; one or two short sentences; use n/a if input summary empty>
2. Keep product names (MiniMax, OpenAI, etc.) recognizable
3. No markdown, no quotes around the whole line"""


def translate_item_to_english(
    item: HotItem, llm: LlmRuntime | OllamaConfig
) -> tuple[str, str | None]:
    """把条目 title/summary 译成英文，返回 (title, summary)。"""
    runtime = llm if isinstance(llm, LlmRuntime) else runtime_from_ollama(llm)
    summary_in = item.summary.strip() if item.summary else ""
    user = (
        f"Title: {item.title}\n"
        f"Summary: {summary_in or '(none)'}\n"
        f"Source: {item.source}\n"
    )
    logger.info(
        "llm to-en provider=%s model=%s source=%s title=%s",
        runtime.provider,
        runtime.model,
        item.source,
        item.title[:60],
    )
    raw = llm_chat(system=_TO_EN_SYSTEM, user=user, llm=runtime)
    title_out, summary_out = _parse_title_summary(raw)
    if not title_out:
        raise RuntimeError(f"llm to-en missing TITLE: {raw[:120]!r}")
    if not summary_in:
        return title_out, None
    cleaned = summary_out.strip()
    if cleaned.lower() in {"", "n/a", "(none)", "none"}:
        raise RuntimeError(f"llm to-en missing SUMMARY: {raw[:120]!r}")
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
