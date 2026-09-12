"""按 URL 抓全文，用本地 LLM 写 ADHD 中/英精写摘要。"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from src.config import load_app_config, settings
from src.digest import load_hot_items, write_digest
from src.fetch_page import fetch_page_body
from src.http_client import build_client
from src.llm import build_llm_runtime, resolve_llm_model, resolve_provider
from src.models import AppConfig, HotItem, LlmRuntime
from src.ollama_client import llm_chat
from src.textutil import speak_plain

FetchBodyFn = Callable[..., str | None]
ChatFn = Callable[..., str]

logger = logging.getLogger(__name__)

_ADHD_SYSTEM = """你是面向 ADHD 读者的中文科技资讯精写助手。
根据用户给出的【文章正文】写摘要，硬性规则：
1. 只根据正文事实，禁止编造正文没有的信息
2. 专有名词可保留英文（OpenAI、Perplexity、Astra 等）
3. 口语、短句、可有 emoji；结构必须如下（可换具体 emoji，但两级标题文字保留）：

⚡️ 一句话总结
（一段话，点明谁做了什么、为何重要）

🔥 核心亮点
（3–5 条，每条一行，以 emoji 开头，讲清动作/结果；不要写 TL;DR 或英文括号说明）

4. 只输出上述摘要正文，不要前言后语，不要 Markdown 代码块围栏"""

_EN_ADHD_SYSTEM = """You write ADHD-friendly English tech digests from the article body.
Hard rules:
1. Only use facts from the body; never invent
2. Short spoken sentences; emoji OK; keep this exact two-level structure
   (emoji on headings may vary, but the English labels must stay):

⚡️ One-liner
(one short paragraph: who did what and why it matters)

🔥 Key takeaways
(3–5 lines, each starts with an emoji; action/result only;
 do not write TL;DR or parenthetical English glosses)

3. Output only the digest body; no preface, no Markdown fences"""


def _normalize_adhd_summary(text: str) -> str:
    """去掉模型偶发输出的 TL;DR 英文标签。"""
    cleaned = text.replace("核心亮点 (TL;DR)", "核心亮点")
    cleaned = cleaned.replace("核心亮点(TL;DR)", "核心亮点")
    cleaned = cleaned.replace("Key takeaways (TL;DR)", "Key takeaways")
    cleaned = cleaned.replace("Key takeaways(TL;DR)", "Key takeaways")
    cleaned = cleaned.replace("(TL;DR)", "")
    return cleaned.strip()


def _normalize_url(url: str) -> str:
    """匹配用：去掉首尾空白与末尾 /（保留 https://host/ 这类根路径）。"""
    text = url.strip()
    if len(text) > 8 and text.endswith("/"):
        text = text.rstrip("/")
    return text


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Full-text ADHD EN/ZH summarize for selected digest URLs"
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        required=False,
        help="Digest item URL to deep-summarize (repeatable)",
    )
    parser.add_argument(
        "--llm",
        default=None,
        help="Provider/model hint (default: config; e.g. qwen / ollama)",
    )
    parser.add_argument(
        "--input",
        default=None,
        help="English digest path (default: paths.digest_path)",
    )
    parser.add_argument(
        "--input-zh",
        default=None,
        help="Chinese digest path (default: paths.digest_zh_path)",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=8000,
        help="Max article body chars sent to the LLM (default: 8000)",
    )
    return parser.parse_args(argv)


def deep_summarize_digest(
    config: AppConfig,
    *,
    urls: list[str],
    llm_flag: str | None = None,
    input_path: str | Path | None = None,
    input_zh_path: str | Path | None = None,
    max_chars: int = 8000,
    client: httpx.Client | None = None,
    runtime: LlmRuntime | None = None,
    fetch_body: FetchBodyFn | None = None,
    chat: ChatFn | None = None,
) -> tuple[Path, Path, int]:
    """对指定 URL 抓全文并写回 en/zh digest；返回 (en_path, zh_path, changed)。"""
    url_list = [_normalize_url(u) for u in urls if u.strip()]
    if not url_list:
        raise ValueError("at least one --url is required")

    en_path = Path(input_path) if input_path else Path(config.paths.digest_path)
    zh_path = (
        Path(input_zh_path) if input_zh_path else Path(config.paths.digest_zh_path)
    )
    generated_at, en_items = load_hot_items(en_path)
    if generated_at is None:
        generated_at = datetime.now(timezone.utc)
    if not en_items:
        raise FileNotFoundError(f"no items in {en_path}; run main first")

    en_by_url = {
        _normalize_url(item.url): item for item in en_items if item.url.strip()
    }
    missing = [u for u in url_list if u not in en_by_url]
    if missing:
        raise ValueError(
            "URL not in English digest: "
            + ", ".join(missing[:5])
            + ("…" if len(missing) > 5 else "")
        )

    _, zh_items = load_hot_items(zh_path)
    zh_by_url = {
        _normalize_url(item.url): item for item in zh_items if item.url.strip()
    }

    provider = resolve_provider(llm_flag, config)
    model = resolve_llm_model(llm_flag, config, provider=provider) if llm_flag else None
    llm = runtime or build_llm_runtime(
        config,
        provider=provider,
        model=model,
        api_key=settings.openrouter_api_key,
    )
    fetch_fn = fetch_body or fetch_page_body
    chat_fn = chat or llm_chat

    owns_client = client is None
    http = client or build_client(config.http)
    changed = 0
    en_updates: dict[str, HotItem] = {}
    zh_updates: dict[str, HotItem] = {}

    try:
        for key in url_list:
            item = en_by_url[key]
            url = item.url.strip()
            logger.info(
                "deep_summarize fetch url=%s model=%s",
                url[:120],
                llm.model,
            )
            body_raw: Any = fetch_fn(http, url, max_chars=max_chars)
            body = str(body_raw).strip() if body_raw else ""
            if not body:
                logger.warning("deep_summarize skip; no body url=%s", url[:120])
                continue

            user_payload = (
                f"Title: {item.title}\n"
                f"URL: {item.url}\n"
                f"Source: {item.source}\n\n"
                f"【文章正文】\n{body}\n"
            )
            zh_summary = _normalize_adhd_summary(
                chat_fn(system=_ADHD_SYSTEM, user=user_payload, llm=llm).strip()
            )
            if not zh_summary or "一句话总结" not in zh_summary:
                logger.warning(
                    "deep_summarize weak ADHD output url=%s; keep previous",
                    url[:120],
                )
                continue

            en_summary = _normalize_adhd_summary(
                chat_fn(
                    system=_EN_ADHD_SYSTEM,
                    user=(
                        f"Title: {item.title}\n"
                        f"URL: {item.url}\n\n"
                        f"Article body:\n{body}\n"
                    ),
                    llm=llm,
                ).strip()
            )
            if not en_summary or "One-liner" not in en_summary:
                logger.warning(
                    "deep_summarize weak EN ADHD output url=%s; keep previous EN",
                    url[:120],
                )
                en_summary = (item.summary or "").strip()

            prev_zh = zh_by_url.get(key)
            if prev_zh and prev_zh.title.strip():
                zh_title = prev_zh.title
            else:
                zh_title = item.title
            speak_zh = speak_plain(zh_summary)
            en_updates[url] = item.model_copy(
                update={
                    "summary": en_summary,
                    "speak_summary": speak_plain(en_summary) or None,
                }
            )
            zh_updates[url] = item.model_copy(
                update={
                    "title": zh_title,
                    "summary": zh_summary,
                    "speak_summary": speak_zh or None,
                }
            )
            changed += 1
    finally:
        if owns_client:
            http.close()

    if not changed:
        logger.info("deep_summarize: nothing written")
        return en_path, zh_path, 0

    final_en = [en_updates.get(item.url, item) for item in en_items]
    write_digest(en_path, final_en, generated_at=generated_at)

    final_zh: list[HotItem] = []
    for item in final_en:
        key = _normalize_url(item.url)
        if item.url in zh_updates:
            final_zh.append(zh_updates[item.url])
            continue
        prev = zh_by_url.get(key)
        if prev is not None:
            final_zh.append(
                item.model_copy(
                    update={
                        "title": prev.title,
                        "summary": prev.summary,
                        "speak_summary": prev.speak_summary,
                    }
                )
            )
        else:
            final_zh.append(item)
    write_digest(zh_path, final_zh, generated_at=generated_at)
    logger.info(
        "deep_summarize wrote en=%s zh=%s changed=%s",
        en_path,
        zh_path,
        changed,
    )
    return en_path, zh_path, changed


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not args.url:
        print("error: provide at least one --url", file=sys.stderr)
        return 2
    config = load_app_config()
    en_path, zh_path, n = deep_summarize_digest(
        config,
        urls=args.url,
        llm_flag=args.llm,
        input_path=args.input,
        input_zh_path=args.input_zh,
        max_chars=args.max_chars,
    )
    print(f"[ai_hot] deep-summarized {n} item(s) → {en_path} + {zh_path}")
    if n:
        print("[ai_hot] next: python -m src.publish  # optional archive")
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())
