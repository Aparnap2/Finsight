"""Tests for shared.llm.config and shared.llm.factory.

All tests are deterministic: no network, no real LLM calls.
"""

from __future__ import annotations

import pytest

from shared.llm.config import LLMProviderConfig, resolve_config
from shared.llm.factory import create_provider
from shared.llm.openai_compatible import OpenAICompatibleProvider


class TestLLMProviderConfig:
    """LLMProviderConfig is a frozen dataclass."""

    def test_frozen(self) -> None:
        cfg = LLMProviderConfig(provider="groq", base_url="https://x", api_key="k", model="m")
        with pytest.raises(AttributeError):
            cfg.provider = "other"  # type: ignore[misc]

    def test_provider_label(self) -> None:
        cfg = LLMProviderConfig(provider="groq", base_url="https://x", api_key="k", model="m")
        assert cfg.provider_label == "groq"


class TestResolveConfig:
    """resolve_config merges explicit args + env + defaults."""

    def test_groq_defaults(self) -> None:
        cfg = resolve_config(_env={})
        assert cfg.provider == "groq"
        assert cfg.base_url == "https://api.groq.com/openai/v1"
        assert cfg.model == "openai/gpt-oss-20b"

    def test_explicit_provider(self) -> None:
        cfg = resolve_config(provider="openrouter", _env={})
        assert cfg.provider == "openrouter"
        assert cfg.base_url == "https://openrouter.ai/api/v1"

    def test_explicit_args_override(self) -> None:
        cfg = resolve_config(
            provider="groq",
            base_url="https://custom.example.com/v1",
            api_key="test-key",
            model="my-model",
            _env={},
        )
        assert cfg.base_url == "https://custom.example.com/v1"
        assert cfg.api_key == "test-key"
        assert cfg.model == "my-model"

    def test_env_overrides(self) -> None:
        cfg = resolve_config(
            _env={
                "LLM_PROVIDER": "openai",
                "LLM_BASE_URL": "https://custom.openai.com/v1",
                "LLM_API_KEY": "sk-env",
                "LLM_CHAT_MODEL": "gpt-4o",
            }
        )
        assert cfg.provider == "openai"
        assert cfg.base_url == "https://custom.openai.com/v1"
        assert cfg.api_key == "sk-env"
        assert cfg.model == "gpt-4o"

    def test_provider_specific_key_env(self) -> None:
        cfg = resolve_config(_env={"GROQ_API_KEY": "gsk-test"})
        assert cfg.api_key == "gsk-test"

    def test_infer_provider_from_key(self) -> None:
        cfg = resolve_config(_env={"OPENROUTER_API_KEY": "or-key"})
        assert cfg.provider == "openrouter"
        assert cfg.api_key == "or-key"

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            resolve_config(provider="nonexistent", _env={})

    def test_timeout_from_env(self) -> None:
        cfg = resolve_config(_env={"LLM_TIMEOUT_S": "60"})
        assert cfg.timeout_s == 60.0

    def test_retries_capped_at_3(self) -> None:
        cfg = resolve_config(_env={"LLM_MAX_RETRIES": "10"})
        assert cfg.max_retries == 3

    def test_trailing_slash_stripped(self) -> None:
        cfg = resolve_config(base_url="https://x.com/v1/", _env={})
        assert cfg.base_url == "https://x.com/v1"


class TestCreateProvider:
    """create_provider returns the right implementation."""

    def test_returns_openai_compatible(self) -> None:
        provider = create_provider(provider="groq", api_key="test", _env={})
        assert isinstance(provider, OpenAICompatibleProvider)

    def test_explicit_config(self) -> None:
        cfg = LLMProviderConfig(provider="groq", base_url="https://x", api_key="k", model="m")
        provider = create_provider(config=cfg)
        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.config is cfg

    def test_model_metadata(self) -> None:
        provider = create_provider(provider="groq", model="test-model", api_key="k", _env={})
        meta = provider.model_metadata()
        assert meta.provider == "groq"
        assert meta.model == "test-model"
