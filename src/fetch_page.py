"""从文章页提取可引用简介片段（OG / meta / 正文），禁止凭空编造。"""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser

import httpx

from src.textutil import strip_html, truncate

logger = logging.getLogger(__name__)

_MAX_DOWNLOAD_BYTES = 500_000
_DEFAULT_SNIPPET_CHARS = 1200

_SCRIPT_STYLE_RE = re.compile(
    r"(?is)<(script|style|noscript)\b[^>]*>.*?</\1>",
)


class _MetaParser(HTMLParser):
    """收集 og/twitter/description meta content。"""

    def __init__(self) -> None:
        super().__init__()
        self.og_description = ""
        self.meta_description = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "meta":
            return
        mapping = {k.lower(): (v or "") for k, v in attrs}
        prop = (mapping.get("property") or mapping.get("name") or "").strip().lower()
        content = mapping.get("content", "").strip()
        if not content:
            return
        if prop in ("og:description", "twitter:description"):
            if not self.og_description:
                self.og_description = content
        elif prop == "description":
            if not self.meta_description:
                self.meta_description = content


def fetch_page_snippet(
    client: httpx.Client,
    url: str,
    *,
    max_chars: int = _DEFAULT_SNIPPET_CHARS,
) -> str | None:
    """抓取 URL，返回 OG/meta/正文片段；失败或无可用文本则 None。"""
    target = url.strip()
    if not target.startswith(("http://", "https://")):
        return None
    try:
        html = _download_html(client, target)
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("page fetch failed url=%s err=%s", target[:120], exc)
        return None
    if not html:
        return None
    snippet = extract_page_snippet(html, max_chars=max_chars)
    if not snippet:
        logger.info("page snippet empty url=%s", target[:120])
        return None
    return snippet


def extract_page_snippet(
    html: str,
    *,
    max_chars: int = _DEFAULT_SNIPPET_CHARS,
) -> str | None:
    """从 HTML 抽简介：优先 OG/twitter/meta description，否则去标签正文。"""
    meta = _MetaParser()
    try:
        meta.feed(html)
        meta.close()
    except Exception:
        # 残缺 HTML 仍尝试正文回退
        pass
    for candidate in (meta.og_description, meta.meta_description):
        cleaned = truncate(strip_html(candidate), max_chars) if candidate else ""
        if cleaned:
            return cleaned
    cleaned_html = _SCRIPT_STYLE_RE.sub(" ", html)
    body = truncate(strip_html(cleaned_html), max_chars)
    return body or None


def _download_html(client: httpx.Client, url: str) -> str:
    with client.stream("GET", url) as resp:
        resp.raise_for_status()
        content_type = str(resp.headers.get("content-type") or "").lower()
        if content_type and "html" not in content_type and "text/" not in content_type:
            raise ValueError(f"unsupported content-type={content_type}")
        chunks: list[bytes] = []
        total = 0
        for chunk in resp.iter_bytes():
            chunks.append(chunk)
            total += len(chunk)
            if total >= _MAX_DOWNLOAD_BYTES:
                break
        raw = b"".join(chunks)
        encoding = resp.charset_encoding or "utf-8"
        try:
            text = raw.decode(encoding, errors="replace")
        except LookupError:
            text = raw.decode("utf-8", errors="replace")
    if not _looks_like_html(text, content_type):
        raise ValueError("response is not html")
    return text


def _looks_like_html(text: str, content_type: str) -> bool:
    if "html" in content_type:
        return True
    head = text.lstrip()[:200].lower()
    return head.startswith("<!doctype") or head.startswith("<html") or "<meta" in head
