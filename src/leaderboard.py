"""构建时拉取 Arena AI 多榜（单榜失败则跳过，不阻断构建）。"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
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
    *,
    cache_dir: Path | None = None,
) -> list[ArenaLeaderboard]:
    """按配置拉取多榜；API 失败时回退 GitHub raw，再回退本地缓存。"""
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
            github_date = _resolve_github_date(client, cfg)
            for idx, board in enumerate(cfg.boards):
                name = board.strip()
                if not name:
                    continue
                if idx > 0 and cfg.request_gap_seconds > 0:
                    time.sleep(cfg.request_gap_seconds)
                snap = _fetch_one(
                    client,
                    cfg,
                    name,
                    github_date=github_date,
                    cache_dir=cache_dir,
                )
                if snap is not None:
                    results.append(snap)
    except httpx.HTTPError as exc:
        logger.warning("arena leaderboard client failed: %s", exc)
    return results


def _fetch_one(
    client: httpx.Client,
    cfg: LeaderboardConfig,
    board: str,
    *,
    github_date: str | None,
    cache_dir: Path | None,
) -> ArenaLeaderboard | None:
    payload = _get_json_api(client, cfg, board)
    source = "api"
    if payload is None and github_date:
        payload = _get_json_github(client, cfg, board, github_date)
        source = "github"
    if payload is None and cache_dir is not None:
        payload = _load_cache(cache_dir, board)
        source = "cache"
    if payload is None:
        return None
    snap = parse_arena_payload(payload, cfg, board=board)
    if snap is None:
        return None
    if cache_dir is not None and source != "cache":
        _save_cache(cache_dir, board, payload)
    if source != "api":
        logger.info("arena leaderboard board=%s via %s", board, source)
    return snap


def _get_json_api(
    client: httpx.Client,
    cfg: LeaderboardConfig,
    board: str,
) -> dict[str, Any] | None:
    url = f"{cfg.base_url.rstrip('/')}?{urlencode({'name': board})}"
    try:
        resp = client.get(url)
        if resp.status_code == 429:
            logger.warning("arena leaderboard API rate-limited board=%s", board)
            return None
        resp.raise_for_status()
        payload: Any = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("arena leaderboard API failed board=%s err=%s", board, exc)
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _resolve_github_date(
    client: httpx.Client,
    cfg: LeaderboardConfig,
) -> str | None:
    base = cfg.github_raw_base.strip()
    if not base:
        return None
    url = f"{base.rstrip('/')}/latest.json"
    try:
        resp = client.get(url)
        resp.raise_for_status()
        payload: Any = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("arena github latest.json failed: %s", exc)
        return None
    if not isinstance(payload, dict):
        return None
    path = str(payload.get("path") or payload.get("date") or "").strip()
    return path or None


def _get_json_github(
    client: httpx.Client,
    cfg: LeaderboardConfig,
    board: str,
    date_path: str,
) -> dict[str, Any] | None:
    url = f"{cfg.github_raw_base.rstrip('/')}/{date_path}/{board}.json"
    try:
        resp = client.get(url)
        resp.raise_for_status()
        payload: Any = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "arena github fetch failed board=%s date=%s err=%s",
            board,
            date_path,
            exc,
        )
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _cache_path(cache_dir: Path, board: str) -> Path:
    safe = board.replace("/", "-")
    return cache_dir / f"{safe}.json"


def _save_cache(cache_dir: Path, board: str, payload: dict[str, Any]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir, board)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _load_cache(cache_dir: Path, board: str) -> dict[str, Any] | None:
    path = _cache_path(cache_dir, board)
    if not path.is_file():
        return None
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("arena cache read failed board=%s err=%s", board, exc)
        return None
    if not isinstance(payload, dict):
        return None
    return payload


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
