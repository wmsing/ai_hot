"""ADHD 摘要生成服务。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from src.admin.services.speak import invalidate_digest_audio
from src.admin.stores import digest as digest_store
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
    urls: list[str] | None = None,
    force: bool = False,
    llm_flag: str | None = None,
    lang: AdhdLang = "both",
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, object]:
    """对快照条目写 ADHD 摘要；urls 为空则处理全部待处理项。"""
    path, changed = deep_summarize_hot_topics(
        config,
        snapshot_path=config.paths.hot_topics_path,
        urls=urls,
        llm_flag=llm_flag,
        force=force,
        lang=lang,
        top_n=0,
        should_stop=should_stop,
    )
    return {"path": str(path), "changed": changed, "lang": lang, "urls": urls or []}


def generate_digest_adhd_batch(
    config: AppConfig,
    *,
    day: date,
    indices: list[int],
    force: bool = False,
    llm_flag: str | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, object]:
    content_dir = Path(config.paths.content_digests_dir)
    view = digest_store.get_day(content_dir, day)
    index_set = {idx for idx in indices if idx > 0}
    urls: list[str] = []
    for item in view.items:
        if item.index not in index_set:
            continue
        url = item.url.strip()
        if not url:
            continue
        if (
            not force
            and digest_store.has_adhd_summary(item.summary_en)
            and digest_store.has_adhd_summary(item.summary_zh)
        ):
            continue
        urls.append(url)
    if not urls:
        return {"day": day.isoformat(), "changed": 0, "indices": sorted(index_set)}
    en_path = content_dir / f"{day.isoformat()}.en.md"
    zh_path = content_dir / f"{day.isoformat()}.zh.md"
    url_to_index = {item.url.strip(): item.index for item in view.items}
    changed = 0
    en_out = en_path
    zh_out = zh_path
    for url in urls:
        if should_stop and should_stop():
            break
        en_out, zh_out, n, _mode = deep_summarize_digest(
            config,
            urls=[url],
            input_path=en_path,
            input_zh_path=zh_path,
            llm_flag=llm_flag,
            should_stop=should_stop,
        )
        if not n:
            continue
        changed += n
        index = url_to_index.get(url)
        if index:
            invalidate_digest_audio(config, day=day, indices=[index])
    return {
        "en_path": str(en_out),
        "zh_path": str(zh_out),
        "changed": changed,
        "day": day.isoformat(),
        "indices": sorted(index_set),
    }


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
    en_out, zh_out, changed, write_mode = deep_summarize_digest(
        config,
        urls=[url],
        input_path=en_path,
        input_zh_path=zh_path,
        llm_flag=llm_flag,
    )
    if changed:
        view = digest_store.get_day(content_dir, day)
        indices = [item.index for item in view.items if item.url.strip() == url.strip()]
        invalidate_digest_audio(config, day=day, indices=indices)
    return {
        "en_path": str(en_out),
        "zh_path": str(zh_out),
        "changed": changed,
        "mode": write_mode,
        "url": url,
        "day": day.isoformat(),
    }


def run_site_build() -> dict[str, object]:
    from src.site_build import build_site_from_content

    config = load_app_config()
    output_dir = build_site_from_content(config)
    return {"ok": True, "output_dir": str(output_dir)}
