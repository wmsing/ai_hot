"""speak_script 口播文案单测。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.models import AppConfig, DigestDocument, DigestItem, PathsConfig
from src.speak import run_speak
from src.speak_script import format_item_speak, format_speak_document


def test_format_item_speak_prefers_speak_summary() -> None:
    item = DigestItem(
        index=1,
        title="标题",
        summary="⚡️ 展示用摘要带 emoji",
        speak_summary="朗读用摘要没有表情",
    )
    text = format_item_speak(item)
    assert "朗读用摘要没有表情" in text
    assert "emoji" not in text
    assert "⚡️" not in text


def test_format_item_speak_with_summary() -> None:
    item = DigestItem(
        index=1,
        title="OpenAI Agents API",
        summary="开发者可构建自主代理应用",
    )
    text = format_item_speak(item)
    assert text == "OpenAI Agents API。\n开发者可构建自主代理应用。"
    assert "第" not in text


def test_format_item_speak_skips_empty_and_na_summary() -> None:
    empty = DigestItem(index=2, title="已有句号。", summary="")
    assert format_item_speak(empty) == "已有句号。"
    na = DigestItem(index=3, title="标题", summary="n/a")
    assert format_item_speak(na) == "标题。"


def test_format_speak_document_intro_and_gaps() -> None:
    doc = DigestDocument(
        items=[
            DigestItem(index=1, title="甲", summary="摘要甲"),
            DigestItem(index=2, title="乙。", summary="摘要乙"),
        ]
    )
    text = format_speak_document(doc, lang="zh")
    assert text.startswith("今日 AI 热点共 2 条。\n\n")
    assert "甲。\n摘要甲。" in text
    assert "乙。\n摘要乙。" in text
    assert "第1条" not in text
    assert text.endswith("\n")


def test_format_speak_document_en_intro() -> None:
    doc = DigestDocument(
        items=[DigestItem(index=1, title="Hello", summary="World")]
    )
    text = format_speak_document(doc, lang="en")
    assert text.startswith("Today's AI highlights: 1 items.")
    assert "Hello.\nWorld." in text


def test_run_speak_skips_existing_mp3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    digest = tmp_path / "digest.zh.md"
    digest.write_text(
        "# ai_hot digest\n\nGenerated (UTC): 2026-09-11T12:00:00+00:00\n"
        "Selected: 2\n\n"
        "## 1. 一\n\n- source: `hn`\n- url: https://a.example/1\n"
        "- summary: 摘要一\n\n"
        "## 2. 二\n\n- source: `hn`\n- url: https://a.example/2\n"
        "- summary: 摘要二\n",
        encoding="utf-8",
    )
    content_day = tmp_path / "content_audio" / "zh" / "2026-09-11"
    content_day.mkdir(parents=True)
    (content_day / "001.mp3").write_bytes(b"EXISTING-1")
    out_audio = tmp_path / "out_audio"
    speak_path = tmp_path / "speak.zh.md"
    cfg = AppConfig(
        paths=PathsConfig(
            digest_zh_path=str(digest),
            speak_zh_path=str(speak_path),
            speak_audio_dir=str(out_audio),
            content_audio_dir=str(tmp_path / "content_audio"),
        )
    )
    calls: list[str] = []

    def _fake_synthesize(text: str, path: Path, **_kwargs: object) -> None:
        calls.append(path.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"NEW-{path.name}".encode())

    monkeypatch.setattr("src.speak.synthesize", _fake_synthesize)
    run_speak(cfg, lang="zh")

    assert "001.mp3" not in calls
    assert "002.mp3" in calls
    assert (out_audio / "zh" / "2026-09-11" / "001.mp3").read_bytes() == b"EXISTING-1"
    assert (content_day / "002.mp3").is_file()


def test_run_speak_force_regenerates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    digest = tmp_path / "digest.zh.md"
    digest.write_text(
        "# ai_hot digest\n\nGenerated (UTC): 2026-09-11T12:00:00+00:00\n"
        "Selected: 1\n\n"
        "## 1. 一\n\n- source: `hn`\n- url: https://a.example/1\n"
        "- summary: 摘要一\n",
        encoding="utf-8",
    )
    content_day = tmp_path / "content_audio" / "zh" / "2026-09-11"
    content_day.mkdir(parents=True)
    (content_day / "001.mp3").write_bytes(b"OLD")
    cfg = AppConfig(
        paths=PathsConfig(
            digest_zh_path=str(digest),
            speak_zh_path=str(tmp_path / "speak.zh.md"),
            speak_audio_dir=str(tmp_path / "out_audio"),
            content_audio_dir=str(tmp_path / "content_audio"),
        )
    )
    calls: list[str] = []

    def _fake_synthesize(text: str, path: Path, **_kwargs: object) -> None:
        calls.append(path.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"FORCED")

    monkeypatch.setattr("src.speak.synthesize", _fake_synthesize)
    run_speak(cfg, lang="zh", force=True)
    assert "001.mp3" in calls
    assert (content_day / "001.mp3").read_bytes() == b"FORCED"
