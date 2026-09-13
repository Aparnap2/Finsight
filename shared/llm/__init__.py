"""LLM provider seam: protocol, frozen types, and thin direct providers."""

from shared.llm.errors import (
    CredentialMissingError,
    ProviderError,
    ProviderUnavailableError,
    SchemaMismatchError,
)
from shared.llm.fake import FakeLLM
from shared.llm.groq import GroqProvider
from shared.llm.provider import LLMProvider, validate_structured_output
from shared.llm.types import InvestigationPrompt, ModelMetadata, ProviderCallLog, ProviderHealth

__all__ = [
    "CredentialMissingError",
    "FakeLLM",
    "GroqProvider",
    "InvestigationPrompt",
    "LLMProvider",
    "ModelMetadata",
    "ProviderCallLog",
    "ProviderError",
    "ProviderHealth",
    "ProviderUnavailableError",
    "SchemaMismatchError",
    "validate_structured_output",
]
