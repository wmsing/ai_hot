"""URL / 标题规范化，供去重使用。"""

import re
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TITLE_STRIP_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_WS_RE = re.compile(r"\s+")

# 常见追踪参数，规范化时丢弃
_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "ref",
}


def normalize_url(url: str) -> str:
    """规范化 URL：小写 host、去 fragment、去追踪参数、去尾斜杠。"""
    raw = url.strip()
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or ""
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    query = urlencode(query_pairs)
    return urlunparse((scheme, netloc, path, "", query, ""))


def title_key(title: str) -> str:
    """标题指纹：小写、去标点、压缩空白。"""
    lowered = title.strip().lower()
    cleaned = _TITLE_STRIP_RE.sub(" ", lowered)
    return _WS_RE.sub(" ", cleaned).strip()


def titles_similar(
    left: str,
    right: str,
    *,
    ratio_threshold: float = 0.88,
) -> bool:
    """标题是否视为同一故事（规范化相等、包含或高相似度）。"""
    a = title_key(left)
    b = title_key(right)
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 16 and shorter in longer:
        return True
    return SequenceMatcher(None, a, b).ratio() >= ratio_threshold
