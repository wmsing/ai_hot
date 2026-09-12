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
from src.models import AppConfig, HotItem, HotTopicSnapshotItem, LlmRuntime
from src.ollama_client import llm_chat
from src.textutil import contains_cjk, speak_plain

FetchBodyFn = Callable[..., str | None]
ChatFn = Callable[..., str]

logger = logging.getLogger(__name__)

_TITLE_ZH_SYSTEM = """你是技术标题翻译。把英文标题译成简短、准确的中文。
规则：
1. 保留专有名词英文（OpenAI、RubyGems、Claude 等）
2. 只输出译后标题一行，不要引号、不要解释"""

_SUMMARY_ZH_SYSTEM = """你是技术资讯翻译。把用户给出的英文摘要译成简体中文。
规则：
1. 保留专有名词英文（OpenAI、Reddit、LLM 等）
2. 只输出译后摘要正文，不要引号、不要前言后语"""

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


def extract_adhd_one_liner(text: str, *, lang: str = "zh") -> str:
    """从 ADHD 摘要里取一句话总结正文。"""
    marker = "一句话总结" if lang == "zh" else "One-liner"
    stop_markers = ("核心亮点", "Key takeaways")
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return ""
    lines = normalized.split("\n")
    for idx, raw in enumerate(lines):
        line = raw.strip()
        if marker not in line:
            continue
        inline = line.split(marker, 1)[-1].strip("：: \t")
        if inline:
            return inline
        for nxt in lines[idx + 1 :]:
            cleaned = nxt.strip()
            if not cleaned:
                continue
            if any(stop in cleaned for stop in stop_markers):
                break
            return cleaned
    return ""


def hot_topic_display_title(item: HotTopicSnapshotItem, lang: str) -> str:
    """热搜页展示标题：中文页用 title_zh，否则回退英文 title。"""
    if lang == "zh" and item.title_zh and item.title_zh.strip():
        return item.title_zh.strip()
    return item.title


def translate_title_to_zh(
    title: str,
    llm: LlmRuntime,
    *,
    chat: ChatFn | None = None,
) -> str:
    """把英文标题译成中文；已是中文则原样返回。"""
    cleaned = title.strip()
    if not cleaned:
        return ""
    if contains_cjk(cleaned):
        return cleaned
    chat_fn = chat or llm_chat
    translated = chat_fn(
        system=_TITLE_ZH_SYSTEM,
        user=cleaned,
        llm=llm,
    ).strip()
    return translated.strip("\"'“”‘’ ")


def translate_summary_to_zh(
    summary: str,
    llm: LlmRuntime,
    *,
    chat: ChatFn | None = None,
) -> str:
    """把英文 probe 摘要译成中文；已是中文则原样返回。"""
    cleaned = summary.strip()
    if not cleaned:
        return ""
    if contains_cjk(cleaned):
        return cleaned
    chat_fn = chat or llm_chat
    translated = chat_fn(
        system=_SUMMARY_ZH_SYSTEM,
        user=cleaned,
        llm=llm,
    ).strip()
    return translated.strip("\"'“”‘’ ")


def _hot_topic_summary_translate_fallback(
    item: HotTopicSnapshotItem,
    llm: LlmRuntime,
    *,
    chat: ChatFn | None = None,
) -> dict[str, str] | None:
    """抓正文失败时：用 probe 英文 summary 直译中文。"""
    raw = (item.summary or "").strip()
    if not raw or contains_cjk(raw):
        return None
    zh = translate_summary_to_zh(raw, llm, chat=chat)
    if not zh:
        return None
    return {
        "summary_en": raw,
        "summary_zh": zh,
        "summary": zh,
    }


def _hot_topic_needs_title_zh(item: HotTopicSnapshotItem) -> bool:
    """缺 title_zh，或旧版误用一句话总结当标题。"""
    current = (item.title_zh or "").strip()
    if not current:
        return True
    one_liner = extract_adhd_one_liner(
        item.summary_zh or item.summary or "",
        lang="zh",
    )
    return bool(one_liner and current == one_liner.strip())


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
    parser.add_argument(
        "--hot-topics",
        action="store_true",
        help="Summarize URLs in content/hot_topics/latest.json (not digest)",
    )
    parser.add_argument(
        "--hot-topics-path",
        default=None,
        help="Hot topics snapshot JSON (default: paths.hot_topics_path)",
    )
    return parser.parse_args(argv)


def summarize_adhd_pair(
    *,
    title: str,
    url: str,
    source: str,
    llm: LlmRuntime,
    http: httpx.Client,
    max_chars: int = 8000,
    fetch_body: FetchBodyFn | None = None,
    chat: ChatFn | None = None,
    fallback_body: str | None = None,
) -> tuple[str, str] | None:
    """抓正文并写 ADHD 中/英摘要；失败返回 None。"""
    fetch_fn = fetch_body or fetch_page_body
    chat_fn = chat or llm_chat
    body_raw: Any = fetch_fn(http, url, max_chars=max_chars)
    body = str(body_raw).strip() if body_raw else ""
    if not body and fallback_body:
        body = fallback_body.strip()
        if body:
            logger.info(
                "summarize_adhd fallback body url=%s chars=%s",
                url[:120],
                len(body),
            )
    if not body:
        logger.warning("summarize_adhd skip; no body url=%s", url[:120])
        return None

    user_payload = (
        f"Title: {title}\n"
        f"URL: {url}\n"
        f"Source: {source}\n\n"
        f"【文章正文】\n{body}\n"
    )
    zh_summary = _normalize_adhd_summary(
        chat_fn(system=_ADHD_SYSTEM, user=user_payload, llm=llm).strip()
    )
    if not zh_summary or "一句话总结" not in zh_summary:
        logger.warning("summarize_adhd weak ZH output url=%s", url[:120])
        return None

    en_summary = _normalize_adhd_summary(
        chat_fn(
            system=_EN_ADHD_SYSTEM,
            user=(
                f"Title: {title}\n"
                f"URL: {url}\n\n"
                f"Article body:\n{body}\n"
            ),
            llm=llm,
        ).strip()
    )
    if not en_summary or "One-liner" not in en_summary:
        logger.warning("summarize_adhd weak EN output url=%s", url[:120])
        en_summary = ""

    return en_summary, zh_summary


def _hot_topic_has_adhd_summary(item: HotTopicSnapshotItem) -> bool:
    """已有完整 ADHD 或 probe 摘要直译则跳过。"""
    zh = (item.summary_zh or "").strip()
    en = (item.summary_en or "").strip()
    if "一句话总结" in zh and "One-liner" in en:
        return True
    return bool(zh and en and contains_cjk(zh))


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
            pair = summarize_adhd_pair(
                title=item.title,
                url=url,
                source=item.source,
                llm=llm,
                http=http,
                max_chars=max_chars,
                fetch_body=fetch_fn,
                chat=chat_fn,
            )
            if pair is None:
                continue
            en_summary, zh_summary = pair
            if not en_summary:
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


def deep_summarize_hot_topics(
    config: AppConfig,
    *,
    snapshot_path: str | Path | None = None,
    urls: list[str] | None = None,
    llm_flag: str | None = None,
    max_chars: int | None = None,
    top_n: int | None = None,
    client: httpx.Client | None = None,
    runtime: LlmRuntime | None = None,
    fetch_body: FetchBodyFn | None = None,
    chat: ChatFn | None = None,
) -> tuple[Path, int]:
    """对热搜快照里的 URL 写 ADHD 中/英摘要并回写 JSON。"""
    from src.hot_topics_probe import load_hot_topics_snapshot

    path = Path(snapshot_path or config.paths.hot_topics_path)
    snapshot = load_hot_topics_snapshot(path)
    if snapshot is None or not snapshot.items:
        raise FileNotFoundError(f"no hot topics snapshot at {path}; run probe first")

    url_filter = {_normalize_url(u) for u in (urls or []) if u.strip()}
    cap = top_n if top_n is not None else config.hot_topics.deep_summarize_top_n
    if url_filter:
        all_keys = {_normalize_url(it.url) for it in snapshot.items}
        missing = url_filter - all_keys
        if missing:
            raise ValueError(
                "URL not in hot topics snapshot: "
                + ", ".join(sorted(missing)[:5])
                + ("…" if len(missing) > 5 else "")
            )

    provider = resolve_provider(llm_flag, config)
    model = resolve_llm_model(llm_flag, config, provider=provider) if llm_flag else None
    llm = runtime or build_llm_runtime(
        config,
        provider=provider,
        model=model,
        api_key=settings.openrouter_api_key,
    )
    chars = max_chars
    if chars is None:
        chars = config.hot_topics.deep_summarize_max_chars
    owns_client = client is None
    http = client or build_client(config.http)
    chat_fn = chat or llm_chat
    changed = 0
    updated_items = list(snapshot.items)

    title_targets: list[int] = []
    for idx, item in enumerate(updated_items):
        key = _normalize_url(item.url)
        if url_filter and key not in url_filter:
            continue
        if _hot_topic_needs_title_zh(item):
            title_targets.append(idx)

    pending: list[int] = []
    for idx, item in enumerate(updated_items):
        key = _normalize_url(item.url)
        if url_filter and key not in url_filter:
            continue
        if _hot_topic_has_adhd_summary(item):
            logger.info(
                "deep_summarize hot skip; already summarized url=%s",
                item.url[:120],
            )
            continue
        pending.append(idx)

    if not url_filter and cap > 0:
        summary_targets = pending[:cap]
    else:
        summary_targets = pending

    if not title_targets and not summary_targets:
        logger.info("deep_summarize hot topics: nothing pending")
        return path, 0

    try:
        for idx in title_targets:
            item = updated_items[idx]
            title_zh = translate_title_to_zh(item.title, llm, chat=chat_fn)
            if not title_zh:
                continue
            updated_items[idx] = item.model_copy(update={"title_zh": title_zh})
            changed += 1
            logger.info(
                "translate hot title url=%s zh=%s",
                item.url[:120],
                title_zh[:80],
            )

        for idx in summary_targets:
            item = updated_items[idx]
            url = item.url.strip()
            logger.info(
                "deep_summarize hot url=%s model=%s",
                url[:120],
                llm.model,
            )
            fallback_body = (item.summary or "").strip() or None
            pair = summarize_adhd_pair(
                title=item.title,
                url=url,
                source=item.source,
                llm=llm,
                http=http,
                max_chars=chars,
                fetch_body=fetch_body,
                chat=chat_fn,
                fallback_body=fallback_body,
            )
            updates: dict[str, object] | None
            if pair is None:
                translated = _hot_topic_summary_translate_fallback(
                    item,
                    llm,
                    chat=chat_fn,
                )
                if translated is None:
                    continue
                updates = dict(translated)
            else:
                en_summary, zh_summary = pair
                updates = {
                    "summary_en": en_summary or None,
                    "summary_zh": zh_summary,
                    "summary": zh_summary,
                }
            if _hot_topic_needs_title_zh(updated_items[idx]):
                title_zh = translate_title_to_zh(item.title, llm, chat=chat_fn)
                if title_zh:
                    updates["title_zh"] = title_zh
            updated_items[idx] = updated_items[idx].model_copy(update=updates)
            changed += 1
    finally:
        if owns_client:
            http.close()

    if changed:
        snapshot = snapshot.model_copy(update={"items": updated_items})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
    logger.info("deep_summarize hot topics changed=%s path=%s", changed, path)
    return path, changed


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.hot_topics:
        config = load_app_config()
        path, n = deep_summarize_hot_topics(
            config,
            snapshot_path=args.hot_topics_path,
            urls=args.url or None,
            llm_flag=args.llm,
            max_chars=args.max_chars,
        )
        print(f"[ai_hot] deep-summarized {n} hot topic(s) → {path}")
        if n == 0:
            print("[ai_hot] all hot topics already summarized")
        print("[ai_hot] next: python -m src.site_build")
        return 0
    if not args.url:
        print("error: provide --url and/or --hot-topics", file=sys.stderr)
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
