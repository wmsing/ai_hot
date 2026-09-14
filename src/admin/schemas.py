"""Admin API 请求/响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.models import HotTopicSnapshotItem


class HotTopicCreate(HotTopicSnapshotItem):
    pass


class HotTopicUpdate(BaseModel):
    url: str
    heat: float | None = None
    source: str | None = None
    title: str | None = None
    title_zh: str | None = None
    score: int | None = None
    comments: int | None = None
    summary: str | None = None
    summary_en: str | None = None
    summary_zh: str | None = None
    published_at: datetime | None = None
    sources: list[str] | None = None
    reason: str | None = None


class UrlBody(BaseModel):
    url: str


AdhdLang = Literal["zh", "en", "both"]


class AdhdHotTopicRequest(BaseModel):
    url: str
    force: bool = False
    llm: str | None = None
    lang: AdhdLang = "both"


class AdhdHotTopicsAllRequest(BaseModel):
    urls: list[str] | None = None
    force: bool = False
    llm: str | None = None
    lang: AdhdLang = "zh"


class PullDataRequest(BaseModel):
    llm: str | None = None


class CopyHotTopicToDigestRequest(BaseModel):
    url: str
    day: str | None = None


class TranslateHotTopicTitlesRequest(BaseModel):
    urls: list[str] | None = None
    force: bool = False
    llm: str | None = None


class TranslateDigestTitlesRequest(BaseModel):
    indices: list[int] | None = None
    force: bool = False
    llm: str | None = None


class TranslateDigestSummariesRequest(BaseModel):
    indices: list[int] | None = None
    force: bool = False
    llm: str | None = None


class AdhdDigestRequest(BaseModel):
    force: bool = False
    llm: str | None = None


class AdhdDigestBatchRequest(BaseModel):
    indices: list[int]
    force: bool = False
    llm: str | None = None


class DigestSpeakRequest(BaseModel):
    indices: list[int] | None = None
    urls: list[str] | None = None
    langs: list[Literal["en", "zh"]] | None = None
    force: bool = False


class DigestItemCreate(BaseModel):
    title_en: str
    title_zh: str = ""
    url: str
    source: str = "manual"
    published: str = ""
    score_line: str = ""
    summary_en: str = ""
    summary_zh: str = ""
    speak_en: str = ""
    speak_zh: str = ""
    tag: str = ""
    image_url: str = ""


class DigestItemUpdate(BaseModel):
    title_en: str | None = None
    title_zh: str | None = None
    url: str | None = None
    source: str | None = None
    published: str | None = None
    score_line: str | None = None
    summary_en: str | None = None
    summary_zh: str | None = None
    speak_en: str | None = None
    speak_zh: str | None = None
    tag: str | None = None
    image_url: str | None = None


AudioSyncStatus = Literal["ok", "stale", "missing"]


class AudioFileOut(BaseModel):
    content_path: str | None = None
    out_path: str | None = None
    play_url: str | None = None
    exists: bool = False
    sync_status: AudioSyncStatus = "missing"


class MergedDigestItemOut(BaseModel):
    index: int
    title_en: str
    title_zh: str
    url: str
    source: str
    published: str
    score_line: str
    summary_en: str
    summary_zh: str
    speak_en: str
    speak_zh: str
    tag: str = ""
    image_url: str = ""
    has_adhd: bool = False
    hot_topic_match: bool = False
    can_copy_hot_adhd: bool = False
    archive_day: str | None = None
    published_day: str | None = None
    audio_en: AudioFileOut = Field(default_factory=AudioFileOut)
    audio_zh: AudioFileOut = Field(default_factory=AudioFileOut)


class DigestDayOut(BaseModel):
    day: str
    generated_at: str
    items: list[MergedDigestItemOut]


class DigestTimelineDayOut(BaseModel):
    published_day: str
    items: list[MergedDigestItemOut]


class DigestRecentOut(BaseModel):
    limit: int
    published_days: list[str]
    items: list[MergedDigestItemOut]


class PublishRequest(BaseModel):
    message: str | None = None


class JobOut(BaseModel):
    id: str
    kind: str
    status: str
    message: str
    result: dict[str, Any] = Field(default_factory=dict)
