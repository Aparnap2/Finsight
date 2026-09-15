"""Frozen typed verdict contract for the P4.4 deterministic verifier.

:class:`Verdict` is the single total output of
:class:`agents.verification.verifier.Verifier.verify`: one closed status
(``ACCEPTED`` | ``REJECTED_REPLAN`` | ``ESCALATE_HITL``), a tuple of
machine-readable reason codes, and the attempt index that produced it.
It authorizes nothing: callers map ``ACCEPTED`` into the frozen P3
proposal / approval / execution path, ``REJECTED_REPLAN`` into a bounded
re-plan, and ``ESCALATE_HITL`` into a frozen case routed to human review.

The module is Decimal-free (no money fields) and imports nothing from
``apps/``, ``agents`` siblings, ``finance`` execution paths, ``shared/``,
or any LLM framework. Strict Pydantic (``strict=True``, ``extra="forbid"``)
applies; JSON arrays are normalized to tuples in ``mode="before"``
validators so the exposed contract stays tuple typed with strict element
checking.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

VerdictStatus = Literal["ACCEPTED", "REJECTED_REPLAN", "ESCALATE_HITL"]
"""Closed verdict vocabulary (spec: deterministic verifier gates every output)."""

MAX_REASONS = 64
"""Ceiling on reason codes per verdict (audit-bounded)."""

MAX_REASON_CHARS = 512
"""Ceiling on a single machine-readable reason code."""


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


class Verdict(BaseModel):
    """One verifier decision: closed status plus audit reasons and attempt."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    status: VerdictStatus
    reasons: tuple[str, ...] = Field(default_factory=tuple)
    attempt_index: int = Field(ge=0)

    @field_validator("reasons", mode="before")
    @classmethod
    def _coerce_reasons(cls, value: Any) -> Any:
        """Normalize JSON arrays to tuples ahead of strict validation."""
        return _coerce_tuple(value, field_name="reasons")

    @field_validator("reasons")
    @classmethod
    def _check_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Require non-blank bounded machine-readable reason codes."""
        if len(value) > MAX_REASONS:
            raise ValueError(f"reasons holds {len(value)} entries; max is {MAX_REASONS}.")
        for reason in value:
            if not reason.strip():
                raise ValueError("Every reason must be a non-empty string.")
            if len(reason) > MAX_REASON_CHARS:
                raise ValueError(f"reason {reason!r} exceeds {MAX_REASON_CHARS} chars.")
        return value
