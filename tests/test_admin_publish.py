"""Admin 发布推送测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.admin.services import publish as publish_svc


def test_publish_status_lists_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def _fake_run(*args: str) -> str:
        calls.append(list(args))
        if args[:2] == ("rev-parse", "--show-toplevel"):
            return f"{tmp_path}\n"
        if "status" in args and "--porcelain" in args:
            return " M content/hot_topics/latest.json\n"
        raise AssertionError(f"unexpected git args: {args}")

    monkeypatch.setattr(publish_svc, "_run_git", _fake_run)
    status = publish_svc.publish_status()
    assert status["has_changes"] is True
    assert "content/hot_topics/latest.json" in status["pending"][0]


def test_publish_push_commits_and_pushes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = {"status": " M content/digests/2026-09-13.en.md\n"}

    def _fake_run(*args: str) -> str:
        if args[:2] == ("rev-parse", "--show-toplevel"):
            return f"{tmp_path}\n"
        if args[2:5] == ("status", "--porcelain", "--"):
            return state["status"]
        if args[2:3] == ("add",):
            return ""
        if args[2:3] == ("commit",):
            return ""
        if args[2:3] == ("push",):
            return "To origin\n   abc..def  main -> main\n"
        if args[2:4] == ("rev-parse", "--short"):
            return "def123\n"
        raise AssertionError(f"unexpected git args: {args}")

    monkeypatch.setattr(publish_svc, "_run_git", _fake_run)
    out = publish_svc.publish_push(message="content: test publish")
    assert out["committed"] is True
    assert out["pushed"] is True
    assert out["commit"] == "def123"
    assert out["message"] == "content: test publish"


def test_publish_push_no_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_run(*args: str) -> str:
        if args[:2] == ("rev-parse", "--show-toplevel"):
            return f"{tmp_path}\n"
        if args[2:5] == ("status", "--porcelain", "--"):
            return ""
        raise AssertionError(f"unexpected git args: {args}")

    monkeypatch.setattr(publish_svc, "_run_git", _fake_run)
    out = publish_svc.publish_push()
    assert out["committed"] is False
    assert out["pushed"] is False
