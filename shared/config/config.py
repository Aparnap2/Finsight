"""Application settings loaded from environment variables only."""

import json
import logging
from functools import lru_cache

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    postgres_uri: str = "postgresql://finsight:finsight@localhost:5432/finsight"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    redis_url: str = "redis://localhost:6380/0"
    openai_api_key: str = "sk-placeholder"
    litellm_proxy_url: str | None = None
    default_llm_model: str = "poolside/laguna-m.1"
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_chat_model: str = "llama-3.3-70b-versatile"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_chat_model: str = "meta-llama/llama-3.1-8b-instruct:free"
    poolside_api_key: str = ""
    poolside_base_url: str = "https://inference.poolside.ai/v1"
    poolside_chat_model: str = "poolside/laguna-m.1"
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"
    app_env: str = "development"
    log_level: str = "INFO"
    stripe_webhook_secret: str = ""
    stripe_tenant_map: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def stripe_tenant_mapping(self) -> dict[str, object]:
        """Parse the trusted stripe_account -> tenant_id map (env-only).

        The ``STRIPE_TENANT_MAP`` env var holds a JSON object such as
        ``{"acct_123": "tenant-acme"}``. Values are normally tenant-id
        strings; a list value marks the account as ambiguous. Returns an
        empty mapping when unset; logs a warning and returns empty when
        the JSON is invalid (callers then quarantine every delivery
        instead of guessing a tenant).
        """
        raw = self.stripe_tenant_map.strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("STRIPE_TENANT_MAP is not valid JSON; using empty map.")
            return {}
        if not isinstance(parsed, dict):
            logger.warning("STRIPE_TENANT_MAP must be a JSON object; using empty map.")
            return {}
        return parsed


@lru_cache
def get_settings() -> Settings:
    return Settings()
