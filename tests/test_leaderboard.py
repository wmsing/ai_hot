"""Arena leaderboard 拉取与独立页。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from src.leaderboard import fetch_arena_boards, parse_arena_payload
from src.models import (
    ArenaLeaderboard,
    ArenaModelRow,
    HttpConfig,
    LeaderboardConfig,
    SiteConfig,
)
from src.site_build import build_site

_SAMPLE_ELO = {
    "meta": {
        "leaderboard": "text-to-image",
        "source_url": "https://arena.ai/leaderboard/text-to-image",
        "fetched_at": "2026-09-10T06:00:00+00:00",
        "last_updated": "Sep 7, 2026",
    },
    "models": [
        {"rank": 2, "model": "model-b", "vendor": "OrgB", "score": 1400},
        {"rank": 1, "model": "model-a", "vendor": "OrgA", "score": 1500},
        {"rank": 3, "model": "model-c", "vendor": None, "score": 1300},
    ],
}

_SAMPLE_AGENT = {
    "meta": {
        "leaderboard": "agent",
        "source_url": "https://arena.ai/leaderboard/agent",
        "fetched_at": "2026-09-10T06:00:00+00:00",
        "last_updated": "Sep 8, 2026",
    },
    "models": [
        {
            "rank": 1,
            "model": "Agent A",
            "vendor": "OrgA",
            "scores": [
                {"name": "Net Improvement", "score": 14.51, "ci": 1.9},
                {"name": "Confirmed Success", "score": 23.0, "ci": 2.0},
            ],
            "sessions": 100,
        },
        {
            "rank": 2,
            "model": "Agent B",
            "vendor": "OrgB",
            "scores": [
                {"name": "Net Improvement", "score": 12.0, "ci": 2.0},
            ],
            "sessions": 50,
        },
    ],
}

_EN_DIGEST = """# ai_hot digest

Generated (UTC): 2026-09-10T05:00:00+00:00
Selected: 1

## 1. Example Title

- source: `hn`
- url: https://example.com/a
- published: 2026-09-10T01:00:00+00:00
- score=120 | comments=30
- summary: Hello summary
- why: hn score>=100
"""


def _cfg(**kwargs: object) -> LeaderboardConfig:
    base: dict[str, object] = {
        "enabled": True,
        "base_url": "https://api.example/leaderboard",
        "source_base": "https://arena.ai/leaderboard",
        "boards": ["text-to-image"],
        "top_n": 10,
        "timeout_seconds": 5.0,
        "agent_score_name": "Net Improvement",
    }
    base.update(kwargs)
    return LeaderboardConfig.model_validate(base)


def test_parse_elo_sorts_and_truncates() -> None:
    snap = parse_arena_payload(_SAMPLE_ELO, _cfg(top_n=2), board="text-to-image")
    assert snap is not None
    assert snap.board == "text-to-image"
    assert snap.score_label == "Elo"
    assert len(snap.models) == 2
    assert snap.models[0].model == "model-a"
    assert snap.models[0].score == 1500


def test_parse_agent_net_improvement() -> None:
    snap = parse_arena_payload(_SAMPLE_AGENT, _cfg(), board="agent")
    assert snap is not None
    assert snap.score_label == "Net Improvement"
    assert snap.models[0].score == 14.51
    assert snap.source_page.endswith("/agent")


def test_parse_bad_shape() -> None:
    assert parse_arena_payload({"models": []}, _cfg(), board="agent") is None
    assert parse_arena_payload("nope", _cfg(), board="agent") is None


def test_fetch_disabled_returns_empty() -> None:
    assert fetch_arena_boards(_cfg(enabled=False)) == []


def test_fetch_http_error_skips_board(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.get.side_effect = httpx.ConnectError("down")
    monkeypatch.setattr("src.leaderboard.httpx.Client", lambda **_k: mock_client)
    assert fetch_arena_boards(_cfg(), HttpConfig()) == []


def test_fetch_multi_boards(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        def __init__(self, payload: dict[str, object]) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self._payload

    def _get(url: str, **_k: object) -> _Resp:
        if "name=agent" in url:
            return _Resp(_SAMPLE_AGENT)
        return _Resp(_SAMPLE_ELO)

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.get.side_effect = _get
    monkeypatch.setattr("src.leaderboard.httpx.Client", lambda **_k: mock_client)
    boards = fetch_arena_boards(
        _cfg(boards=["agent", "text-to-image"], top_n=1), HttpConfig()
    )
    assert len(boards) == 2
    assert boards[0].board == "agent"
    assert boards[1].board == "text-to-image"
    assert len(boards[0].models) == 1


def test_build_site_arena_tab_not_home(tmp_path: Path) -> None:
    content = tmp_path / "digests"
    content.mkdir()
    (content / "2026-09-10.en.md").write_text(_EN_DIGEST, encoding="utf-8")
    out = tmp_path / "public"
    boards = [
        ArenaLeaderboard(
            board="text-to-image",
            source_url="https://arena.ai/leaderboard/text-to-image",
            source_page="https://arena.ai/leaderboard/text-to-image",
            score_label="Elo",
            fetched_at="2026-09-10T06:00:00+00:00",
            last_updated="Sep 7, 2026",
            models=[
                ArenaModelRow(rank=1, model="img-model", vendor="OpenAI", score=1421),
            ],
        ),
        ArenaLeaderboard(
            board="agent",
            source_url="https://arena.ai/leaderboard/agent",
            source_page="https://arena.ai/leaderboard/agent",
            score_label="Net Improvement",
            models=[
                ArenaModelRow(
                    rank=1, model="agent-model", vendor="Anthropic", score=14.51
                ),
            ],
        ),
    ]
    build_site(
        content_dir=content,
        output_dir=out,
        site=SiteConfig(),
        arena_boards=boards,
    )

    home = (out / "index.html").read_text(encoding="utf-8")
    assert 'href="arena.html"' in home
    assert ">Leaderboard<" in home
    assert "img-model" not in home
    assert 'class="arena"' not in home

    arena = (out / "arena.html").read_text(encoding="utf-8")
    assert ">Leaderboard<" in arena or "— Leaderboard" in arena
    assert "Text to Image" in arena
    assert "as of 2026-9-7" in arena
    assert "img-model" in arena
    assert "1421" in arena
    assert "Agent" in arena
    assert "agent-model" in arena
    assert "14.51" in arena
    assert "Net Improvement" in arena

    zh_arena = (out / "zh" / "arena.html").read_text(encoding="utf-8")
    assert "排行榜" in zh_arena
    assert "文生图" in zh_arena
    assert "截至 2026-9-7" in zh_arena
    assert "评分" in zh_arena
    assert "净提升" in zh_arena
