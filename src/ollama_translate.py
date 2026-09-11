"""调用 LLM，把 digest 译成中文 Markdown（按 URL 增量）。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from src.config import settings
from src.digest import (
    format_digest_markdown,
    load_hot_items,
    parse_hot_items,
    write_digest,
)
from src.llm import build_llm_runtime, resolve_provider, runtime_from_ollama
from src.models import AppConfig, HotItem, LlmRuntime, OllamaConfig
from src.ollama_client import llm_chat

logger = logging.getLogger(__name__)

_SYSTEM = """你是技术资讯翻译。将用户给出的英文 Markdown digest 译成简体中文。
硬性规则：
1. 保持 Markdown 结构（标题层级、列表、空行）不变
2. URL、代码、source 反引号内的标识、image 行的图片 URL、tag 行的值不要改
3. published 行的时间（如 2026-09-10 01:00 UTC 或旧 ISO）原样保留，不要翻译或改时区写法
4. 专有名词可保留英文（如 OpenAI、Hacker News），其余用通顺中文
5. 只输出译后的 Markdown 全文，不要前言后语"""


def translate_markdown(text: str, llm: LlmRuntime | OllamaConfig) -> str:
    runtime = llm if isinstance(llm, LlmRuntime) else runtime_from_ollama(llm)
    return llm_chat(system=_SYSTEM, user=text, llm=runtime)


def translate_digest_file(config: AppConfig, *, model: str | None = None) -> Path:
    """读英文 digest，增量写出中文版。

    已有 digest.zh.md 中同 URL 条目复用 title/summary，只翻译新增 URL。
    新增条目按 ollama.translate_batch_size 分批调用 LLM，避免大包超时。
    model 非空时覆盖 config 默认模型；含 `/` 或 `:free` 时走 openrouter。
    """
    src = Path(config.paths.digest_path)
    dst = Path(config.paths.digest_zh_path)
    if not src.is_file():
        raise FileNotFoundError(f"missing {src}; run `python -m src.main` first")

    generated_at, en_items = load_hot_items(src)
    if not en_items and not src.read_text(encoding="utf-8").strip():
        raise ValueError(f"digest is empty: {src}")
    if generated_at is None:
        generated_at = datetime.now(timezone.utc)

    _, zh_items = load_hot_items(dst)
    zh_by_url = {item.url: item for item in zh_items if item.url.strip()}

    need: list[HotItem] = []
    for item in en_items:
        prev = zh_by_url.get(item.url)
        if prev is None or not _usable_zh(prev):
            need.append(item)

    provider = resolve_provider(model, config)
    runtime = build_llm_runtime(
        config,
        provider=provider,
        model=model,
        api_key=settings.openrouter_api_key,
    )
    batch_size = max(1, int(config.ollama.translate_batch_size))
    logger.info(
        "translating digest provider=%s model=%s en=%s reuse=%s new=%s batch=%s",
        runtime.provider,
        runtime.model,
        len(en_items),
        len(en_items) - len(need),
        len(need),
        batch_size,
    )

    translated_by_url: dict[str, HotItem] = {}
    if need:
        total_batches = (len(need) + batch_size - 1) // batch_size
        for batch_i, start in enumerate(range(0, len(need), batch_size), start=1):
            batch = need[start : start + batch_size]
            logger.info(
                "translate batch %s/%s size=%s",
                batch_i,
                total_batches,
                len(batch),
            )
            english_chunk = format_digest_markdown(batch, generated_at=generated_at)
            chinese_chunk = translate_markdown(english_chunk, runtime)
            _, translated_items = parse_hot_items(chinese_chunk)
            translated_by_url.update(_align_translated(batch, translated_items))

    final: list[HotItem] = []
    for item in en_items:
        if item.url in translated_by_url:
            final.append(translated_by_url[item.url])
            continue
        prev = zh_by_url.get(item.url)
        if prev is not None and _usable_zh(prev):
            final.append(
                item.model_copy(
                    update={
                        "title": prev.title,
                        "summary": prev.summary,
                    }
                )
            )
        else:
            final.append(item)

    write_digest(dst, final, generated_at=generated_at)
    logger.info("wrote %s (items=%s)", dst, len(final))
    return dst


def _usable_zh(item: HotItem) -> bool:
    return bool(item.title.strip())


def _align_translated(
    need: list[HotItem],
    translated: list[HotItem],
) -> dict[str, HotItem]:
    """按 URL 对齐；URL 丢失时按 need 顺序回退。"""
    by_url = {item.url: item for item in translated if item.url.strip()}
    out: dict[str, HotItem] = {}
    for index, item in enumerate(need):
        hit = by_url.get(item.url)
        if hit is None and index < len(translated):
            hit = translated[index]
        if hit is None:
            out[item.url] = item
            continue
        out[item.url] = item.model_copy(
            update={
                "title": hit.title.strip() or item.title,
                "summary": hit.summary if hit.summary else item.summary,
            }
        )
    return out
