"""重写 digest.md 中 junk / 低质英文简介（强制 LLM 再试）。"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.config import load_app_config, settings
from src.digest import load_hot_items, write_digest
from src.llm import build_llm_runtime, resolve_llm_model, resolve_provider
from src.models import AppConfig, HotItem
from src.ollama_client import is_junk_summary
from src.pipeline import _enrich_with_llm

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Force-resummarize junk or selected digest items"
    )
    parser.add_argument(
        "--input",
        default=None,
        help="Digest markdown path (default: paths.digest_path)",
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="Only resummarize this URL (repeatable); default = all junk summaries",
    )
    parser.add_argument(
        "--llm",
        default=None,
        help="Provider/model hint (default: config llm; e.g. openrouter)",
    )
    parser.add_argument(
        "--all-hn",
        action="store_true",
        help="Also force-resummarize every HN item (not only junk)",
    )
    return parser.parse_args(argv)


def _needs_resummarize(
    item: HotItem,
    *,
    urls: set[str],
    all_hn: bool,
) -> bool:
    if urls:
        return item.url.strip() in urls
    summary = (item.summary or "").strip()
    if is_junk_summary(summary, title=item.title):
        return True
    if all_hn and item.source == "hn" and summary:
        return True
    return False


def resummarize_digest(
    config: AppConfig,
    *,
    input_path: str | Path | None = None,
    urls: list[str] | None = None,
    llm_flag: str | None = None,
    all_hn: bool = False,
) -> tuple[Path, int]:
    """重写 junk 简介；返回 (digest_path, rewritten_count)。"""
    path = Path(input_path) if input_path else Path(config.paths.digest_path)
    generated_at, items = load_hot_items(path)
    if generated_at is None:
        generated_at = datetime.now(timezone.utc)
    url_set = {u.strip() for u in (urls or []) if u.strip()}
    targets = [
        item for item in items if _needs_resummarize(item, urls=url_set, all_hn=all_hn)
    ]
    if not targets:
        logger.info("resummarize: nothing to do path=%s", path)
        return path, 0

    provider = resolve_provider(llm_flag, config)
    model = resolve_llm_model(llm_flag, config, provider=provider) if llm_flag else None
    runtime = build_llm_runtime(
        config,
        provider=provider,
        model=model,
        api_key=settings.openrouter_api_key,
    )
    logger.info(
        "resummarize path=%s candidates=%s provider=%s model=%s",
        path,
        len(targets),
        runtime.provider,
        runtime.model,
    )
    rewritten = _enrich_with_llm(targets, runtime)
    by_url = {item.url: item for item in rewritten}
    final: list[HotItem] = []
    changed = 0
    for item in items:
        hit = by_url.get(item.url)
        if hit is None:
            final.append(item)
            continue
        if (hit.summary or "") != (item.summary or ""):
            changed += 1
        final.append(hit)
    write_digest(path, final, generated_at=generated_at)
    logger.info("resummarize wrote %s changed=%s", path, changed)
    return path, changed


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_app_config()
    path, n = resummarize_digest(
        config,
        input_path=args.input,
        urls=args.url,
        llm_flag=args.llm,
        all_hn=args.all_hn,
    )
    print(f"[ai_hot] resummarized {n} item(s) → {path}")
    if n:
        print("[ai_hot] next: python -m src.translate  # refresh ZH for changed URLs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
