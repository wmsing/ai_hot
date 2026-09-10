"""HTTP 客户端工厂。"""

from __future__ import annotations

import httpx

from src.models import HttpConfig


def build_client(http: HttpConfig) -> httpx.Client:
    return httpx.Client(
        timeout=http.timeout_seconds,
        headers={"User-Agent": http.user_agent},
        follow_redirects=True,
    )
