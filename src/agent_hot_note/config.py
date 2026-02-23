from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TopicDomainProfile(BaseModel):
    primary: list[str] = []
    secondary: list[str] = []
    extract_allowed: list[str] = []


def _default_topic_domain_profiles() -> dict[str, TopicDomainProfile]:
    return {
        "general": TopicDomainProfile(
            primary=["xiaohongshu.com"],
            secondary=["zhihu.com", "bilibili.com"],
            extract_allowed=["xiaohongshu.com", "zhihu.com", "bilibili.com"],
        ),
        "job": TopicDomainProfile(
            primary=["bosszhipin.com"],
            secondary=["liepin.com", "51job.com", "zhaopin.com", "lagou.com", "kanzhun.com"],
            extract_allowed=["bosszhipin.com", "liepin.com", "51job.com", "zhaopin.com", "lagou.com", "kanzhun.com"],
        ),
        "finance": TopicDomainProfile(
            primary=["eastmoney.com"],
            secondary=["10jqka.com.cn", "stcn.com", "cnstock.com"],
            extract_allowed=["eastmoney.com", "10jqka.com.cn", "stcn.com", "cnstock.com"],
        ),
    }


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.deepseek.com", alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="deepseek-chat", alias="OPENAI_MODEL")
    llm_timeout_seconds: float = Field(default=60.0, alias="LLM_TIMEOUT_SECONDS")
    llm_num_retries: int = Field(default=1, alias="LLM_NUM_RETRIES")

    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")
    tavily_search_depth: str = Field(default="advanced", alias="TAVILY_SEARCH_DEPTH")
    tavily_max_results: int = Field(default=8, alias="TAVILY_MAX_RESULTS")

    search_context_results: int = Field(default=5, alias="SEARCH_CONTEXT_RESULTS")
    search_title_chars: int = Field(default=80, alias="SEARCH_TITLE_CHARS")
    search_content_chars: int = Field(default=260, alias="SEARCH_CONTENT_CHARS")
    tavily_title_chars: int = Field(default=60, alias="TAVILY_TITLE_CHARS")
    fallback_min_results: int = Field(default=2, alias="FALLBACK_MIN_RESULTS")
    fallback_min_avg_summary_chars: int = Field(default=30, alias="FALLBACK_MIN_AVG_SUMMARY_CHARS")
    fallback_max_title_dup_ratio: float = Field(default=0.5, alias="FALLBACK_MAX_TITLE_DUP_RATIO")
    fallback_primary_domains: str = Field(default="xiaohongshu.com", alias="FALLBACK_PRIMARY_DOMAINS")
    fallback_secondary_domains: str = Field(default="zhihu.com,bilibili.com", alias="FALLBACK_SECONDARY_DOMAINS")
    tavily_extract_enabled: bool = Field(default=True, alias="TAVILY_EXTRACT_ENABLED")
    tavily_extract_max_urls: int = Field(default=2, alias="TAVILY_EXTRACT_MAX_URLS")
    tavily_extract_allowed_domains: str = Field(
        default="xiaohongshu.com,zhihu.com,bilibili.com",
        alias="TAVILY_EXTRACT_ALLOWED_DOMAINS",
    )
    topic_default_profile: str = Field(default="general", alias="TOPIC_DEFAULT_PROFILE")
    topic_domain_profiles: dict[str, TopicDomainProfile] = Field(
        default_factory=_default_topic_domain_profiles,
        alias="TOPIC_DOMAIN_PROFILES",
    )

    def model_post_init(self, __context: Any) -> None:  # type: ignore[override]
        normalized: dict[str, TopicDomainProfile] = {}
        for key, profile in self.topic_domain_profiles.items():
            profile_id = str(key).strip().lower()
            if not profile_id:
                continue
            if isinstance(profile, TopicDomainProfile):
                normalized[profile_id] = profile
                continue
            if isinstance(profile, Mapping):
                normalized[profile_id] = TopicDomainProfile.model_validate(profile)
        self.topic_domain_profiles = normalized or _default_topic_domain_profiles()
        self.topic_default_profile = self.topic_default_profile.strip().lower() or "general"
        if self.topic_default_profile not in self.topic_domain_profiles:
            self.topic_default_profile = "general"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
