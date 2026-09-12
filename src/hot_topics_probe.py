"""AI 热门话题 probe：HN + Reddit + Google News +（可选）Trends/Threads。"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.config import load_app_config, settings
from src.hot_score import cluster_and_rank
from src.http_client import build_client
from src.models import AppConfig, HotItem, HotTopicSnapshot, HotTopicSnapshotItem
from src.normalize import normalize_url
from src.sources.google_news import fetch_google_news_candidates
from src.sources.hn import fetch_hn_candidates
from src.sources.reddit import fetch_reddit_candidates
from src.sources.threads import fetch_threads_candidates
from src.sources.trends import collect_related_query_set, fetch_trends_daily_candidates
from src.timeutil import format_published

logger = logging.getLogger(__name__)


def collect_hot_topic_candidates(
    client: object,
    config: AppConfig,
    *,
    include_trends: bool = True,
    include_threads: bool = True,
) -> list[HotItem]:
    """拉取各源候选（不做 SQLite 去重）。"""
    import httpx

    assert isinstance(client, httpx.Client)
    items: list[HotItem] = []
    items.extend(fetch_hn_candidates(client, config.hn))
    items.extend(fetch_reddit_candidates(client, config.reddit))
    items.extend(fetch_google_news_candidates(client, config.google_news))
    if include_trends:
        items.extend(fetch_trends_daily_candidates(client, config.trends))
    if include_threads:
        items.extend(
            fetch_threads_candidates(
                client,
                config.threads,
                access_token=settings.threads_access_token,
            )
        )
    return items


def run_probe(
    config: AppConfig,
    *,
    top_n: int | None = None,
    include_trends: bool = True,
    include_threads: bool = True,
) -> list[tuple[float, HotItem]]:
    """跨源打分，返回 (heat, item) 列表。"""
    now = datetime.now(timezone.utc)
    hot_cfg = config.hot_topics.model_copy(
        update={"top_n": top_n} if top_n is not None else {}
    )
    with build_client(config.http) as client:
        candidates = collect_hot_topic_candidates(
            client,
            config,
            include_trends=include_trends,
            include_threads=include_threads,
        )
        related: set[str] = set()
        if include_trends and config.trends.enabled:
            related = collect_related_query_set(client, config.trends)
        return cluster_and_rank(
            candidates,
            hot_cfg,
            now=now,
            related_queries=related,
        )


def ranked_to_snapshot(ranked: list[tuple[float, HotItem]]) -> HotTopicSnapshot:
    items = [
        HotTopicSnapshotItem(
            heat=round(heat, 4),
            source=item.source,
            sources=item.sources,
            title=item.title,
            url=item.url,
            score=item.score,
            comments=item.comments,
            summary=item.summary,
            published_at=item.published_at,
            reason=item.reason,
        )
        for heat, item in ranked
    ]
    return HotTopicSnapshot(generated_at=datetime.now(timezone.utc), items=items)


def save_hot_topics_snapshot(path: Path, ranked: list[tuple[float, HotItem]]) -> None:
    snapshot = ranked_to_snapshot(ranked)
    prev = load_hot_topics_snapshot(path)
    if prev is not None and prev.items:
        by_url = {
            normalize_url(item.url): item
            for item in prev.items
            if item.url.strip()
        }
        merged: list[HotTopicSnapshotItem] = []
        for item in snapshot.items:
            old = by_url.get(normalize_url(item.url))
            if old is None:
                merged.append(item)
                continue
            merged.append(
                item.model_copy(
                    update={
                        "summary_en": old.summary_en,
                        "summary_zh": old.summary_zh,
                        "summary": old.summary_zh or old.summary or item.summary,
                        "title_zh": old.title_zh or item.title_zh,
                    }
                )
            )
        snapshot = snapshot.model_copy(update={"items": merged})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        snapshot.model_dump_json(indent=2),
        encoding="utf-8",
    )


def load_hot_topics_snapshot(path: Path) -> HotTopicSnapshot | None:
    if not path.is_file():
        return None
    try:
        return HotTopicSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        logger.warning("hot topics snapshot invalid path=%s err=%s", path, exc)
        return None


def format_probe_text(ranked: list[tuple[float, HotItem]]) -> str:
    lines = [
        f"# AI Hot Topics Probe ({datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)",
        "",
    ]
    for idx, (heat, item) in enumerate(ranked, start=1):
        lines.append(
            f"{idx}. [{heat:.2f}] {item.title}\n"
            f"   source={item.source} score={item.score} "
            f"comments={item.comments} "
            f"published={format_published(item.published_at)}\n"
            f"   {item.url}\n"
            f"   reason={item.reason}"
        )
    return "\n".join(lines) + ("\n" if ranked else "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe hottest AI topics (free sources)"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="config.yaml path (default: AI_HOT_CONFIG or ./config.yaml)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=None,
        help="Top N (default hot_topics.top_n)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON instead of text",
    )
    parser.add_argument(
        "--no-trends",
        action="store_true",
        help="Skip Google Trends daily + related",
    )
    parser.add_argument(
        "--no-threads",
        action="store_true",
        help="Skip Threads even if enabled + token",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Also write JSON snapshot to paths.hot_topics_path",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Write report to file",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",
    )
    config = load_app_config(args.config)
    ranked = run_probe(
        config,
        top_n=args.top,
        include_trends=not args.no_trends,
        include_threads=not args.no_threads,
    )
    if args.json:
        payload = [
            {
                "heat": round(heat, 4),
                "source": item.source,
                "sources": item.sources,
                "title": item.title,
                "url": item.url,
                "score": item.score,
                "comments": item.comments,
                "published_at": (
                    item.published_at.isoformat() if item.published_at else None
                ),
                "reason": item.reason,
            }
            for heat, item in ranked
        ]
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    else:
        text = format_probe_text(ranked)

    if args.save:
        snap_path = Path(config.paths.hot_topics_path)
        save_hot_topics_snapshot(snap_path, ranked)
        logger.info("saved snapshot %s (%s items)", snap_path, len(ranked))

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        logger.info("wrote %s (%s items)", args.output, len(ranked))
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
