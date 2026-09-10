"""纯文本处理：去 HTML、截断。"""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser


class _StripHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


_WS_RE = re.compile(r"\s+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def contains_cjk(text: str) -> bool:
    """是否包含汉字（用于 digest 英文化判定）。"""
    return _CJK_RE.search(text) is not None


def strip_html(raw: str) -> str:
    parser = _StripHTML()
    parser.feed(raw)
    parser.close()
    text = unescape(parser.text())
    return _WS_RE.sub(" ", text).strip()


def truncate(text: str, max_chars: int = 280) -> str:
    cleaned = _WS_RE.sub(" ", text).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"
