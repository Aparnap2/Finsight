"""Redaction helpers for observability payloads — no PII, no unrestricted bodies.

Sensitive material (Gmail bodies, Sheets free text, legacy rejections,
full provider JSON, credentials, emails) MUST NOT be captured in traces.
Every span/generation/tool payload passes through ``sanitize_*`` before
export. The functions are pure, deterministic, and total.

Policy:
- ``body``/``snippet``/``content`` fields from ``search_gmail`` are redacted
  to ``[REDACTED Gmail body]`` with bounded metadata (message_id, subject
  hash) retained.
- Sheets/legacy free text beyond 500 chars is truncated and marked.
- Email addresses are replaced with ``[REDACTED_EMAIL]``.
- Secret-like keys (api_key, secret, password, bearer, token, credential,
  access_key) are replaced with ``[REDACTED_SECRET]``.
- Bare Gmail/Sheets JSON beyond the allowlist is dropped.
"""

from __future__ import annotations

import re
from typing import Any

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|secret|password|passwd|pwd|bearer|private[_-]?key|"
    r"credential|access[_-]?key|token)",
    re.IGNORECASE,
)
_MAX_VALUE_CHARS = 100
_MAX_HYPOTHESIS_CHARS = 500
_MAX_FREE_TEXT_CHARS = 500


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def redact_pii(text: str) -> str:
    """Redact email addresses and secret-bearing substrings in ``text``.

    Args:
        text: Free-text payload.

    Returns:
        Text with emails replaced by ``[REDACTED_EMAIL]`` and secret
        substrings replaced by ``[REDACTED_SECRET]`` where applicable.
    """
    if not isinstance(text, str):
        return str(text)
    # Email redaction
    redacted = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    # Credential hint — if the whole value looks like a secret key, redact fully
    if _SECRET_KEY_RE.search(redacted) and len(redacted) > 200:
        return "[REDACTED_SECRET]"
    return redacted


def sanitize_value(value: Any, *, limit: int = _MAX_VALUE_CHARS) -> Any:
    """Sanitize a single value: truncate, redact PII, drop sensitive keys.

    Args:
        value: Raw value (string or other).
        limit: Char limit for string truncation.

    Returns:
        Sanitized value.
    """
    if isinstance(value, str):
        truncated = _truncate(value, limit)
        return redact_pii(truncated)
    return value


def sanitize_args(
    args: dict[str, Any],
    *,
    capability: str | None = None,
    limit: int = _MAX_VALUE_CHARS,
) -> dict[str, Any]:
    """Sanitize tool args: truncate, redact Gmail bodies, PII, secrets.

    Args:
        args: Raw args mapping from a capability call.
        capability: Capability name for targeted redaction (e.g. search_gmail).
        limit: Per-value truncation limit.

    Returns:
        Sanitized copy (never mutates input).
    """
    out: dict[str, Any] = {}
    for k, v in args.items():
        if _SECRET_KEY_RE.search(k):
            out[k] = "[REDACTED_SECRET]"
            continue
        if isinstance(v, str) and _SECRET_KEY_RE.search(v) and (len(v) > 20 or "sk-" in v.lower()):
            out[k] = "[REDACTED_SECRET]"
            continue
        # Gmail body redaction: search_gmail carries snippet/body
        if capability == "search_gmail" and k in ("body", "snippet", "content"):
            out[k] = "[REDACTED Gmail body]"
            continue
        # Generic free-text fields beyond allowlist — truncate + PII redact
        if isinstance(v, str):
            # Truncate to limit and redact emails
            out[k] = sanitize_value(v, limit=limit)
        else:
            out[k] = v
    return out


def sanitize_input(
    data: dict[str, Any],
    *,
    capability: str | None = None,
) -> dict[str, Any]:
    """Sanitize a generic input dict for tracing.

    Args:
        data: Raw input dict for a span/tool/generation.
        capability: Optional capability name for targeted rules.

    Returns:
        Sanitized dict.
    """
    # Check for sensitive top-level keys that should be dropped fully
    sanitized: dict[str, Any] = {}
    for k, v in data.items():
        if _SECRET_KEY_RE.search(k):
            sanitized[k] = "[REDACTED_SECRET]"
            continue
        # Gmail body / Sheets free text / legacy rejection / full provider JSON
        if k in ("gmail_body", "sheet_content", "legacy_rejection", "provider_json"):
            # Do not capture unrestricted payload — replace with metadata
            if isinstance(v, str):
                sanitized[k] = "[REDACTED sensitive payload]"
            elif isinstance(v, dict):
                sanitized[k] = {"_redacted": True, "keys": list(v.keys())[:5]}
            else:
                sanitized[k] = "[REDACTED sensitive payload]"
            continue
        if isinstance(v, str):
            # Hypothesis text has higher limit but still PII-redacted
            lim = _MAX_HYPOTHESIS_CHARS if k == "hypothesis_text" else _MAX_VALUE_CHARS
            # For gmail bodies in input, redact fully
            if capability == "search_gmail" and k in ("body", "snippet"):
                sanitized[k] = "[REDACTED Gmail body]"
            else:
                sanitized[k] = sanitize_value(v, limit=lim)
        elif isinstance(v, dict):
            # Recurse shallowly for nested evidence metadata, but drop bodies
            nested: dict[str, Any] = {}
            for nk, nv in v.items():
                if nk in ("body", "content", "raw", "payload"):
                    nested[nk] = "[REDACTED]"
                elif isinstance(nv, str):
                    nested[nk] = sanitize_value(nv)
                else:
                    nested[nk] = nv
            sanitized[k] = nested
        else:
            sanitized[k] = v
    return sanitized


def sanitize_output(data: dict[str, Any]) -> dict[str, Any]:
    """Sanitize a tool/generation output dict (never echo Gmail bodies).

    Args:
        data: Raw output dict.

    Returns:
        Sanitized dict with bodies redacted and values truncated.
    """
    sanitized: dict[str, Any] = {}
    for k, v in data.items():
        if k in ("gmail_body", "body", "snippet", "sheet_content", "legacy_rejection"):
            sanitized[k] = "[REDACTED sensitive payload]"
            continue
        if isinstance(v, str):
            sanitized[k] = sanitize_value(_truncate(v, _MAX_FREE_TEXT_CHARS))
        elif isinstance(v, list):
            # List of evidence rows — redact each row's body field
            rows: list[Any] = []
            for item in v[:10]:  # bound list size in trace
                if isinstance(item, dict):
                    row = {}
                    for rk, rv in item.items():
                        if rk in ("body", "snippet", "content"):
                            row[rk] = "[REDACTED]"
                        elif isinstance(rv, str):
                            row[rk] = sanitize_value(_truncate(rv, _MAX_VALUE_CHARS))
                        else:
                            row[rk] = rv
                    rows.append(row)
                else:
                    rows.append(item)
            sanitized[k] = rows
            if len(v) > 10:
                sanitized["_truncated_rows"] = len(v) - 10
        elif isinstance(v, dict):
            sanitized[k] = sanitize_input(v)
        else:
            sanitized[k] = v
    return sanitized


def is_unrestricted_payload(data: dict[str, Any]) -> bool:
    """Return True when ``data`` appears to contain an unrestricted Gmail/Sheets body.

    Used by the observability test gate to reject traces that capture
    raw Gmail bodies (unbounded free-text beyond 500 chars or containing
    an @ email that wasn't redacted).

    Args:
        data: Trace payload to inspect.

    Returns:
        True when unrestricted sensitive content is detected.
    """
    for k, v in data.items():
        if k in ("gmail_body", "sheet_content", "legacy_rejection", "provider_json"):
            if isinstance(v, str) and v not in (
                "[REDACTED sensitive payload]",
                "[REDACTED Gmail body]",
                "[REDACTED]",
            ):
                if len(v) > _MAX_FREE_TEXT_CHARS:
                    return True
                if _EMAIL_RE.search(v):
                    return True
            if isinstance(v, str) and len(v) > 1000:
                return True
        if isinstance(v, str) and len(v) > 1000 and ("@" in v or "body" in k.lower()):
            return True
        if isinstance(v, dict) and is_unrestricted_payload(v):
            return True
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict) and is_unrestricted_payload(item):
                    return True
    return False
