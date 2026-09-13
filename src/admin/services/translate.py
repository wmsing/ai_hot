"""Admin 翻译服务。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from src.config import settings
from src.deep_summarize import (
    translate_hot_topic_titles,
    translate_summary_to_zh,
    translate_title_to_zh,
)
from src.llm import build_llm_runtime, resolve_llm_model, resolve_provider
from src.models import AppConfig
from src.ollama_client import llm_chat
from src.textutil import contains_cjk


def translate_all_hot_topic_titles(
    config: AppConfig,
    *,
    urls: list[str] | None = None,
    force: bool = False,
    llm_flag: str | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, object]:
    path, changed = translate_hot_topic_titles(
        config,
        snapshot_path=config.paths.hot_topics_path,
        urls=urls,
        force=force,
        llm_flag=llm_flag,
        should_stop=should_stop,
    )
    return {"path": str(path), "changed": changed}


def translate_digest_day_titles(
    config: AppConfig,
    *,
    day: date,
    indices: list[int] | None = None,
    force: bool = False,
    llm_flag: str | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, object]:
    from src.admin.stores import digest as digest_store

    content_dir = Path(config.paths.content_digests_dir)
    view = digest_store.get_day(content_dir, day)
    index_filter = {idx for idx in (indices or []) if idx > 0}
    provider = resolve_provider(llm_flag, config)
    model = resolve_llm_model(llm_flag, config, provider=provider) if llm_flag else None
    llm = build_llm_runtime(
        config,
        provider=provider,
        model=model,
        api_key=settings.openrouter_api_key,
    )
    changed = 0
    for item in view.items:
        if should_stop and should_stop():
            break
        if index_filter and item.index not in index_filter:
            continue
        if not force and item.title_zh.strip() and contains_cjk(item.title_zh):
            continue
        source_title = item.title_en.strip()
        if not source_title:
            continue
        title_zh = translate_title_to_zh(source_title, llm, chat=llm_chat)
        if not title_zh:
            continue
        digest_store.update_item(
            content_dir,
            day,
            item.index,
            title_zh=title_zh,
        )
        changed += 1
    return {"day": day.isoformat(), "changed": changed}


def translate_digest_day_summaries(
    config: AppConfig,
    *,
    day: date,
    indices: list[int] | None = None,
    force: bool = False,
    llm_flag: str | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, object]:
    from src.admin.stores import digest as digest_store

    content_dir = Path(config.paths.content_digests_dir)
    view = digest_store.get_day(content_dir, day)
    index_filter = {idx for idx in (indices or []) if idx > 0}
    provider = resolve_provider(llm_flag, config)
    model = resolve_llm_model(llm_flag, config, provider=provider) if llm_flag else None
    llm = build_llm_runtime(
        config,
        provider=provider,
        model=model,
        api_key=settings.openrouter_api_key,
    )
    changed = 0
    for item in view.items:
        if should_stop and should_stop():
            break
        if index_filter and item.index not in index_filter:
            continue
        if not force and item.summary_zh.strip() and contains_cjk(item.summary_zh):
            continue
        source_summary = item.summary_en.strip()
        if not source_summary:
            continue
        summary_zh = translate_summary_to_zh(source_summary, llm, chat=llm_chat)
        if not summary_zh:
            continue
        digest_store.update_item(
            content_dir,
            day,
            item.index,
            summary_zh=summary_zh,
        )
        changed += 1
    return {"day": day.isoformat(), "changed": changed}
