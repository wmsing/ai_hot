"""Admin 拉取：probe 热搜 + 巡检 digest + 归档到 content/。"""

from __future__ import annotations

from pathlib import Path

from src.hot_topics_probe import run_probe, save_hot_topics_snapshot
from src.llm import resolve_llm_model, resolve_provider
from src.models import AppConfig
from src.pipeline import run_once
from src.publish import archive_digests


def run_pull_data(
    config: AppConfig,
    *,
    llm_flag: str | None = None,
) -> dict[str, object]:
    """从网络拉取热搜与 digest，并归档到 content/（覆盖当日 digest 文件）。"""
    hot_path = Path(config.paths.hot_topics_path)
    ranked = run_probe(config)
    save_hot_topics_snapshot(hot_path, ranked)

    provider = resolve_provider(llm_flag, config)
    llm_model = (
        resolve_llm_model(llm_flag, config, provider=provider) if llm_flag else None
    )
    items = run_once(config, llm_flag=llm_flag, llm_model=llm_model)

    archived = archive_digests(
        digest_en=Path(config.paths.digest_path),
        digest_zh=Path(config.paths.digest_zh_path),
        content_dir=Path(config.paths.content_digests_dir),
    )
    return {
        "hot_topics_count": len(ranked),
        "hot_topics_path": str(hot_path),
        "digest_selected": len(items),
        "digest_path": config.paths.digest_path,
        "archived": [str(path) for path in archived],
    }
