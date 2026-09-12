"""巡检流水线：抓取 → 过滤去重 →（可选 LLM 简介）→ 落库 → digest。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from src.config import settings
from src.digest import load_hot_items, merge_by_url, same_utc_day, write_digest
from src.digest_en import translate_cjk_fields_to_english
from src.fetch_page import fetch_page_snippet
from src.http_client import build_client
from src.keywords import matched_keyword, passes_keywords
from src.llm import build_llm_runtime, resolve_llm_model, resolve_provider
from src.models import AppConfig, FeedConfig, HotItem, LlmRuntime
from src.ollama_client import (
    is_junk_summary,
    is_usable_source_summary,
    summarize_item,
)
from src.sources.hn import fetch_hn_candidates
from src.sources.rss import fetch_rss_candidates
from src.storage import ItemStore
from src.textutil import truncate

logger = logging.getLogger(__name__)


def _feed_by_source(config: AppConfig, source: str) -> FeedConfig | None:
    if not source.startswith("rss:"):
        return None
    name = source.removeprefix("rss:")
    for feed in config.rss.feeds:
        if feed.name == name:
            return feed
    return None


def run_once(
    config: AppConfig,
    *,
    llm_flag: str | None = None,
    llm_model: str | None = None,
) -> list[HotItem]:
    """执行一次巡检，返回当日累计 digest 条目。

    llm_model 为 None → 模式 A（RSS/AskHN 原生简介）。
    有值 → 模式 B（对本轮新条目用 LLM 生成简介）。
    同 UTC 日会与已有 digest.md 按 URL 合并（旧在前、新追加）。
    llm_flag 用于解析 provider（如 openrouter）；可与 llm_model 一并传入。
    """
    now = datetime.now(timezone.utc)
    provider = resolve_provider(llm_flag, config)
    if llm_model is None and llm_flag is not None:
        llm_model = resolve_llm_model(llm_flag, config, provider=provider)
    # 模式 A 仍可能要用 LLM 做中文→英；model=None 时用 provider 默认模型
    runtime = build_llm_runtime(
        config,
        provider=provider,
        model=llm_model,
        api_key=settings.openrouter_api_key,
    )

    store = ItemStore(config.paths.sqlite_path)
    selected: list[HotItem] = []
    try:
        with build_client(config.http) as client:
            candidates: list[HotItem] = []
            candidates.extend(fetch_hn_candidates(client, config.hn))
            candidates.extend(fetch_rss_candidates(client, config.rss))

            rss_new_count: dict[str, int] = {}
            for item in candidates:
                feed = _feed_by_source(config, item.source)
                keywords = feed.keywords if feed else []
                if not passes_keywords(item, keywords):
                    continue
                hit = matched_keyword(item, keywords)
                if hit:
                    item = item.model_copy(
                        update={"reason": f"{item.reason}; kw={hit}"}
                    )

                if store.is_seen(
                    item.url,
                    item.title,
                    cooldown_hours=config.filter.cooldown_hours,
                    now=now,
                ):
                    continue
                if item.source.startswith("rss:"):
                    count = rss_new_count.get(item.source, 0)
                    if count >= config.rss.max_new_per_feed:
                        continue
                    rss_new_count[item.source] = count + 1
                selected.append(item)

            selected = _attach_hn_page_snippets(
                selected,
                client,
                max_chars=1200 if llm_model else 280,
            )

        if llm_model:
            selected = _enrich_with_llm(selected, runtime)

        # digest.md 默认英文：含汉字的 title/summary 用 LLM 译成英文
        selected = translate_cjk_fields_to_english(selected, runtime)

        for item in selected:
            store.upsert_seen(item, now=now)

        # UTC 当日累计：旧条目保留，本轮新 URL 追加
        prev_at, prev_items = load_hot_items(config.paths.digest_path)
        if prev_at is not None and same_utc_day(prev_at, now):
            selected = merge_by_url(prev_items, selected)

        write_digest(config.paths.digest_path, selected, generated_at=now)
        logger.info(
            "selected=%s llm=%s provider=%s model=%s digest=%s",
            len(selected),
            llm_model or "off",
            runtime.provider,
            runtime.model,
            config.paths.digest_path,
        )
        return selected
    finally:
        store.close()


def _attach_hn_page_snippets(
    items: list[HotItem],
    client: httpx.Client,
    *,
    max_chars: int = 280,
) -> list[HotItem]:
    """HN 无可用原生摘要时抓目标页片段；失败则保持原样（可为空）。"""
    out: list[HotItem] = []
    for item in items:
        if item.source != "hn":
            out.append(item)
            continue
        existing = (item.summary or "").strip()
        if existing and is_usable_source_summary(existing, title=item.title):
            out.append(item)
            continue
        snippet = fetch_page_snippet(client, item.url, max_chars=max_chars)
        if not snippet:
            out.append(item)
            continue
        out.append(item.model_copy(update={"summary": truncate(snippet, max_chars)}))
    return out


def _enrich_with_llm(items: list[HotItem], llm: LlmRuntime) -> list[HotItem]:
    enriched: list[HotItem] = []
    for item in items:
        existing = (item.summary or "").strip()
        # RSS 等已有可靠原生简介可跳过；junk / HN 页面片段仍交给 LLM
        if (
            item.source != "hn"
            and existing
            and is_usable_source_summary(existing, title=item.title)
        ):
            logger.info(
                "skip llm summarize; keep source summary source=%s len=%s",
                item.source,
                len(existing),
            )
            enriched.append(item)
            continue
        try:
            blurb = summarize_item(item, llm)
            if not blurb.strip():
                if existing and is_junk_summary(existing, title=item.title):
                    enriched.append(item.model_copy(update={"summary": None}))
                else:
                    enriched.append(item)
                continue
            if is_junk_summary(blurb, title=item.title):
                enriched.append(item.model_copy(update={"summary": None}))
                continue
            enriched.append(item.model_copy(update={"summary": blurb}))
        except Exception as exc:
            logger.warning("llm summarize failed source=%s err=%s", item.source, exc)
            if existing and is_junk_summary(existing, title=item.title):
                enriched.append(item.model_copy(update={"summary": None}))
            else:
                enriched.append(item)
    return enriched
