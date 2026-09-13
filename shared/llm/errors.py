"""Provider error hierarchy for the FinSight LLM boundary.

All errors are credential-safe by construction: they carry only redacted
messages and never embed API keys, secrets, or auth headers.
"""

from __future__ import annotations


class ProviderError(Exception):
    """Base class for all LLM provider failures."""


class ProviderUnavailableError(ProviderError):
    """Transport-level failure: timeout, 5xx, or unhealthy provider."""


class SchemaMismatchError(ProviderError):
    """Structured output failed strict boundary validation."""


class CredentialMissingError(ProviderError):
    """No credential available via environment/config (never holds the key)."""
