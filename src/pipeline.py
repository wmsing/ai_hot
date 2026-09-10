"""巡检流水线：抓取 → 过滤去重 →（可选 LLM 简介）→ 落库 → digest。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.digest import load_hot_items, merge_by_url, same_utc_day, write_digest
from src.digest_en import translate_cjk_fields_to_english
from src.http_client import build_client
from src.keywords import matched_keyword, passes_keywords
from src.models import AppConfig, FeedConfig, HotItem, OllamaConfig
from src.ollama_client import summarize_item
from src.sources.hn import fetch_hn_candidates
from src.sources.rss import fetch_rss_candidates
from src.storage import ItemStore

logger = logging.getLogger(__name__)


def resolve_llm_model(flag: str | None, default_model: str) -> str | None:
    """解析 --llm：None=模式A；qwen/空=用默认模型；其它=显式模型名。"""
    if flag is None:
        return None
    normalized = flag.strip().lower()
    if normalized in {"", "qwen", "1", "true", "yes", "on"}:
        return default_model
    return flag.strip()


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
    llm_model: str | None = None,
) -> list[HotItem]:
    """执行一次巡检，返回当日累计 digest 条目。

    llm_model 为 None → 模式 A（RSS/AskHN 原生简介）。
    有值 → 模式 B（对本轮新条目用 Ollama 生成简介）。
    同 UTC 日会与已有 digest.md 按 URL 合并（旧在前、新追加）。
    """
    now = datetime.now(timezone.utc)
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
                item = item.model_copy(update={"reason": f"{item.reason}; kw={hit}"})

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

        if llm_model:
            ollama = config.ollama.model_copy(update={"model": llm_model})
            selected = _enrich_with_llm(selected, ollama)

        # digest.md 默认英文：含汉字的 title/summary 用 Ollama 译成英文
        selected = translate_cjk_fields_to_english(selected, config.ollama)

        for item in selected:
            store.upsert_seen(item, now=now)

        # UTC 当日累计：旧条目保留，本轮新 URL 追加
        prev_at, prev_items = load_hot_items(config.paths.digest_path)
        if prev_at is not None and same_utc_day(prev_at, now):
            selected = merge_by_url(prev_items, selected)

        write_digest(config.paths.digest_path, selected, generated_at=now)
        logger.info(
            "selected=%s llm=%s digest=%s",
            len(selected),
            llm_model or "off",
            config.paths.digest_path,
        )
        return selected
    finally:
        store.close()


def _enrich_with_llm(items: list[HotItem], ollama: OllamaConfig) -> list[HotItem]:
    enriched: list[HotItem] = []
    for item in items:
        try:
            blurb = summarize_item(item, ollama)
            enriched.append(item.model_copy(update={"summary": blurb}))
        except Exception as exc:
            logger.warning("llm summarize failed source=%s err=%s", item.source, exc)
            enriched.append(item)
    return enriched
