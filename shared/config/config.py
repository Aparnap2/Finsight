"""Application settings loaded from environment variables only."""

import json
import logging
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

#: SQLAlchemy only ships a psycopg 2 dialect for the bare ``postgresql://``
#: scheme. psycopg 2 is not installed here, so a bare DSN raised
#: ``ModuleNotFoundError`` at engine creation. The runtime and migration DSNs
#: are normalized to the psycopg 3 dialect at the configuration boundary.
BARE_POSTGRES_SCHEMES = frozenset({"postgres", "postgresql"})
PSYCOPG_SCHEME = "postgresql+psycopg"


def normalize_postgres_dsn(uri: str) -> str:
    """Add the psycopg 3 driver to a bare PostgreSQL DSN.

    Only the scheme is rewritten, so credentials, host, port, database name,
    query parameters, and percent-encoding pass through byte-for-byte. A DSN
    that already names a driver (``postgresql+asyncpg://``,
    ``postgresql+psycopg2://``) is returned untouched: choosing a driver is a
    deployment decision, not something this function should silently override.
    Non-PostgreSQL URLs (``sqlite://``) and empty strings are also untouched.
    """
    scheme, separator, remainder = uri.partition("://")
    if not separator or scheme.lower() not in BARE_POSTGRES_SCHEMES:
        return uri
    return f"{PSYCOPG_SCHEME}://{remainder}"


class Settings(BaseSettings):
    postgres_uri: str = "postgresql+psycopg://finsight:finsight@localhost:5432/finsight"
    #: Separate migration URI (Slice 3: migration role != runtime role).
    #: Empty means migrations use ``postgres_uri`` (dev default).
    migration_postgres_uri: str = ""
    #: Bounded pool (Slice 3: connection-pool sizing is a reliability control).
    db_pool_size: int = 5
    db_pool_max_overflow: int = 5
    db_pool_timeout_s: float = 10.0
    #: Statement timeout applied per connection (milliseconds, 0 = unset).
    db_statement_timeout_ms: int = 30_000
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    redis_url: str = "redis://localhost:6380/0"
    openai_api_key: str = "sk-placeholder"
    litellm_proxy_url: str | None = None
    default_llm_model: str = "poolside/laguna-m.1"
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_chat_model: str = "openai/gpt-oss-20b"
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
    #: UI-1 demo-only console identity (environment only, never committed).
    #: Empty means the operator console renders unconfigured instead of
    #: guessing headers. Production must never set these.
    operator_console_demo_tenant_id: str = ""
    operator_console_demo_role: str = ""
    operator_console_demo_user_id: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @field_validator("postgres_uri", "migration_postgres_uri", mode="before")
    @classmethod
    def _normalize_postgres_dsn(cls, value: object) -> object:
        """Normalize both DSN fields so an env-supplied bare DSN still works.

        ``migration_postgres_uri`` is empty by default, meaning "use the
        runtime DSN"; empty stays empty so that fallback keeps working.
        """
        return normalize_postgres_dsn(value) if isinstance(value, str) else value

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
