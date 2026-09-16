"""PII/secrets redaction — retained/redacted/hashed/excluded per hop.

P5-06: sensitive data travelling provider → adapter → canonical →
evidence → context → LLM → traces → logs → audit is classified per hop:

- **excluded**: never persisted, never sent (raw secrets, API keys).
- **redacted**: replaced with ``[REDACTED]`` (or ``[REDACTED_EMAIL]``)
  in logs, traces, and audit payloads.
- **hashed**: sha256 (with tenant scope) for PII that must remain
  joinable without revealing values.
- **retained**: only tenant-safe ids (correlation/tenant/case) and
  non-sensitive metadata.

Pure stdlib helpers; no imports from ``apps/``, ``agents/``,
or ``finance/``. Every redactor is total (never raises on odd input).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

REDACTED: str = "[REDACTED]"
REDACTED_EMAIL: str = "[REDACTED_EMAIL]"
REDACTED_SECRET: str = "[REDACTED_SECRET]"

_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|secret|password|passwd|pwd|token|bearer|session[_-]?key"
    r"|authori[zs]ation|cookie|set[_-]?cookie|x[_-]?api[_-]?key)",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_BEARER_VALUE_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_SK_VALUE_RE = re.compile(r"\bsk[_-][A-Za-z0-9_-]{8,}\b")


def _is_secret_key(key: str) -> bool:
    """Return True when a mapping key names a secret-bearing field."""
    return bool(_SECRET_KEY_RE.search(key))


def redact_value(key: str, value: Any) -> Any:
    """Redact one mapping value when its key names a secret.

    Non-string values under secret keys collapse to ``[REDACTED]``;
    everything else passes through untouched.
    """
    if _is_secret_key(key):
        return REDACTED
    return value


def redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``data`` with secret-keyed values redacted.

    Shallow: nested dicts are redacted one level deep; lists of dicts
    are handled element-wise. The input is never mutated.
    """
    def _redact_scalar(key: str, value: Any) -> Any:
        if _is_secret_key(key):
            return REDACTED
        if isinstance(value, str) and _looks_like_secret_value(value):
            return REDACTED_SECRET
        return value

    redacted: dict[str, Any] = {}
    for key, value in data.items():
        if _is_secret_key(key):
            redacted[key] = REDACTED
        elif isinstance(value, dict):
            redacted[key] = {k: _redact_scalar(k, v) for k, v in value.items()}
        elif isinstance(value, list):
            redacted[key] = [
                (
                    {k: _redact_scalar(k, v) for k, v in item.items()}
                    if isinstance(item, dict)
                    else item
                )
                for item in value
            ]
        else:
            redacted[key] = _redact_scalar(key, value)
    return redacted


def scrub_text(text: str) -> str:
    """Scrub secrets and emails from free text (logs, prompts, traces).

    Replaces bearer tokens, ``sk-`` style keys, emails, and
    ``key = value`` secret assignments with redaction markers.
    """
    if not text:
        return text
    scrubbed = _BEARER_VALUE_RE.sub(r"\1" + REDACTED, text)
    scrubbed = _SK_VALUE_RE.sub(REDACTED_SECRET, scrubbed)
    scrubbed = _EMAIL_RE.sub(REDACTED_EMAIL, scrubbed)
    return scrubbed


def hash_pii(value: str, *, tenant_id: str) -> str:
    """Return tenant-scoped sha256 hex for a PII value.

    The tenant scope prevents cross-tenant join correlation of hashes.
    Empty values hash deterministically without raising.
    """
    scoped = f"{tenant_id}:{(value or '').strip().lower()}"
    return hashlib.sha256(scoped.encode()).hexdigest()


def _looks_like_secret_value(value: str) -> bool:
    """Return True when a string value itself looks like a credential."""
    if not value or not isinstance(value, str):
        return False
    if _SK_VALUE_RE.search(value):
        return True
    match = _BEARER_VALUE_RE.search(value)
    return bool(match and REDACTED not in value)


def contains_secret_literal(text: str) -> bool:
    """Return True when text appears to carry an unredacted secret literal."""
    if not text:
        return False
    lowered = text.lower()
    if ("sk-" in lowered or "sk_" in lowered) and _SK_VALUE_RE.search(text):
        return True
    return bool(_BEARER_VALUE_RE.search(text) and "redacted" not in lowered)
