"""关键词白名单匹配（用于量子位等噪音源）。"""

from __future__ import annotations

from src.models import HotItem


def matched_keyword(item: HotItem, keywords: list[str]) -> str | None:
    """返回命中的第一个关键词；无命中返回 None。"""
    if not keywords:
        return None
    blob = f"{item.title}\n{item.summary or ''}".casefold()
    for raw in keywords:
        term = raw.strip()
        if term and term.casefold() in blob:
            return term
    return None


def passes_keywords(item: HotItem, keywords: list[str]) -> bool:
    """无关键词配置视为通过；有配置则须命中。"""
    if not keywords:
        return True
    return matched_keyword(item, keywords) is not None
