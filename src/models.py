"""领域数据模型。"""

from datetime import datetime, timezone

from pydantic import BaseModel, Field, HttpUrl


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class HotItem(BaseModel):
    """一条候选/入选热点。"""

    source: str
    title: str
    url: str
    score: int | None = None
    comments: int | None = None
    summary: str | None = None
    published_at: datetime | None = None
    reason: str = ""
    fetched_at: datetime = Field(default_factory=utc_now)


class FeedConfig(BaseModel):
    name: str
    url: HttpUrl
    # 非空则标题/摘要须命中至少一词（大小写不敏感）；空=不过滤
    keywords: list[str] = Field(default_factory=list)


class HnConfig(BaseModel):
    enabled: bool = True
    top_n: int = 30
    min_score: int = 100
    min_comments: int = 20


class RssConfig(BaseModel):
    max_new_per_feed: int = 5
    feeds: list[FeedConfig] = Field(default_factory=list)


class FilterConfig(BaseModel):
    cooldown_hours: int = 24


class PathsConfig(BaseModel):
    sqlite_path: str = "data/ai_hot.db"
    digest_path: str = "out/digest.md"
    digest_zh_path: str = "out/digest.zh.md"
    content_digests_dir: str = "content/digests"
    site_output_dir: str = "public"


class DigestItem(BaseModel):
    """站点用的一条 digest 条目（从 md 解析）。"""

    index: int
    title: str
    source: str = ""
    url: str = ""
    published: str = ""
    score_line: str = ""
    summary: str = ""
    reason: str = ""


class DigestDocument(BaseModel):
    """一份按日归档的 digest。"""

    title: str = ""
    generated_at: str = ""
    selected: int | None = None
    items: list[DigestItem] = Field(default_factory=list)


class HttpConfig(BaseModel):
    timeout_seconds: float = 30.0
    user_agent: str = "ai_hot/0.1"


class OllamaConfig(BaseModel):
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen3:4b-instruct"
    timeout_seconds: float = 300.0


class AppConfig(BaseModel):
    paths: PathsConfig = Field(default_factory=PathsConfig)
    hn: HnConfig = Field(default_factory=HnConfig)
    rss: RssConfig = Field(default_factory=RssConfig)
    filter: FilterConfig = Field(default_factory=FilterConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
