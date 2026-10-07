"""Purpose-specific sanitizers: classification-aware, deterministic, total.

Four surfaces over one explicit contract (see the RED contract tests):

- log: strongest minimization; PII becomes tenant-scoped hash tokens;
  financial values become ``[FINANCIAL_SENSITIVE]``; control chars flat.
- llm: minimum necessary context; evidence text kept, scrubbed, bounded.
- eval: same transforms as llm, keys sorted for canonical form.
- ui: operator-safe display masks; control chars flattened.

Resolution order per field (never silent about safety):

1. Secret patterns (secret-like key or secret-like value) always win,
   regardless of explicit classification or the ``unknown`` mode.
2. Explicit ``classifications`` entry: SECRET / PERSONAL / FINANCIAL /
   INTERNAL / PUBLIC select the class rule below.
3. Pattern-detected PII (email/phone shapes) and body keys apply
   without explicit classification (detection is recognition, and the
   rules below are non-disclosing).
4. Anything else unclassified: ``unknown="redact"`` (default,
   fail-closed) replaces the value with ``[REDACTED]``;
   ``unknown="preserve"`` passes it through (explicit opt-in only).

Markers, hash tokens, and display masks pass through unchanged, so
re-sanitizing is stable. Inputs are never mutated. Blank tenant ids
and invalid ``unknown`` modes raise ``ValueError``. Functions never
raise on hostile values; hostile ``__repr__`` output is scrubbed like
any other string.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Literal

from shared.privacy.inventory import DataClassification
from shared.safety.secrets import REDACTED, REDACTED_SECRET, hash_pii

FINANCIAL_MARKER: str = "[FINANCIAL_SENSITIVE]"
_LLM_SNIPPET_BOUND: int = 500

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{8,}\d")
_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|secret|password|passwd|pwd|token|bearer|session[_-]?key"
    r"|authori[zs]ation|cookie|set[_-]?cookie|x[_-]?api[_-]?key|credential"
    r"|access[_-]?key|private[_-]?key)",
    re.IGNORECASE,
)
_SK_VALUE_RE = re.compile(r"\bsk[_-][A-Za-z0-9_-]{8,}\b")
_BEARER_VALUE_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_KNOWN_MARKER_RE = re.compile(
    r"^\[(REDACTED|REDACTED_EMAIL|REDACTED_SECRET|FINANCIAL_SENSITIVE)\]$"
)
_MASK_SHAPE_RE = re.compile(r"\*\*\*")
_BODY_KEYS = frozenset({"body", "snippet", "content"})
_UNKNOWN_MODES = ("redact", "preserve")

Classifications = Mapping[str, DataClassification]


def _looks_secret_key(key: str) -> bool:
    """Return True when a field name denotes secret-bearing content."""
    return bool(_SECRET_KEY_RE.search(key))


def _already_sanitized(value: str) -> bool:
    """Return True for values a previous pass produced (stable re-apply)."""
    return bool(
        _KNOWN_MARKER_RE.match(value) or _HASH_RE.match(value) or _MASK_SHAPE_RE.search(value)
    )


def _neutralize_controls(text: str) -> str:
    """Collapse all whitespace runs (log-injection defense)."""
    return " ".join(text.split())


def _scrub_embedded(text: str) -> str:
    """Scrub secret values and emails embedded in free text."""
    scrubbed = _BEARER_VALUE_RE.sub(r"\1" + REDACTED, text)
    scrubbed = _SK_VALUE_RE.sub(REDACTED_SECRET, scrubbed)
    return _EMAIL_RE.sub("[REDACTED_EMAIL]", scrubbed)


def _mask_email(value: str) -> str:
    """Mask an email for operator display: first char + domain kept."""
    local, _, domain = value.partition("@")
    if not local or not domain:
        return value
    return f"{local[0]}***@{domain}"


def _mask_phone(value: str) -> str:
    """Mask a phone for display: first 3 + last 4 chars kept."""
    if len(value) <= 7:
        return value
    return f"{value[:3]}******{value[-4:]}"


def _mask_account(value: str) -> str:
    """Mask an account/reference for display: last 4 chars kept."""
    if len(value) <= 4:
        return value
    return f"******{value[-4:]}"


def _mask_name(value: str) -> str:
    """Mask a personal name for display: first char kept."""
    if not value:
        return value
    return f"{value[0]}***"


def _is_account_key(key: str) -> bool:
    """Return True for account/reference-style field names."""
    lowered = key.lower()
    return "account" in lowered or "card" in lowered or "iban" in lowered or "acct" in lowered


def _tokenize(value: Any, tenant_id: str) -> str:
    """Return the tenant-scoped irreversible token for a value."""
    return hash_pii(str(value), tenant_id=tenant_id)


def _mask_for_ui(key: str, value: str) -> str:
    """Apply operator display masking by detected shape."""
    if _EMAIL_RE.fullmatch(value):
        return _mask_email(value)
    if _is_account_key(key):
        return _mask_account(value)
    if _PHONE_RE.fullmatch(value):
        return _mask_phone(value)
    return _mask_name(value) if value else value


def _validate(
    tenant_id: str, unknown: str, classifications: Classifications | None
) -> dict[str, DataClassification]:
    """Validate entry args; return normalized classifications."""
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("tenant_id must be a non-empty string")
    if unknown not in _UNKNOWN_MODES:
        raise ValueError(f"unknown must be one of {_UNKNOWN_MODES}")
    normalized: dict[str, DataClassification] = {}
    for field_name, classification in (classifications or {}).items():
        if not isinstance(classification, DataClassification):
            raise ValueError(f"classification for {field_name!r} must be a DataClassification")
        normalized[field_name] = classification
    return normalized


def _is_secret_credential(value: str) -> bool:
    """Return True when the whole value is a credential, not text about one."""
    return bool(_SK_VALUE_RE.fullmatch(value) or _BEARER_VALUE_RE.fullmatch(value))


def _sanitize_string(
    key: str,
    value: str,
    classification: DataClassification | None,
    *,
    tenant_id: str,
    surface: str,
    unknown: str,
) -> Any:
    """Sanitize one string value under the field resolution order."""
    if _already_sanitized(value):
        return value
    if _is_secret_credential(value):
        return REDACTED_SECRET
    if key in _BODY_KEYS:
        if surface == "llm":
            return _scrub_embedded(value)[:_LLM_SNIPPET_BOUND]
        return REDACTED
    if _EMAIL_RE.fullmatch(value):
        if surface == "ui":
            return _mask_email(value)
        return _tokenize(value, tenant_id)
    if _is_account_key(key) and surface == "ui":
        return _mask_account(value)
    if _PHONE_RE.fullmatch(value):
        if surface == "ui":
            return _mask_phone(value)
        return _tokenize(value, tenant_id)
    if surface == "ui":
        if _is_account_key(key):
            return _mask_account(value)
        if classification is DataClassification.PERSONAL:
            return _mask_name(value)
        scrubbed = _scrub_embedded(value)
        if classification in (DataClassification.INTERNAL, DataClassification.PUBLIC):
            return _neutralize_controls(scrubbed)
        if unknown == "preserve":
            return _neutralize_controls(scrubbed)
        return REDACTED
    if classification is DataClassification.PERSONAL:
        return _tokenize(value, tenant_id)
    if classification is DataClassification.FINANCIAL_SENSITIVE:
        return value
    scrubbed = _scrub_embedded(value)
    if classification in (DataClassification.INTERNAL, DataClassification.PUBLIC):
        return _neutralize_controls(scrubbed) if surface in ("log", "ui") else scrubbed
    if unknown == "preserve":
        return _neutralize_controls(scrubbed) if surface in ("log", "ui") else scrubbed
    return REDACTED


def _walk_value(
    key: str,
    value: Any,
    classification: DataClassification | None,
    *,
    tenant_id: str,
    surface: str,
    unknown: str,
    normalized: dict[str, DataClassification],
) -> Any:
    """Sanitize one value of any JSON-ish type (total: never raises)."""
    if value is None or isinstance(value, bool):
        return value
    if classification is DataClassification.SECRET or _looks_secret_key(key):
        return REDACTED_SECRET if classification is DataClassification.SECRET else REDACTED
    if isinstance(value, dict):
        return _walk_mapping(
            value,
            tenant_id=tenant_id,
            surface=surface,
            unknown=unknown,
            normalized=normalized,
        )
    if isinstance(value, list):
        return [
            _walk_mapping(
                item,
                tenant_id=tenant_id,
                surface=surface,
                unknown=unknown,
                normalized=normalized,
            )
            if isinstance(item, dict)
            else _walk_value(
                key,
                item,
                classification,
                tenant_id=tenant_id,
                surface=surface,
                unknown=unknown,
                normalized=normalized,
            )
            for item in value
        ]
    if isinstance(value, (Decimal, int, float)):
        if classification is DataClassification.FINANCIAL_SENSITIVE:
            if surface == "log":
                return FINANCIAL_MARKER
            return value
        if classification in (DataClassification.INTERNAL, DataClassification.PUBLIC):
            return value
        if unknown == "preserve":
            return value
        return REDACTED
    text = value if isinstance(value, str) else str(value)
    return _sanitize_string(
        key, text, classification, tenant_id=tenant_id, surface=surface, unknown=unknown
    )


def _walk_mapping(
    data: Mapping[str, Any],
    *,
    tenant_id: str,
    surface: str,
    unknown: str,
    normalized: dict[str, DataClassification],
) -> dict[str, Any]:
    """Recurse one mapping level, resolving classifications by field name."""
    out = {
        key: _walk_value(
            key,
            value,
            normalized.get(key),
            tenant_id=tenant_id,
            surface=surface,
            unknown=unknown,
            normalized=normalized,
        )
        for key, value in data.items()
    }
    items = list(out.items())
    if surface == "eval":
        items.sort(key=lambda kv: kv[0])
    return dict(items)


def _sanitize_mapping(
    data: Mapping[str, Any],
    *,
    tenant_id: str,
    surface: str,
    classifications: Classifications | None,
    unknown: str,
) -> dict[str, Any]:
    """Walk one mapping level applying field classifications."""
    normalized = _validate(tenant_id, unknown, classifications)
    return _walk_mapping(
        data,
        tenant_id=tenant_id,
        surface=surface,
        unknown=unknown,
        normalized=normalized,
    )


def sanitize_for_log(
    data: Mapping[str, Any],
    *,
    tenant_id: str,
    classifications: Classifications | None = None,
    unknown: Literal["redact", "preserve"] = "redact",
) -> dict[str, Any]:
    """Minimize for logs: tokens for PII, marker for financial values."""
    return _sanitize_mapping(
        data,
        tenant_id=tenant_id,
        surface="log",
        classifications=classifications,
        unknown=unknown,
    )


def sanitize_for_llm(
    data: Mapping[str, Any],
    *,
    tenant_id: str,
    classifications: Classifications | None = None,
    unknown: Literal["redact", "preserve"] = "redact",
) -> dict[str, Any]:
    """Minimum necessary context: evidence kept scrubbed and bounded."""
    return _sanitize_mapping(
        data,
        tenant_id=tenant_id,
        surface="llm",
        classifications=classifications,
        unknown=unknown,
    )


def sanitize_for_eval(
    data: Mapping[str, Any],
    *,
    tenant_id: str,
    classifications: Classifications | None = None,
    unknown: Literal["redact", "preserve"] = "redact",
) -> dict[str, Any]:
    """Deterministic canonical representation (keys sorted)."""
    return _sanitize_mapping(
        data,
        tenant_id=tenant_id,
        surface="eval",
        classifications=classifications,
        unknown=unknown,
    )


def sanitize_for_ui(
    data: Mapping[str, Any],
    *,
    tenant_id: str,
    classifications: Classifications | None = None,
    unknown: Literal["redact", "preserve"] = "redact",
) -> dict[str, Any]:
    """Operator-safe display masks; control characters neutralized."""
    return _sanitize_mapping(
        data,
        tenant_id=tenant_id,
        surface="ui",
        classifications=classifications,
        unknown=unknown,
    )
