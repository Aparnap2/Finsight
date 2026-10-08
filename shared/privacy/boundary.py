"""Purpose-gated LLM context authorization (P10-03).

Single choke point between raw source data and provider-bound prompts.
Unlike :mod:`shared.privacy.sanitize` (which redacts unknowns and
continues), this gate DENIES: secrets, unclassified non-structural
values, financial data for non-financial purposes, and cross-tenant
data never reach prompt construction — they raise
:class:`PolicyDeniedError`. The model is never the privacy control, and
untrusted free text cannot alter enforcement (authorization is
structural, never instruction-following).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from shared.privacy.inventory import DataClassification
from shared.safety.secrets import hash_pii

__all__ = [
    "FINANCIAL_PURPOSES",
    "PolicyDeniedError",
    "Purpose",
    "authorize_llm_context",
]


class PolicyDeniedError(Exception):
    """Raised when data may not enter LLM context under the given purpose."""


class Purpose(StrEnum):
    """Closed purpose vocabulary: purpose is authorization input."""

    COMMENTARY = "commentary"
    ROOT_CAUSE = "root_cause"
    REASONING = "reasoning"
    WORKFLOW = "workflow"
    INVESTIGATION = "investigation"


FINANCIAL_PURPOSES: frozenset[Purpose] = frozenset(
    {Purpose.COMMENTARY, Purpose.ROOT_CAUSE, Purpose.REASONING}
)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{8,}\d")
_SK_VALUE_RE = re.compile(r"\bsk[_-][A-Za-z0-9_-]{8,}\b")
_BEARER_VALUE_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|secret|password|passwd|pwd|token|bearer|session[_-]?key"
    r"|authori[zs]ation|cookie|set[_-]?cookie|x[_-]?api[_-]?key|credential"
    r"|access[_-]?key|private[_-]?key)",
    re.IGNORECASE,
)


def _is_secret_credential(value: str) -> bool:
    """Return True when the whole value is a credential."""
    return bool(_SK_VALUE_RE.fullmatch(value) or _BEARER_VALUE_RE.fullmatch(value))


def _scrub_inline(text: str, tenant_id: str) -> str:
    """Replace PII shapes inside free text with tenant tokens.

    Secrets become markers (never tokenized: a token is still an oracle);
    emails and phones become tenant-scoped hash tokens so coreference
    across mentions survives without disclosing values.
    """
    scrubbed = _BEARER_VALUE_RE.sub("[REDACTED_SECRET]", text)
    scrubbed = _SK_VALUE_RE.sub("[REDACTED_SECRET]", scrubbed)

    def _tokenize_email(match: re.Match[str]) -> str:
        return hash_pii(match.group(0), tenant_id=tenant_id)

    def _tokenize_phone(match: re.Match[str]) -> str:
        return hash_pii(match.group(0), tenant_id=tenant_id)

    scrubbed = _EMAIL_RE.sub(_tokenize_email, scrubbed)
    return _PHONE_RE.sub(_tokenize_phone, scrubbed)


def _deny_if_forbidden(
    key: str,
    value: Any,
    classification: DataClassification | None,
    *,
    purpose: Purpose,
) -> None:
    """Raise PolicyDeniedError for any field that may not enter LLM context."""
    if classification is DataClassification.SECRET:
        raise PolicyDeniedError(f"secret field denied: {key}")
    if _SECRET_KEY_RE.search(key):
        raise PolicyDeniedError(f"secret-named field denied: {key}")
    if isinstance(value, str) and _is_secret_credential(value):
        raise PolicyDeniedError(f"credential value denied: {key}")
    if classification is None:
        raise PolicyDeniedError(f"unclassified field denied: {key}")
    if (
        classification is DataClassification.FINANCIAL_SENSITIVE
        and purpose not in FINANCIAL_PURPOSES
    ):
        raise PolicyDeniedError(f"financial field denied for purpose {purpose.value}: {key}")


def _walk(
    key: str,
    value: Any,
    classification: DataClassification | None,
    *,
    tenant_id: str,
    purpose: Purpose,
    free_text_fields: frozenset[str],
    normalized: dict[str, DataClassification],
) -> Any:
    """Recurse one value: deny first, then transform (never mutates input)."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, dict):
        return {
            sub_key: _walk(
                sub_key,
                sub_value,
                normalized.get(sub_key, classification),
                tenant_id=tenant_id,
                purpose=purpose,
                free_text_fields=free_text_fields,
                normalized=normalized,
            )
            for sub_key, sub_value in value.items()
        }
    if isinstance(value, list):
        return [
            _walk(
                key,
                item,
                classification,
                tenant_id=tenant_id,
                purpose=purpose,
                free_text_fields=free_text_fields,
                normalized=normalized,
            )
            for item in value
        ]
    _deny_if_forbidden(key, value, classification, purpose=purpose)
    if classification is DataClassification.PERSONAL:
        if key in free_text_fields and isinstance(value, str):
            return _scrub_inline(value, tenant_id)
        return hash_pii(str(value), tenant_id=tenant_id)
    if classification is DataClassification.FINANCIAL_SENSITIVE:
        return value
    if isinstance(value, str):
        return _scrub_inline(value, tenant_id)
    return value


def authorize_llm_context(
    data: Mapping[str, Any],
    *,
    purpose: str,
    tenant_id: str,
    data_tenant_id: str,
    classifications: Mapping[str, DataClassification] | None = None,
    free_text_fields: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Authorize and transform raw data into provider-safe prompt context.

    Args:
        data: Raw source mapping (never mutated).
        purpose: Closed purpose vocabulary value (authorization input).
        tenant_id: Calling tenant; blank rejected.
        data_tenant_id: Owning tenant of the data; mismatch denied.
        classifications: Field-name to classification map.
        free_text_fields: Fields scrubbed inline instead of whole-tokenized.

    Returns:
        New mapping safe for prompt construction under the purpose.

    Raises:
        ValueError: Blank tenant or unknown purpose (programmer errors).
        PolicyDeniedError: Secrets, unclassified non-structural values,
            financial data for non-financial purposes, tenant mismatch.
    """
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("tenant_id must be a non-empty string")
    if not isinstance(data_tenant_id, str) or not data_tenant_id.strip():
        raise ValueError("data_tenant_id must be a non-empty string")
    try:
        resolved = Purpose(purpose)
    except ValueError as exc:
        raise ValueError(f"unknown purpose {purpose!r}") from exc
    if data_tenant_id != tenant_id:
        raise PolicyDeniedError(f"cross-tenant context denied: {data_tenant_id!r}")
    normalized: dict[str, DataClassification] = {}
    for field_name, classification in (classifications or {}).items():
        if not isinstance(classification, DataClassification):
            raise ValueError(f"classification for {field_name!r} must be a DataClassification")
        normalized[field_name] = classification
    return {
        key: _walk(
            key,
            value,
            normalized.get(key),
            tenant_id=tenant_id,
            purpose=resolved,
            free_text_fields=free_text_fields,
            normalized=normalized,
        )
        for key, value in data.items()
    }
