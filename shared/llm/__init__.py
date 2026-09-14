"""LLM provider seam: protocol, frozen types, config, factory, and adapters."""

from shared.llm.config import LLMProviderConfig, resolve_config
from shared.llm.errors import (
    CredentialMissingError,
    ProviderError,
    ProviderUnavailableError,
    SchemaMismatchError,
)
from shared.llm.factory import create_provider
from shared.llm.fake import FakeLLM
from shared.llm.groq import GroqProvider
from shared.llm.openai_compatible import OpenAICompatibleProvider
from shared.llm.provider import LLMProvider, validate_structured_output
from shared.llm.replay import ReplayProvider
from shared.llm.types import InvestigationPrompt, ModelMetadata, ProviderCallLog, ProviderHealth

__all__ = [
    "CredentialMissingError",
    "FakeLLM",
    "GroqProvider",
    "InvestigationPrompt",
    "LLMProvider",
    "LLMProviderConfig",
    "ModelMetadata",
    "OpenAICompatibleProvider",
    "ProviderCallLog",
    "ProviderError",
    "ProviderHealth",
    "ProviderUnavailableError",
    "ReplayProvider",
    "SchemaMismatchError",
    "create_provider",
    "resolve_config",
    "validate_structured_output",
]
