"""把 out/digest.md 译成中文 → out/digest.zh.md。"""

from __future__ import annotations

import argparse
import logging
import sys

from src.config import load_app_config, settings
from src.llm import build_llm_runtime, resolve_provider
from src.ollama_translate import translate_digest_file


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Translate digest.md → digest.zh.md")
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Override LLM model for this run. "
            "Examples: --model inclusionai/ling-3.0-flash-vl:free | "
            "--model nvidia/nemotron-3-ultra-550b-a55b:free"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_app_config()
    out = translate_digest_file(config, model=args.model)
    provider = resolve_provider(args.model, config)
    runtime = build_llm_runtime(
        config,
        provider=provider,
        model=args.model,
        api_key=settings.openrouter_api_key,
    )
    print(
        f"[ai_hot] translated → {out} "
        f"(provider={runtime.provider}, model={runtime.model})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
