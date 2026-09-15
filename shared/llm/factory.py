"""LLM provider factory: create providers from config, no code changes needed.

Usage::

    from shared.llm.factory import create_provider

    # From env vars (LLM_PROVIDER, LLM_API_KEY, etc.)
    provider = create_provider()

    # Explicit config
    provider = create_provider(provider="openrouter", model="anthropic/claude-3.5-sonnet")

    # From a pre-built config
    from shared.llm.config import resolve_config
    config = resolve_config(provider="groq")
    provider = create_provider(config=config)
"""

from __future__ import annotations

from shared.llm.config import LLMProviderConfig, resolve_config
from shared.llm.fake import FakeLLM
from shared.llm.openai_compatible import OpenAICompatibleProvider
from shared.llm.provider import LLMProvider


def create_provider(
    config: LLMProviderConfig | None = None,
    *,
    provider: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    timeout_s: float | None = None,
    max_retries: int | None = None,
    _env: dict[str, str] | None = None,
) -> LLMProvider:
    """Create an LLM provider from config or env vars.

    If ``config`` is provided, it is used directly.
    Otherwise, config is resolved from the explicit args + env vars + defaults.

    Args:
        config: Pre-resolved config (optional).
        provider: Provider name override.
        base_url: Base URL override.
        api_key: API key override.
        model: Model override.
        timeout_s: Timeout override.
        max_retries: Max retries override.
        _env: Env dict for testing (defaults to ``os.environ``).

    Returns:
        An :class:`LLMProvider` implementation.
    """
    if config is None:
        config = resolve_config(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout_s=timeout_s,
            max_retries=max_retries,
            _env=_env,
        )
    return OpenAICompatibleProvider(config)


def create_fake_provider() -> FakeLLM:
    """Create a deterministic FakeLLM for testing (zero network)."""
    return FakeLLM()
