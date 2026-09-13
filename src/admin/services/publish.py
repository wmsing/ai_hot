"""Admin 发布：git add content → commit → push。"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

CONTENT_GLOBS = (
    "content/hot_topics",
    "content/digests",
    "content/audio",
    "content/arena",
)


def repo_root() -> Path:
    out = _run_git("rev-parse", "--show-toplevel")
    return Path(out.strip())


def publish_status() -> dict[str, object]:
    """返回 content/ 下待提交变更。"""
    root = repo_root()
    lines = _status_lines(root)
    return {
        "repo_root": str(root),
        "pending": lines,
        "has_changes": bool(lines),
    }


def publish_push(*, message: str | None = None) -> dict[str, object]:
    """stage content 路径 → commit → push。"""
    root = repo_root()
    pending = _status_lines(root)
    if not pending:
        return {
            "ok": True,
            "committed": False,
            "pushed": False,
            "message": "nothing to commit",
            "pending": [],
        }

    for rel in CONTENT_GLOBS:
        target = root / rel
        if target.exists():
            _run_git("-C", str(root), "add", rel)

    commit_msg = (message or "").strip() or _default_commit_message()
    _run_git("-C", str(root), "commit", "-m", commit_msg)
    push_out = _run_git("-C", str(root), "push")
    head = _run_git("-C", str(root), "rev-parse", "--short", "HEAD").strip()
    return {
        "ok": True,
        "committed": True,
        "pushed": True,
        "commit": head,
        "message": commit_msg,
        "pending": pending,
        "push_output": push_out.strip(),
    }


def _default_commit_message() -> str:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"content: admin publish {day}"


def _status_lines(root: Path) -> list[str]:
    out = _run_git(
        "-C",
        str(root),
        "status",
        "--porcelain",
        "--",
        *CONTENT_GLOBS,
    )
    return [line for line in out.splitlines() if line.strip()]


def _run_git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(detail or f"git {' '.join(args)} failed")
    return proc.stdout
