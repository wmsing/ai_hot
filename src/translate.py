"""把 out/digest.md 译成中文 → out/digest.zh.md（本地 Ollama）。"""

from __future__ import annotations

import logging
import sys

from src.config import load_app_config, settings
from src.ollama_translate import translate_digest_file


def main() -> int:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_app_config()
    out = translate_digest_file(config)
    print(f"[ai_hot] translated → {out} (model={config.ollama.model})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
