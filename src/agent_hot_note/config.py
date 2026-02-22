from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.deepseek.com", alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="deepseek-chat", alias="OPENAI_MODEL")
    llm_timeout_seconds: float = Field(default=60.0, alias="LLM_TIMEOUT_SECONDS")
    llm_num_retries: int = Field(default=1, alias="LLM_NUM_RETRIES")

    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")
    tavily_search_depth: str = Field(default="advanced", alias="TAVILY_SEARCH_DEPTH")
    tavily_max_results: int = Field(default=5, alias="TAVILY_MAX_RESULTS")

    otel_sdk_disabled: bool = Field(default=True, alias="OTEL_SDK_DISABLED")
    crewai_storage_dir: str = Field(default=".crewai", alias="CREWAI_STORAGE_DIR")

    search_context_results: int = Field(default=3, alias="SEARCH_CONTEXT_RESULTS")
    search_title_chars: int = Field(default=40, alias="SEARCH_TITLE_CHARS")
    search_content_chars: int = Field(default=120, alias="SEARCH_CONTENT_CHARS")
    tavily_title_chars: int = Field(default=30, alias="TAVILY_TITLE_CHARS")
    fallback_min_results: int = Field(default=2, alias="FALLBACK_MIN_RESULTS")
    fallback_min_avg_summary_chars: int = Field(default=30, alias="FALLBACK_MIN_AVG_SUMMARY_CHARS")
    fallback_max_title_dup_ratio: float = Field(default=0.5, alias="FALLBACK_MAX_TITLE_DUP_RATIO")
    fallback_primary_domains: str = Field(default="xiaohongshu.com", alias="FALLBACK_PRIMARY_DOMAINS")
    fallback_secondary_domains: str = Field(default="zhihu.com,bilibili.com", alias="FALLBACK_SECONDARY_DOMAINS")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
