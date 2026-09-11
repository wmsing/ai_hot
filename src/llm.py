"""LLM provider 解析：ollama（默认）或 openrouter。"""

from __future__ import annotations

import os
from typing import Literal

from src.models import AppConfig, LlmRuntime, OllamaConfig

Provider = Literal["ollama", "openrouter"]


def resolve_provider(flag: str | None, config: AppConfig) -> Provider:
    """优先级：LLM_PROVIDER 环境变量 > --llm 暗示 > config.llm.provider。"""
    env = os.getenv("LLM_PROVIDER", "").strip().lower()
    if env in {"ollama", "openrouter"}:
        return env  # type: ignore[return-value]
    if flag is not None:
        fl = flag.strip().lower()
        if fl in {"openrouter", "or"}:
            return "openrouter"
        if "/" in flag.strip() or fl.endswith(":free"):
            return "openrouter"
    return config.llm.provider


def resolve_llm_model(
    flag: str | None,
    config: AppConfig,
    *,
    provider: Provider | None = None,
) -> str | None:
    """解析 --llm：None=模式A（不摘要）；有值=模式B 模型名。"""
    if flag is None:
        return None
    prov = provider if provider is not None else resolve_provider(flag, config)
    normalized = flag.strip().lower()
    if normalized in {"", "qwen", "1", "true", "yes", "on"}:
        return _default_model(config, prov)
    if normalized in {"openrouter", "or"}:
        return config.openrouter.model
    return flag.strip()


def build_llm_runtime(
    config: AppConfig,
    *,
    provider: Provider | None = None,
    model: str | None = None,
    api_key: str = "",
) -> LlmRuntime:
    """构造一次调用用的 runtime（翻译/摘要共用）。"""
    prov = provider if provider is not None else resolve_provider(None, config)
    if prov == "openrouter":
        key = api_key or os.getenv("OPENROUTER_API_KEY", "").strip()
        if not key:
            raise ValueError(
                "OPENROUTER_API_KEY is required when llm.provider=openrouter"
            )
        return LlmRuntime(
            provider="openrouter",
            model=model or config.openrouter.model,
            base_url=config.openrouter.base_url,
            timeout_seconds=config.openrouter.timeout_seconds,
            api_key=key,
            http_referer=config.site.base_url.rstrip("/"),
            app_title=config.openrouter.app_title,
            fallback_model=config.openrouter.fallback_model,
        )
    return LlmRuntime(
        provider="ollama",
        model=model or config.ollama.model,
        base_url=config.ollama.base_url,
        timeout_seconds=config.ollama.timeout_seconds,
    )


def runtime_from_ollama(ollama: OllamaConfig) -> LlmRuntime:
    """测试/旧调用兼容：OllamaConfig → LlmRuntime。"""
    return LlmRuntime(
        provider="ollama",
        model=ollama.model,
        base_url=ollama.base_url,
        timeout_seconds=ollama.timeout_seconds,
    )


def _default_model(config: AppConfig, provider: Provider) -> str:
    if provider == "openrouter":
        return config.openrouter.model
    return config.ollama.model
