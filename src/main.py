"""ai_hot 入口：手动跑通一次巡检。"""

from __future__ import annotations

import argparse
import logging
import sys

from src.config import load_app_config, settings
from src.pipeline import resolve_llm_model, run_once


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ai_hot hotspot scan")
    parser.add_argument(
        "--llm",
        nargs="?",
        const="qwen",
        default=None,
        help="Enable LLM summaries (mode B). Example: --llm qwen",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_app_config()
    llm_model = resolve_llm_model(args.llm, config.ollama.model)
    selected = run_once(config, llm_model=llm_model)
    mode = f"llm={llm_model}" if llm_model else "llm=off(A)"
    print(
        f"[ai_hot] env={settings.app_env} selected={len(selected)} "
        f"{mode} digest={config.paths.digest_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
