"""从文章页提取可引用简介片段（OG / meta / 正文），禁止凭空编造。"""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser

import httpx

from src.textutil import strip_html, truncate

logger = logging.getLogger(__name__)

_MAX_DOWNLOAD_BYTES = 500_000
_MAX_DOWNLOAD_BYTES_BODY = 1_000_000
_DEFAULT_SNIPPET_CHARS = 1200
_DEFAULT_BODY_CHARS = 8000
_MIN_BODY_CHARS = 200

_SCRIPT_STYLE_RE = re.compile(
    r"(?is)<(script|style|noscript)\b[^>]*>.*?</\1>",
)
_CHROME_RE = re.compile(
    r"(?is)<(nav|footer|header|aside|svg)\b[^>]*>.*?</\1>",
)
_ARTICLE_RE = re.compile(r"(?is)<article\b[^>]*>(.*?)</article>")
_MAIN_RE = re.compile(r"(?is)<main\b[^>]*>(.*?)</main>")
_ROLE_MAIN_RE = re.compile(
    r'(?is)<([a-zA-Z][\w:-]*)\b[^>]*\brole\s*=\s*["\']main["\'][^>]*>(.*?)</\1>'
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
        html = _download_html(client, target, max_bytes=_MAX_DOWNLOAD_BYTES)
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


def fetch_page_body(
    client: httpx.Client,
    url: str,
    *,
    max_chars: int = _DEFAULT_BODY_CHARS,
) -> str | None:
    """抓取 URL，返回 article/main 优先的长正文；失败或过短则 None。"""
    target = url.strip()
    if not target.startswith(("http://", "https://")):
        return None
    try:
        html = _download_html(client, target, max_bytes=_MAX_DOWNLOAD_BYTES_BODY)
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("page body fetch failed url=%s err=%s", target[:120], exc)
        return None
    if not html:
        return None
    body = extract_page_body(html, max_chars=max_chars)
    if not body:
        logger.info("page body empty url=%s", target[:120])
        return None
    return body


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


def extract_page_body(
    html: str,
    *,
    max_chars: int = _DEFAULT_BODY_CHARS,
) -> str | None:
    """从 HTML 抽长正文：优先 article/main/role=main，否则去标签全文。"""
    cleaned = _SCRIPT_STYLE_RE.sub(" ", html)
    cleaned = _CHROME_RE.sub(" ", cleaned)

    candidates: list[str] = []
    for match in _ARTICLE_RE.finditer(cleaned):
        candidates.append(match.group(1))
    for match in _MAIN_RE.finditer(cleaned):
        candidates.append(match.group(1))
    for match in _ROLE_MAIN_RE.finditer(cleaned):
        candidates.append(match.group(2))

    best = ""
    best_len = 0
    for chunk in candidates:
        text = strip_html(chunk).strip()
        if len(text) > best_len:
            best = text
            best_len = len(text)

    if best_len >= _MIN_BODY_CHARS:
        return truncate(best, max_chars) or None

    fallback = strip_html(cleaned).strip()
    if len(fallback) < _MIN_BODY_CHARS:
        return None
    return truncate(fallback, max_chars) or None


def _download_html(
    client: httpx.Client,
    url: str,
    *,
    max_bytes: int = _MAX_DOWNLOAD_BYTES,
) -> str:
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
            if total >= max_bytes:
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
