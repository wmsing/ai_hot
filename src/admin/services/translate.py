"""Admin 翻译服务。"""

from __future__ import annotations

from collections.abc import Callable

from src.deep_summarize import translate_hot_topic_titles
from src.models import AppConfig


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
