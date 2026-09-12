"""领域数据模型。"""

from datetime import datetime, timezone
from typing import Literal

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
    # 口播用无 emoji 文本；空则 speak 回退 summary
    speak_summary: str | None = None
    image_url: str | None = None
    published_at: datetime | None = None
    # 展示标签，如 paper → 站点 EN: Paper / ZH: 论文
    tag: str = ""
    # 同 URL 合并后的来源族，如 ["hn", "reddit", "google_news"]
    sources: list[str] = Field(default_factory=list)
    reason: str = ""
    fetched_at: datetime = Field(default_factory=utc_now)


class HotTopicSnapshotItem(BaseModel):
    """站点「今日热搜」页一条。"""

    heat: float
    source: str
    title: str
    url: str
    score: int | None = None
    comments: int | None = None
    summary: str | None = None
    summary_en: str | None = None
    summary_zh: str | None = None
    title_zh: str | None = None
    published_at: datetime | None = None
    sources: list[str] = Field(default_factory=list)
    reason: str = ""


class HotTopicSnapshot(BaseModel):
    generated_at: datetime = Field(default_factory=utc_now)
    items: list[HotTopicSnapshotItem] = Field(default_factory=list)


class FeedConfig(BaseModel):
    name: str
    url: HttpUrl
    # 非空则标题/摘要须命中至少一词（大小写不敏感）；空=不过滤
    keywords: list[str] = Field(default_factory=list)
    # 写入条目的展示标签（如 paper）
    tag: str = ""
    # 本源每轮最多新条；None → 用 RssConfig.max_new_per_feed
    # 若设置了 max_age_hours，则不再按 max_new 截断（只按时间窗 + 已见跳过）
    max_new: int | None = None
    # URL 含子串则跳过（如 YouTube /shorts/）
    exclude_url_contains: list[str] = Field(default_factory=list)
    # 只收 published_at 在最近 N 小时内的条目；None=不限
    max_age_hours: int | None = None


class HnConfig(BaseModel):
    enabled: bool = True
    top_n: int = 30
    min_score: int = 100
    min_comments: int = 20


class RedditConfig(BaseModel):
    """Reddit 公开 JSON（无需 API key）。"""

    enabled: bool = True
    subreddits: list[str] = Field(
        default_factory=lambda: [
            "MachineLearning",
            "LocalLLaMA",
            "artificial",
            "OpenAI",
        ]
    )
    listing: Literal["top", "hot"] = "top"
    time_filter: Literal["hour", "day", "week", "month", "year", "all"] = "day"
    limit: int = 25
    min_score: int = 20
    # 进入 digest pipeline 时每轮总上限
    max_new_total: int = 5


class GoogleNewsQuery(BaseModel):
    """一条 Google News RSS 查询。"""

    name: str
    # 完整 RSS URL，或仅 q= 查询串（由代码拼默认 RSS）
    query: str
    hl: str = "en-US"
    gl: str = "US"
    ceid: str = "US:en"


class GoogleNewsConfig(BaseModel):
    enabled: bool = True
    max_per_query: int = 10
    max_new_total: int = 5
    queries: list[GoogleNewsQuery] = Field(
        default_factory=lambda: [
            GoogleNewsQuery(
                name="ai_en",
                query="artificial intelligence when:1d",
                hl="en-US",
                gl="US",
                ceid="US:en",
            ),
            GoogleNewsQuery(
                name="ai_zh",
                query="人工智能 when:1d",
                hl="zh-CN",
                gl="CN",
                ceid="CN:zh-Hans",
            ),
        ]
    )


class TrendsConfig(BaseModel):
    """Google Trends：非官方，失败则跳过。"""

    enabled: bool = True
    geo: str = "US"
    # 对 Top 候选做 related 补强时的种子词
    seed_keywords: list[str] = Field(
        default_factory=lambda: ["artificial intelligence", "ChatGPT", "LLM"]
    )
    # 日榜 RSS 命中这些词才入选
    ai_keywords: list[str] = Field(
        default_factory=lambda: [
            "ai",
            "artificial intelligence",
            "chatgpt",
            "openai",
            "claude",
            "gemini",
            "llm",
            "gpt",
            "deepseek",
            "人工智能",
            "大模型",
        ]
    )


class ThreadsConfig(BaseModel):
    """Threads Keyword Search；需 THREADS_ACCESS_TOKEN + App Review。"""

    enabled: bool = False
    seed_tags: list[str] = Field(
        default_factory=lambda: ["AI", "LLM", "OpenAI", "Claude", "ChatGPT"]
    )
    limit: int = 25
    max_new_total: int = 5
    search_type: Literal["TOP", "RECENT"] = "TOP"


class HotTopicsConfig(BaseModel):
    """跨源热门话题 probe / 打分。"""

    top_n: int = 20
    deep_summarize: bool = False
    # 0 = 精写快照里全部条目；>0 则只精写前 N 条
    deep_summarize_top_n: int = 0
    deep_summarize_max_chars: int = 8000
    source_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "hn": 1.0,
            "reddit": 0.8,
            "google_news": 0.6,
            "threads": 0.7,
            "trends": 0.5,
        }
    )
    w_engagement: float = 1.0
    w_recency: float = 0.5
    w_source: float = 1.0
    trends_boost: float = 0.3
    exclude_digest_urls: bool = True


class RssConfig(BaseModel):
    max_new_per_feed: int = 5
    feeds: list[FeedConfig] = Field(default_factory=list)


class FilterConfig(BaseModel):
    cooldown_hours: int = 24


class PathsConfig(BaseModel):
    sqlite_path: str = "data/ai_hot.db"
    digest_path: str = "out/digest.md"
    digest_zh_path: str = "out/digest.zh.md"
    speak_en_path: str = "out/speak.md"
    speak_zh_path: str = "out/speak.zh.md"
    # 根目录；实际文件在 {dir}/{en|zh}/{YYYY-MM-DD}/
    speak_audio_dir: str = "out/audio"
    content_audio_dir: str = "content/audio"
    content_digests_dir: str = "content/digests"
    hot_topics_path: str = "content/hot_topics/latest.json"
    arena_cache_dir: str = "content/arena"
    site_output_dir: str = "public"


class SpeakConfig(BaseModel):
    """口播 TTS（edge-tts）。"""

    voice: str = "zh-CN-YunxiNeural"
    voice_en: str = "en-US-JennyNeural"
    rate: str = "+0%"


class SiteConfig(BaseModel):
    """静态站展示、SEO 与联盟开关（非密钥）。"""

    affiliate_enabled: bool = False
    owner_name: str = ""
    contact_email: str = ""
    # sitemap / canonical / hreflang 用的站点根（无尾斜杠）
    base_url: str = "https://ai-hot.tonysingwm.workers.dev"


class LeaderboardConfig(BaseModel):
    """构建时拉取的 Arena 多榜配置。"""

    enabled: bool = True
    base_url: str = "https://api.wulong.dev/arena-ai-leaderboards/v1/leaderboard"
    # API 429 时回退到 GitHub raw 快照
    github_raw_base: str = (
        "https://raw.githubusercontent.com/oolong-tea-2026/"
        "arena-ai-leaderboards/main/data"
    )
    source_base: str = "https://arena.ai/leaderboard"
    boards: list[str] = Field(
        default_factory=lambda: [
            "agent",
            "text-to-image",
            "text-to-video",
            "image-edit",
            "image-to-video",
            "video-edit",
        ]
    )
    top_n: int = 10
    timeout_seconds: float = 20.0
    request_gap_seconds: float = 0.4
    agent_score_name: str = "Net Improvement"


class ArenaModelRow(BaseModel):
    """Arena 榜单上一行。"""

    rank: int
    model: str
    vendor: str | None = None
    score: float | None = None


class ArenaLeaderboard(BaseModel):
    """单榜构建快照。"""

    board: str
    source_url: str
    source_page: str
    score_label: str = "Elo"
    fetched_at: str = ""
    last_updated: str = ""
    models: list[ArenaModelRow] = Field(default_factory=list)


class DigestItem(BaseModel):
    """站点用的一条 digest 条目（从 md 解析）。"""

    index: int
    title: str
    source: str = ""
    url: str = ""
    published: str = ""
    score_line: str = ""
    summary: str = ""
    speak_summary: str = ""
    tag: str = ""
    reason: str = ""
    affiliate_url: str = ""
    image_url: str = ""


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
    timeout_seconds: float = 600.0
    # 增量翻译每批条数；过大易 ReadTimeout / 占满 RAM
    translate_batch_size: int = 8
    # 上下文窗口；过大（如默认 65536）会把 KV cache 撑到十余 GB
    num_ctx: int = 8192
    # Qwen3.5 等默认会 thinking；摘要/翻译应关掉，否则极慢且 content 可能为空
    think: bool = False


class OpenRouterConfig(BaseModel):
    base_url: str = "https://openrouter.ai/api/v1"
    model: str = "inclusionai/ling-3.0-flash-vl:free"
    # 主模型失败（空 content / HTTP 错）时再试一次；空字符串=不重试
    fallback_model: str = "openrouter/free"
    timeout_seconds: float = 120.0
    app_title: str = "ai_hot"


class LlmConfig(BaseModel):
    """默认 LLM 后端；可被 LLM_PROVIDER / --llm openrouter 覆盖。"""

    provider: Literal["ollama", "openrouter"] = "ollama"


class LlmRuntime(BaseModel):
    """一次调用的解析结果（provider + 端点 + 模型）。"""

    provider: Literal["ollama", "openrouter"]
    model: str
    base_url: str
    timeout_seconds: float = 300.0
    api_key: str = ""
    http_referer: str = ""
    app_title: str = "ai_hot"
    fallback_model: str = ""
    # 仅 Ollama：传给 options.num_ctx；None=不设置（用服务端默认）
    num_ctx: int | None = None
    # 仅 Ollama：顶层 think；None=不传该字段
    think: bool | None = False


class AppConfig(BaseModel):
    paths: PathsConfig = Field(default_factory=PathsConfig)
    site: SiteConfig = Field(default_factory=SiteConfig)
    leaderboard: LeaderboardConfig = Field(default_factory=LeaderboardConfig)
    hn: HnConfig = Field(default_factory=HnConfig)
    reddit: RedditConfig = Field(default_factory=RedditConfig)
    google_news: GoogleNewsConfig = Field(default_factory=GoogleNewsConfig)
    trends: TrendsConfig = Field(default_factory=TrendsConfig)
    threads: ThreadsConfig = Field(default_factory=ThreadsConfig)
    hot_topics: HotTopicsConfig = Field(default_factory=HotTopicsConfig)
    rss: RssConfig = Field(default_factory=RssConfig)
    filter: FilterConfig = Field(default_factory=FilterConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    openrouter: OpenRouterConfig = Field(default_factory=OpenRouterConfig)
    speak: SpeakConfig = Field(default_factory=SpeakConfig)
