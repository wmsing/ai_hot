"""ai_hot 入口：手动跑通一次巡检。"""

from __future__ import annotations

import argparse
import logging
import sys

from src.config import load_app_config, settings
from src.llm import resolve_llm_model, resolve_provider
from src.ollama_translate import translate_digest_file
from src.pipeline import run_once


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ai_hot hotspot scan")
    parser.add_argument(
        "--llm",
        nargs="?",
        const="qwen",
        default=None,
        help=(
            "Enable LLM summaries (mode B). "
            "Examples: --llm qwen | --llm openrouter | --llm openrouter/free"
        ),
    )
    parser.add_argument(
        "--translate",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="After digest, translate EN → ZH (default: on when --llm is set)",
    )
    parser.add_argument(
        "--translate-model",
        default=None,
        help="Override zh translation model (default: same as --llm)",
    )
    return parser.parse_args(argv)


def should_translate(args: argparse.Namespace) -> bool:
    """有 --llm 时默认顺带译中文；可用 --no-translate 关闭。"""
    if args.translate is True:
        return True
    if args.translate is False:
        return False
    return args.llm is not None


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_app_config()
    provider = resolve_provider(args.llm, config)
    llm_model = resolve_llm_model(args.llm, config, provider=provider)
    selected = run_once(config, llm_flag=args.llm, llm_model=llm_model)
    if llm_model:
        mode = f"llm={llm_model} provider={provider}"
    else:
        mode = f"llm=off(A) provider={provider}"
    print(
        f"[ai_hot] env={settings.app_env} selected={len(selected)} "
        f"{mode} digest={config.paths.digest_path}"
    )
    if should_translate(args):
        translate_model = args.translate_model or args.llm
        zh_path = translate_digest_file(config, model=translate_model)
        tr_provider = resolve_provider(translate_model, config)
        tr_model = resolve_llm_model(translate_model, config, provider=tr_provider)
        print(
            f"[ai_hot] translated → {zh_path} "
            f"(provider={tr_provider}, model={tr_model})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
