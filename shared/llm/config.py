"""LLM provider configuration: env-driven, swappable, single source of truth.

Any OpenAI-compatible endpoint (Groq, OpenRouter, vLLM, Ollama, etc.) is
supported by setting ``LLM_PROVIDER`` and the matching ``*_API_KEY`` /
``*_BASE_URL`` / ``*_CHAT_MODEL`` env vars.  No code changes required.

Environment variables:

    LLM_PROVIDER        — provider name: "groq" | "openrouter" | "openai" | "ollama"
    LLM_BASE_URL        — override base URL (optional, provider-specific default)
    LLM_API_KEY         — override API key (optional, provider-specific default)
    LLM_CHAT_MODEL      — override model (optional, provider-specific default)
    LLM_TIMEOUT_S       — per-attempt timeout in seconds (default 30)
    LLM_MAX_RETRIES     — max attempts, capped at 3 (default 3)

Provider-specific fallbacks (when LLM_* is unset):

    GROQ_API_KEY / GROQ_BASE_URL / GROQ_CHAT_MODEL
    OPENROUTER_API_KEY / OPENROUTER_BASE_URL / OPENROUTER_CHAT_MODEL
    OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_CHAT_MODEL
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

# Provider-specific defaults ------------------------------------------------

_PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-20b",
        "key_env": "GROQ_API_KEY",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "meta-llama/llama-3.1-8b-instruct:free",
        "key_env": "OPENROUTER_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "key_env": "OPENAI_API_KEY",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "llama3.2",
        "key_env": "OLLAMA_API_KEY",
    },
}

_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class LLMProviderConfig:
    """Resolved provider configuration.  Immutable after construction."""

    provider: str
    base_url: str
    api_key: str
    model: str
    timeout_s: float = _DEFAULT_TIMEOUT_S
    max_retries: int = _DEFAULT_MAX_ATTEMPTS

    @property
    def provider_label(self) -> str:
        """Short label for audit logs (no secrets)."""
        return self.provider


def resolve_config(
    *,
    provider: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    timeout_s: float | None = None,
    max_retries: int | None = None,
    _env: dict[str, str] | None = None,
) -> LLMProviderConfig:
    """Resolve provider config from explicit args + env vars + defaults.

    Resolution order (first non-empty wins):

        1. Explicit argument
        2. ``LLM_*`` env vars (``LLM_PROVIDER``, ``LLM_BASE_URL``, etc.)
        3. Provider-specific env vars (``GROQ_API_KEY``, etc.)
        4. Provider-specific defaults from ``_PROVIDER_DEFAULTS``

    Args:
        provider: Provider name override (``"groq"``, ``"openrouter"``, etc.).
        base_url: Base URL override.
        api_key: API key override.
        model: Model override.
        timeout_s: Per-attempt timeout override.
        max_retries: Max attempts override.
        _env: Env dict for testing (defaults to ``os.environ``).

    Returns:
        A frozen :class:`LLMProviderConfig`.
    """
    import os

    env = _env if _env is not None else os.environ

    # 1. Resolve provider name
    resolved_provider = (
        (provider or env.get("LLM_PROVIDER", "") or _infer_provider_from_key(env) or "groq")
        .lower()
        .strip()
    )

    if resolved_provider not in _PROVIDER_DEFAULTS:
        raise ValueError(
            f"Unknown LLM provider {resolved_provider!r}. Supported: {sorted(_PROVIDER_DEFAULTS)}"
        )

    defaults = _PROVIDER_DEFAULTS[resolved_provider]

    # 2. Resolve base_url
    resolved_base_url = (
        base_url
        or env.get("LLM_BASE_URL", "")
        or env.get(f"{resolved_provider.upper()}_BASE_URL", "")
        or defaults["base_url"]
    ).rstrip("/")

    # 3. Resolve api_key
    resolved_api_key = api_key or env.get("LLM_API_KEY", "") or env.get(defaults["key_env"], "")

    # 4. Resolve model
    resolved_model = (
        model
        or env.get("LLM_CHAT_MODEL", "")
        or env.get(f"{resolved_provider.upper()}_CHAT_MODEL", "")
        or defaults["model"]
    )

    # 5. Resolve numeric settings
    resolved_timeout = _DEFAULT_TIMEOUT_S
    if timeout_s is not None:
        resolved_timeout = timeout_s
    elif env.get("LLM_TIMEOUT_S", ""):
        resolved_timeout = float(env["LLM_TIMEOUT_S"])

    resolved_retries = _DEFAULT_MAX_ATTEMPTS
    if max_retries is not None:
        resolved_retries = max_retries
    elif env.get("LLM_MAX_RETRIES", ""):
        resolved_retries = int(env["LLM_MAX_RETRIES"])

    return LLMProviderConfig(
        provider=resolved_provider,
        base_url=resolved_base_url,
        api_key=resolved_api_key,
        model=resolved_model,
        timeout_s=resolved_timeout,
        max_retries=min(resolved_retries, _DEFAULT_MAX_ATTEMPTS),
    )


def _infer_provider_from_key(env: Mapping[str, str]) -> str | None:
    """Infer provider from which API key env var is set."""
    if env.get("GROQ_API_KEY", ""):
        return "groq"
    if env.get("OPENROUTER_API_KEY", ""):
        return "openrouter"
    if env.get("OPENAI_API_KEY", ""):
        return "openai"
    return None
