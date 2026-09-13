"""Frozen typed output contract for the P4.2 investigation planner.

:class:`InvestigationPlan` is the candidate the LLM returns through exactly one
``LLMProvider.generate_structured`` call. It authorizes nothing: every effect
still requires the deterministic verifier plus the frozen P3 proposal,
approval, and execution path.

The module is Decimal-free (no money fields) and imports nothing from
``apps/``, ``agents`` siblings, ``finance`` execution paths, or any LLM
framework. Strict Pydantic (``strict=True``, ``extra="forbid"``) applies;
JSON arrays are normalized to tuples in ``mode="before"`` validators so
provider-decoded output validates while the exposed contract stays tuple
typed with strict element checking.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CapabilityName = Literal[
    "get_stripe_payment",
    "get_stripe_refunds",
    "get_qb_transaction",
    "get_expected_state",
    "search_gmail",
]
"""Closed capability vocabulary (spec: LLM-boundary allowlist)."""

FROZEN_CAPABILITY_ALLOWLIST: tuple[str, ...] = (
    "get_stripe_payment",
    "get_stripe_refunds",
    "get_qb_transaction",
    "get_expected_state",
    "search_gmail",
)
"""Frozen closed allowlist; the request snapshot is the enforcement source."""

MAX_HYPOTHESIS_CHARS = 2000
MAX_CAPABILITY_CALLS = 8
MAX_ARGS_PER_CALL = 8
MAX_ARG_KEY_CHARS = 64
MAX_ARG_VALUE_CHARS = 512
MAX_EVIDENCE_REQUIRED = 32
MAX_EVIDENCE_ID_CHARS = 128


def _coerce_tuple(value: Any, *, field_name: str) -> Any:
    """Normalize a JSON list to a tuple ahead of strict validation.

    Args:
        value: Raw field value (tuple, JSON-decoded list, or other).
        field_name: Field name used only for error messages.

    Returns:
        A tuple when given a list or tuple; anything else is returned
        unchanged so strict validation reports the real type error.
    """
    _ = field_name
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return value


class CapabilityCall(BaseModel):
    """One ordered deterministic capability reference (selection only).

    Names a capability without invoking it: execution belongs exclusively to
    the deterministic executor after verifier approval.
    """

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    capability: CapabilityName
    args: dict[str, str] = Field(default_factory=dict)
    order_index: int = Field(ge=0)

    @field_validator("args")
    @classmethod
    def _check_args(cls, value: dict[str, str]) -> dict[str, str]:
        """Enforce a string-only bounded args mapping."""
        if len(value) > MAX_ARGS_PER_CALL:
            raise ValueError(f"args holds {len(value)} entries; max is {MAX_ARGS_PER_CALL}.")
        for key, item in value.items():
            if not key.strip():
                raise ValueError("Every args key must be a non-empty string.")
            if len(key) > MAX_ARG_KEY_CHARS:
                raise ValueError(f"args key {key!r} exceeds {MAX_ARG_KEY_CHARS} chars.")
            if len(item) > MAX_ARG_VALUE_CHARS:
                raise ValueError(f"args[{key!r}] exceeds {MAX_ARG_VALUE_CHARS} chars.")
        return value


class InvestigationPlan(BaseModel):
    """Candidate plan: unproven hypothesis plus ordered capability references."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    hypothesis_text: str = Field(min_length=1, max_length=MAX_HYPOTHESIS_CHARS)
    capability_calls: tuple[CapabilityCall, ...] = Field(
        min_length=1, max_length=MAX_CAPABILITY_CALLS
    )
    evidence_required: tuple[str, ...] = Field(min_length=1, max_length=MAX_EVIDENCE_REQUIRED)
    escalation: bool = False

    @model_validator(mode="before")
    @classmethod
    def _coerce_sequences(cls, data: Any) -> Any:
        """Normalize JSON arrays to tuples ahead of strict validation."""
        if isinstance(data, dict):
            coerced = dict(data)
            for field_name in ("capability_calls", "evidence_required"):
                if field_name in coerced:
                    coerced[field_name] = _coerce_tuple(coerced[field_name], field_name=field_name)
            return coerced
        return data

    @field_validator("hypothesis_text")
    @classmethod
    def _check_hypothesis(cls, value: str) -> str:
        """Reject blank hypotheses; authoritative wording is scanned by planner."""
        if not value.strip():
            raise ValueError("hypothesis_text must be non-blank.")
        return value

    @field_validator("evidence_required")
    @classmethod
    def _check_evidence_required(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Require non-blank bounded unique ids (subset checked by the planner)."""
        seen: set[str] = set()
        for evidence_id in value:
            if not evidence_id.strip():
                raise ValueError("Every evidence_required entry must be non-blank.")
            if len(evidence_id) > MAX_EVIDENCE_ID_CHARS:
                raise ValueError(
                    f"Evidence id {evidence_id!r} exceeds {MAX_EVIDENCE_ID_CHARS} chars."
                )
            if evidence_id in seen:
                raise ValueError(f"Duplicate evidence_required entry {evidence_id!r}.")
            seen.add(evidence_id)
        return value

    @model_validator(mode="after")
    def _check_ordering(self) -> InvestigationPlan:
        """Require order_index to match tuple position (0-based, dense)."""
        for position, call in enumerate(self.capability_calls):
            if call.order_index != position:
                raise ValueError(
                    f"capability_calls[{position}].order_index is "
                    f"{call.order_index}; must equal its position ({position})."
                )
        return self
