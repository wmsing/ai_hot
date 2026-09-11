"""调用 LLM，把 digest 译成中文 Markdown。"""

from __future__ import annotations

import logging
from pathlib import Path

from src.config import settings
from src.llm import build_llm_runtime, runtime_from_ollama
from src.models import AppConfig, LlmRuntime, OllamaConfig
from src.ollama_client import llm_chat

logger = logging.getLogger(__name__)

_SYSTEM = """你是技术资讯翻译。将用户给出的英文 Markdown digest 译成简体中文。
硬性规则：
1. 保持 Markdown 结构（标题层级、列表、空行）不变
2. URL、代码、source 反引号内的标识、image 行的图片 URL、tag 行的值不要改
3. published 行的时间（如 2026-09-10 01:00 UTC 或旧 ISO）原样保留，不要翻译或改时区写法
4. 专有名词可保留英文（如 OpenAI、Hacker News），其余用通顺中文
5. 只输出译后的 Markdown 全文，不要前言后语"""


def translate_markdown(text: str, llm: LlmRuntime | OllamaConfig) -> str:
    runtime = llm if isinstance(llm, LlmRuntime) else runtime_from_ollama(llm)
    return llm_chat(system=_SYSTEM, user=text, llm=runtime)


def translate_digest_file(config: AppConfig) -> Path:
    """读英文 digest，写出中文版路径。"""
    src = Path(config.paths.digest_path)
    dst = Path(config.paths.digest_zh_path)
    if not src.is_file():
        raise FileNotFoundError(f"missing {src}; run `python -m src.main` first")
    english = src.read_text(encoding="utf-8")
    if not english.strip():
        raise ValueError(f"digest is empty: {src}")
    runtime = build_llm_runtime(config, api_key=settings.openrouter_api_key)
    logger.info(
        "translating digest provider=%s model=%s chars=%s",
        runtime.provider,
        runtime.model,
        len(english),
    )
    chinese = translate_markdown(english, runtime)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(chinese + "\n", encoding="utf-8")
    logger.info("wrote %s", dst)
    return dst
