"""配置：config.yaml（非密钥）+ .env（密钥/环境）。"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from src.models import AppConfig

load_dotenv()

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG_PATH = _ROOT / "config.yaml"


class Settings(BaseModel):
    """运行时环境变量（密钥与环境名）。"""

    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")
    api_key: str = Field(default="")
    openrouter_api_key: str = Field(default="")
    llm_provider: str = Field(default="")


def load_settings() -> Settings:
    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        api_key=os.getenv("API_KEY", ""),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        llm_provider=os.getenv("LLM_PROVIDER", ""),
    )


def load_app_config(path: Path | None = None) -> AppConfig:
    """从 YAML 加载业务配置。"""
    config_path = path or Path(os.getenv("AI_HOT_CONFIG", str(_DEFAULT_CONFIG_PATH)))
    if not config_path.is_file():
        raise FileNotFoundError(f"config not found: {config_path}")
    with config_path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return AppConfig.model_validate(raw)


settings = load_settings()
