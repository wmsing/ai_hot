"""ADHD 摘要生成服务。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from src.config import load_app_config
from src.deep_summarize import (
    AdhdLang,
    deep_summarize_digest,
    deep_summarize_hot_topics,
)
from src.models import AppConfig


def generate_hot_topic_adhd(
    config: AppConfig,
    *,
    url: str,
    force: bool = False,
    llm_flag: str | None = None,
    lang: AdhdLang = "both",
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, object]:
    path, changed = deep_summarize_hot_topics(
        config,
        snapshot_path=config.paths.hot_topics_path,
        urls=[url],
        llm_flag=llm_flag,
        force=force,
        lang=lang,
        should_stop=should_stop,
    )
    return {"path": str(path), "changed": changed, "url": url, "lang": lang}


def generate_all_hot_topic_adhd(
    config: AppConfig,
    *,
    force: bool = False,
    llm_flag: str | None = None,
    lang: AdhdLang = "both",
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, object]:
    """对快照里全部待处理条目写 ADHD 摘要（top_n=0 → 不截断；逐条 LLM）。"""
    path, changed = deep_summarize_hot_topics(
        config,
        snapshot_path=config.paths.hot_topics_path,
        urls=None,
        llm_flag=llm_flag,
        force=force,
        lang=lang,
        top_n=0,
        should_stop=should_stop,
    )
    return {"path": str(path), "changed": changed, "lang": lang}


def generate_digest_adhd(
    config: AppConfig,
    *,
    day: date,
    url: str,
    llm_flag: str | None = None,
) -> dict[str, object]:
    content_dir = Path(config.paths.content_digests_dir)
    en_path = content_dir / f"{day.isoformat()}.en.md"
    zh_path = content_dir / f"{day.isoformat()}.zh.md"
    en_out, zh_out, changed = deep_summarize_digest(
        config,
        urls=[url],
        input_path=en_path,
        input_zh_path=zh_path,
        llm_flag=llm_flag,
    )
    return {
        "en_path": str(en_out),
        "zh_path": str(zh_out),
        "changed": changed,
        "url": url,
        "day": day.isoformat(),
    }


def run_site_build() -> dict[str, object]:
    from src.site_build import build_site_from_content

    config = load_app_config()
    output_dir = build_site_from_content(config)
    return {"ok": True, "output_dir": str(output_dir)}
