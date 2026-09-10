"""构建时拉取 Arena AI 多榜（单榜失败则跳过，不阻断构建）。"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from src.models import (
    ArenaLeaderboard,
    ArenaModelRow,
    HttpConfig,
    LeaderboardConfig,
)

logger = logging.getLogger(__name__)


def fetch_arena_boards(
    cfg: LeaderboardConfig,
    http: HttpConfig | None = None,
) -> list[ArenaLeaderboard]:
    """按配置拉取多榜；全部失败时返回空列表。"""
    if not cfg.enabled or not cfg.boards:
        return []
    http_cfg = http if http is not None else HttpConfig()
    timeout = min(cfg.timeout_seconds, http_cfg.timeout_seconds)
    results: list[ArenaLeaderboard] = []
    try:
        with httpx.Client(
            timeout=timeout,
            headers={"User-Agent": http_cfg.user_agent},
            follow_redirects=True,
        ) as client:
            for board in cfg.boards:
                name = board.strip()
                if not name:
                    continue
                snap = _fetch_one(client, cfg, name)
                if snap is not None:
                    results.append(snap)
    except httpx.HTTPError as exc:
        logger.warning("arena leaderboard client failed: %s", exc)
    return results


def _fetch_one(
    client: httpx.Client,
    cfg: LeaderboardConfig,
    board: str,
) -> ArenaLeaderboard | None:
    url = f"{cfg.base_url.rstrip('/')}?{urlencode({'name': board})}"
    try:
        resp = client.get(url)
        resp.raise_for_status()
        payload: Any = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("arena leaderboard fetch failed board=%s err=%s", board, exc)
        return None
    return parse_arena_payload(payload, cfg, board=board)


def parse_arena_payload(
    payload: Any,
    cfg: LeaderboardConfig,
    *,
    board: str,
) -> ArenaLeaderboard | None:
    """校验 JSON 并截断；结构不对返回 None。"""
    if not isinstance(payload, dict):
        logger.warning("arena leaderboard: payload is not an object board=%s", board)
        return None
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    raw_models = payload.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        logger.warning("arena leaderboard: missing models list board=%s", board)
        return None

    is_agent = board == "agent"
    score_label = cfg.agent_score_name if is_agent else "Elo"
    rows: list[ArenaModelRow] = []
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        try:
            rank = int(item["rank"])
            model = str(item["model"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if not model:
            continue
        vendor_raw = item.get("vendor")
        vendor = str(vendor_raw).strip() if vendor_raw is not None else None
        if vendor == "":
            vendor = None
        score = (
            _agent_score(item, cfg.agent_score_name) if is_agent else _elo_score(item)
        )
        rows.append(ArenaModelRow(rank=rank, model=model, vendor=vendor, score=score))

    if not rows:
        logger.warning("arena leaderboard: no valid model rows board=%s", board)
        return None

    rows.sort(key=lambda r: r.rank)
    top_n = max(1, cfg.top_n)
    source_page = f"{cfg.source_base.rstrip('/')}/{board}"
    source_url = str(meta.get("source_url") or source_page)
    return ArenaLeaderboard(
        board=board,
        source_url=source_url,
        source_page=source_page,
        score_label=score_label,
        fetched_at=str(meta.get("fetched_at") or ""),
        last_updated=str(meta.get("last_updated") or ""),
        models=rows[:top_n],
    )


def _elo_score(item: dict[str, Any]) -> float | None:
    try:
        score_raw = item.get("score")
        return float(score_raw) if score_raw is not None else None
    except (TypeError, ValueError):
        return None


def _agent_score(item: dict[str, Any], score_name: str) -> float | None:
    scores = item.get("scores")
    if not isinstance(scores, list):
        return None
    for entry in scores:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("name") or "") != score_name:
            continue
        try:
            raw = entry.get("score")
            return float(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None
    return None
