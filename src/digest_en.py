"""把 digest.md 中残留中文 title/summary 译成英文。"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.config import load_app_config, settings
from src.digest import load_hot_items, write_digest
from src.llm import build_llm_runtime
from src.models import AppConfig, HotItem, LlmRuntime, OllamaConfig
from src.ollama_client import translate_item_to_english
from src.textutil import contains_cjk

logger = logging.getLogger(__name__)


def needs_english_fields(item: HotItem) -> bool:
    """title 或 summary 含汉字则需要英文化。"""
    if contains_cjk(item.title):
        return True
    if item.summary and contains_cjk(item.summary):
        return True
    return False


def translate_cjk_fields_to_english(
    items: list[HotItem], llm: LlmRuntime | OllamaConfig
) -> list[HotItem]:
    """仅翻译含汉字的条目；失败则保留原文并打 warning。"""
    out: list[HotItem] = []
    for item in items:
        if not needs_english_fields(item):
            out.append(item)
            continue
        try:
            title_en, summary_en = translate_item_to_english(item, llm)
            updates: dict[str, str | None] = {"title": title_en}
            if summary_en is not None:
                updates["summary"] = summary_en
            out.append(item.model_copy(update=updates))
        except Exception as exc:
            logger.warning("llm to-en failed source=%s err=%s", item.source, exc)
            out.append(item)
    return out


def rewrite_digest_english(config: AppConfig) -> tuple[Path, int]:
    """重写 digest.md：残留中文条目译成英文。返回 (path, 尝试翻译的条数)。"""
    path = Path(config.paths.digest_path)
    _, items = load_hot_items(path)
    if not items and not path.is_file():
        raise FileNotFoundError(f"digest not found: {path}")

    runtime = build_llm_runtime(config, api_key=settings.openrouter_api_key)
    to_fix = sum(1 for item in items if needs_english_fields(item))
    translated = translate_cjk_fields_to_english(items, runtime)
    now = datetime.now(timezone.utc)
    write_digest(path, translated, generated_at=now)
    remaining = sum(1 for item in translated if needs_english_fields(item))
    logger.info(
        "digest_en path=%s candidates=%s remaining_cjk=%s provider=%s model=%s",
        path,
        to_fix,
        remaining,
        runtime.provider,
        runtime.model,
    )
    return path, to_fix


def main() -> int:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_app_config()
    path, n = rewrite_digest_english(config)
    runtime = build_llm_runtime(config, api_key=settings.openrouter_api_key)
    print(
        f"[ai_hot] digest_en → {path} (tried={n}, "
        f"provider={runtime.provider}, model={runtime.model}); "
        "re-run: python -m src.translate && python -m src.publish"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
