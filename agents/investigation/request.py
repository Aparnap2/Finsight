"""Frozen typed input contract for the P4.2 investigation planner.

:class:`InvestigationRequest` is assembled in deterministic code before any LLM
call: verified-only evidence ids, a bounded context window, the frozen
capability-allowlist snapshot, and a round budget. The LLM never receives full
DB access, credentials, or unscoped history. Decimal-free (no money fields).

This module imports nothing from ``apps/``, ``agents`` siblings (beyond the
capability vocabulary in :mod:`agents.investigation.plan`), ``finance``
execution paths, or any LLM framework.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agents.investigation.plan import FROZEN_CAPABILITY_ALLOWLIST, MAX_EVIDENCE_ID_CHARS

MAX_CONTEXT_CHARS = 4000
"""Bounded context window; overlong input is truncated and flagged."""

MAX_ID_CHARS = 128
MAX_EVIDENCE_IDS = 32
MIN_ROUND_BUDGET = 1
MAX_ROUND_BUDGET = 10
DEFAULT_ROUND_BUDGET = 3

# P5-02 per-exception-type capability scope (allowlist subset per case).
# Tenant isolation: scope is checked after allowlist subset check; unknown
# exception_type (not in map) has no extra scope restriction beyond the frozen
# allowlist. Keys are the canonical P1 codes (I-REFUND-LAG, I-FEE-DRIFT, I-DUPLICATE).
# I-REFUND-LAG is the flagship and allows the full frozen set (backward compat
# for existing tests); fee/duplicate are scoped.
_ALLOWED_SCOPE: dict[str, frozenset[str]] = {
    "I-REFUND-LAG": frozenset(
        {
            "get_stripe_payment",
            "get_stripe_refunds",
            "get_qb_transaction",
            "get_expected_state",
            "search_gmail",
        }
    ),
    "I-FEE-DRIFT": frozenset({"get_stripe_payment", "get_qb_transaction", "get_expected_state"}),
    "I-DUPLICATE": frozenset({"get_qb_transaction", "get_expected_state", "search_gmail"}),
}


class InvestigationRequest(BaseModel):
    """Deterministic planner input assembled before any LLM call."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    exception_id: str = Field(min_length=1, max_length=MAX_ID_CHARS)
    exception_type: str = Field(min_length=1, max_length=MAX_ID_CHARS)
    tenant_id: str = Field(min_length=1, max_length=MAX_ID_CHARS)
    actor: str = Field(min_length=1, max_length=MAX_ID_CHARS)
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=MAX_EVIDENCE_IDS)
    context_window: str = Field(default="", max_length=MAX_CONTEXT_CHARS)
    context_truncated: bool = False
    capability_allowlist: tuple[str, ...] = Field(
        default=FROZEN_CAPABILITY_ALLOWLIST,
        min_length=1,
        max_length=len(FROZEN_CAPABILITY_ALLOWLIST),
    )
    round_budget: int = Field(
        default=DEFAULT_ROUND_BUDGET, ge=MIN_ROUND_BUDGET, le=MAX_ROUND_BUDGET
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_input(cls, data: Any) -> Any:
        """Truncate overlong context (flag it) and normalize JSON lists."""
        if isinstance(data, InvestigationRequest):
            return data
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        raw_context = normalized.get("context_window", "")
        if isinstance(raw_context, str) and len(raw_context) > MAX_CONTEXT_CHARS:
            normalized["context_window"] = raw_context[:MAX_CONTEXT_CHARS]
            normalized["context_truncated"] = True
        for field_name in ("evidence_ids", "capability_allowlist"):
            if field_name in normalized and isinstance(normalized[field_name], list):
                normalized[field_name] = tuple(normalized[field_name])
        return normalized

    @field_validator("exception_id", "exception_type", "tenant_id", "actor")
    @classmethod
    def _check_non_blank(cls, value: str) -> str:
        """Reject blank identifiers (tenant/actor included, trusted server-side)."""
        if not value.strip():
            raise ValueError("Identifier must be a non-blank string.")
        return value.strip()

    @field_validator("evidence_ids")
    @classmethod
    def _check_evidence_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Require verified-only evidence ids: non-blank, bounded, unique."""
        seen: set[str] = set()
        for evidence_id in value:
            if not evidence_id.strip():
                raise ValueError("Every evidence id must be a non-blank string.")
            if len(evidence_id) > MAX_EVIDENCE_ID_CHARS:
                raise ValueError(
                    f"Evidence id {evidence_id!r} exceeds {MAX_EVIDENCE_ID_CHARS} chars."
                )
            if evidence_id in seen:
                raise ValueError(f"Duplicate evidence id {evidence_id!r}.")
            seen.add(evidence_id)
        return value

    @field_validator("capability_allowlist")
    @classmethod
    def _check_allowlist(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Require a duplicate-free subset of the frozen allowlist."""
        frozen = set(FROZEN_CAPABILITY_ALLOWLIST)
        seen: set[str] = set()
        for capability in value:
            if capability not in frozen:
                raise ValueError(f"Capability {capability!r} is outside the frozen allowlist.")
            if capability in seen:
                raise ValueError(f"Duplicate allowlist entry {capability!r}.")
            seen.add(capability)
        return value

    @model_validator(mode="after")
    def _check_scope(self) -> InvestigationRequest:
        """Enforce per-exception-type scope: allowlist must be subset of allowed scope."""
        allowed = _ALLOWED_SCOPE.get(self.exception_type)
        if allowed is None:
            return self
        for cap in self.capability_allowlist:
            if cap not in allowed:
                raise ValueError(
                    f"Capability {cap!r} is outside scope for {self.exception_type!r} "
                    f"(allowed: {sorted(allowed)})"
                )
        return self
