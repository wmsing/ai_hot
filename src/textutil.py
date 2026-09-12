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


# Emoji / pictograph（口播需剥除）
_EMOJI_RE = re.compile(
    "["
    "\U0001f300-\U0001f9ff"
    "\U0001fa00-\U0001faff"
    "\U00002600-\U000027bf"
    "\U0000fe00-\U0000fe0f"
    "\U0001f1e0-\U0001f1ff"
    "\U0000200d"
    "\U0000fe0f"
    "]+",
    flags=re.UNICODE,
)


def strip_emoji(text: str) -> str:
    """去掉 emoji，压空白；供 TTS 朗读版。"""
    cleaned = _EMOJI_RE.sub("", text)
    return _WS_RE.sub(" ", cleaned).strip()


def speak_plain(text: str) -> str:
    """摘要 → 无 emoji 的单段口播文本。"""
    return strip_emoji(text.replace("\n", " "))
