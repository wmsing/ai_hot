"""跨源热度打分与 URL/标题簇合并。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from src.models import HotItem, HotTopicsConfig
from src.normalize import normalize_url, title_key


def source_family(source: str) -> str:
    """reddit:foo → reddit；google_news:ai_en → google_news。"""
    if ":" in source:
        return source.split(":", 1)[0]
    return source


def sort_source_families(families: set[str], cfg: HotTopicsConfig) -> list[str]:
    """按 source_weights 降序，同权重按字母序。"""
    return sorted(
        families,
        key=lambda family: (-float(cfg.source_weights.get(family, 0.5)), family),
    )


def engagement(item: HotItem) -> float:
    score = float(item.score or 0)
    comments = float(item.comments or 0)
    return score + 2.0 * comments


def recency_decay(
    item: HotItem, *, now: datetime, half_life_hours: float = 12.0
) -> float:
    """越新越接近 1；无时间戳给中性 0.5。"""
    if item.published_at is None:
        return 0.5
    pub = item.published_at
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=timezone.utc)
    else:
        pub = pub.astimezone(timezone.utc)
    age_h = max((now - pub).total_seconds() / 3600.0, 0.0)
    return math.exp(-math.log(2) * age_h / half_life_hours)


def heat_score(
    item: HotItem,
    cfg: HotTopicsConfig,
    *,
    now: datetime,
    trends_hit: bool = False,
) -> float:
    family = source_family(item.source)
    weight = float(cfg.source_weights.get(family, 0.5))
    base = (
        cfg.w_engagement * math.log1p(engagement(item))
        + cfg.w_recency * recency_decay(item, now=now)
        + cfg.w_source * weight
    )
    if trends_hit:
        base += cfg.trends_boost
    return base


@dataclass
class _ClusterEntry:
    score: float
    item: HotItem
    families: set[str]


def _attach_merged_sources(
    item: HotItem, families: set[str], cfg: HotTopicsConfig
) -> HotItem:
    sources = sort_source_families(families, cfg)
    updates: dict[str, object] = {"sources": sources}
    if len(sources) >= 2:
        merged_tag = "+".join(sources)
        reason = item.reason.strip()
        marker = f"merged_sources={merged_tag}"
        if marker not in reason:
            updates["reason"] = f"{reason}; {marker}" if reason else marker
    return item.model_copy(update=updates)


def cluster_and_rank(
    items: list[HotItem],
    cfg: HotTopicsConfig,
    *,
    now: datetime | None = None,
    related_queries: set[str] | None = None,
) -> list[tuple[float, HotItem]]:
    """按规范化 URL 合并，同 URL 保留热度更高者；再按 heat 降序。"""
    clock = now or datetime.now(timezone.utc)
    related = related_queries or set()
    best: dict[str, _ClusterEntry] = {}
    for raw in items:
        key = normalize_url(raw.url) or title_key(raw.title)
        family = source_family(raw.source)
        hit = _trends_hit(raw, related)
        score = heat_score(raw, cfg, now=clock, trends_hit=hit)
        item = raw
        if hit and "trends_related" not in raw.reason:
            item = raw.model_copy(update={"reason": f"{raw.reason}; trends_related"})
        prev = best.get(key)
        if prev is None:
            best[key] = _ClusterEntry(score=score, item=item, families={family})
            continue
        families = prev.families | {family}
        if score > prev.score:
            best[key] = _ClusterEntry(score=score, item=item, families=families)
        else:
            best[key] = _ClusterEntry(
                score=prev.score, item=prev.item, families=families
            )
    ranked = sorted(best.values(), key=lambda entry: entry.score, reverse=True)
    out: list[tuple[float, HotItem]] = []
    for entry in ranked[: cfg.top_n]:
        merged = _attach_merged_sources(entry.item, entry.families, cfg)
        out.append((entry.score, merged))
    return out


def _trends_hit(item: HotItem, related: set[str]) -> bool:
    if not related:
        return False
    blob = f"{item.title}\n{item.summary or ''}".casefold()
    return any(q in blob for q in related)
