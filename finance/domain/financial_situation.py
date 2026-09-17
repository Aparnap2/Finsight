"""FinancialSituation aggregate for the P6-01 Meridian domain contract.

Central object of FinSight per ``docs/domain/meridian-process-model.md``
(section 1.6): one detected discrepancy, one case. The aggregate is a
frozen Pydantic v2 model (strict mode, ``Decimal``-only money) scoped to
the single company ``meridian``. State changes never mutate: use
:meth:`FinancialSituation.transition_to`, which enforces the canonical
lifecycle in ``finance/domain/lifecycle.py`` (spec section 2).

P6-02 adds optional lifecycle-only evidence (``proposal_ref``,
``verified_total``, ``closed_at``, ``rejection_reason``) plus the
:meth:`FinancialSituation.record_verification` helper. All default to
``None`` so P6-01 construction stays valid. Lifecycle state only: this
module never writes ledgers.
"""

import re
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

from finance.domain._types import MoneyDecimal
from finance.domain.lifecycle import ALLOWED_TRANSITIONS, assert_transition_allowed

_SITUATION_ID_PATTERN = re.compile(r"FS-\d{4}-\d{4}-\d{5}")
"""Shape ``FS-YYYY-MMDD-NNNNN``, e.g. ``FS-2026-0916-00231``."""

__all__ = ["ALLOWED_TRANSITIONS", "SituationStatus", "FinancialSituation"]
"""Re-exported canonical table, lifecycle states, and the aggregate."""


class SituationStatus(StrEnum):
    """Lifecycle states of a FinancialSituation (spec section 2)."""

    DETECTED = "DETECTED"
    """Discrepancy detected, severity not yet assigned."""

    TRIAGED = "TRIAGED"
    """Deterministic severity assigned."""

    INVESTIGATING = "INVESTIGATING"
    """Investigation opened, evidence being gathered."""

    CORRELATED = "CORRELATED"
    """Four financial states compared deterministically."""

    EXPLAINED = "EXPLAINED"
    """One to three hypotheses ranked with evidence."""

    PROPOSED = "PROPOSED"
    """Resolution proposal raised with verified evidence."""

    APPROVED = "APPROVED"
    """Slack approval pinned to the immutable proposal hash."""

    EXECUTING = "EXECUTING"
    """Idempotent S3 correction upload started."""

    VERIFYING = "VERIFYING"
    """Legacy result parsed, deterministic re-reconcile running."""

    CLOSED = "CLOSED"
    """Execution verified, residual within tolerance (terminal)."""

    ESCALATED = "ESCALATED"
    """Amount or risk exceeds the current decider (side state)."""

    REJECTED = "REJECTED"
    """Proposal refused on Slack (terminal for this version)."""


class FinancialSituation(BaseModel):
    """One detected discrepancy for Meridian, with four money states.

    The four states are ``Decimal``-only INR figures: Sheets expectation,
    Razorpay provider net, QuickBooks accounting truth and COBOL legacy
    truth. ``company_id`` is frozen to ``meridian`` (single-company
    boundary); ``status`` follows the lifecycle in section 2.
    """

    model_config = ConfigDict(frozen=True, strict=True)

    situation_id: str
    """Case id, shape ``FS-YYYY-MMDD-NNNNN``."""

    company_id: str = "meridian"
    """Always ``meridian``; any other value is rejected."""

    expected: MoneyDecimal
    """Sheets expected settlement, INR."""

    razorpay_net: MoneyDecimal
    """Razorpay provider net, INR (deterministic decomposition)."""

    quickbooks: MoneyDecimal
    """QuickBooks accounting total, INR."""

    legacy: MoneyDecimal
    """COBOL legacy accepted total, INR."""

    status: SituationStatus
    """Current lifecycle state."""

    proposal_ref: str | None = None
    """Pinned proposal reference (immutable proposal hash), set by PROPOSED."""

    verified_total: MoneyDecimal | None = None
    """Deterministic re-reconcile total, INR; set via record_verification."""

    closed_at: datetime | None = None
    """Timezone-aware close timestamp; auto-stamped on transition to CLOSED."""

    rejection_reason: str | None = None
    """Refusal reason recorded when a proposal version is REJECTED."""

    @field_validator("situation_id")
    @classmethod
    def _validate_situation_id(cls, value: str) -> str:
        """Require the ``FS-YYYY-MMDD-NNNNN`` id shape."""
        if _SITUATION_ID_PATTERN.fullmatch(value) is None:
            raise ValueError(
                f"situation_id must match FS-YYYY-MMDD-NNNNN, got {value!r}."
            )
        return value

    @field_validator("company_id")
    @classmethod
    def _validate_company_id(cls, value: str) -> str:
        """Enforce the single-company boundary (meridian only)."""
        if value != "meridian":
            raise ValueError(
                f"company_id must be 'meridian' (single-company boundary), "
                f"got {value!r}."
            )
        return value

    @field_validator("closed_at")
    @classmethod
    def _validate_closed_at(cls, value: datetime | None) -> datetime | None:
        """Require timezone-aware timestamps for closed_at when set."""
        if value is not None and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise ValueError(
                "closed_at must be timezone-aware when set, got a naive datetime."
            )
        return value

    def variance(self) -> Decimal:
        """Return the residual variance between books and provider net.

        Defined as ``quickbooks - razorpay_net`` in exact ``Decimal``
        arithmetic. For FS-231 the correlated accounting figure
        (QuickBooks 982500, agreeing with legacy 982500) exceeds the
        provider net (972500) by exactly the rejected 10000 correction
        leg. Note the gross gap ``expected - legacy`` is 17500: the
        7500 pending timing item (known, per the Razorpay decomposition)
        plus the 10000 actionable residual isolated here.
        """
        return self.quickbooks - self.razorpay_net

    def record_verification(self, verified_total: Decimal) -> "FinancialSituation":
        """Record the deterministic re-reconcile total while in VERIFYING.

        Per spec section 2.1, verification runs in ``VERIFYING`` and the
        ``VERIFYING -> CLOSED`` gate is the ``EXECUTION_VERIFIED`` verdict
        with residual near zero. There is no separate evidence state: this
        helper stores ``verified_total`` (lifecycle state only, never a
        ledger write) and keeps the status at ``VERIFYING`` so the caller
        can then transition to ``CLOSED``.

        Args:
            verified_total: The re-reconciled total in exact ``Decimal``.

        Returns:
            A new frozen aggregate with ``verified_total`` set.

        Raises:
            TypeError: If ``verified_total`` is not a ``Decimal`` (floats
                forbidden, Decimal-only money).
            ValueError: If the current status is not ``VERIFYING``.
        """
        if not isinstance(verified_total, Decimal):
            raise TypeError(
                "verified_total must be a decimal.Decimal for monetary "
                f"values, got {type(verified_total).__name__}."
            )
        if self.status is not SituationStatus.VERIFYING:
            raise ValueError(
                "record_verification() is only allowed from VERIFYING "
                f"(spec section 2.1), current status is {self.status.value}."
            )
        return self.model_copy(update={"verified_total": verified_total})

    def transition_to(self, target: SituationStatus) -> "FinancialSituation":
        """Return a copy in ``target`` state when the move is allowed.

        Validates against the canonical table in
        ``finance/domain/lifecycle.py`` (spec section 2.1). Field-level
        invariants (``verified_total`` before close, ``proposal_ref``
        before approval, ``rejection_reason`` on reject) live as explicit
        predicates in that module so the frozen P6-01 chain stays
        constructible; call them before transitioning. Moving to
        ``CLOSED`` auto-stamps a timezone-aware ``closed_at`` when unset.

        Args:
            target: The lifecycle state to move into.

        Returns:
            A new frozen aggregate with ``status`` set to ``target``.

        Raises:
            ValueError: If ``target`` is not reachable from the current
                status under the canonical table (this covers every
                banned move: execution without approval, close without
                ``EXECUTION_VERIFIED``, and any exit from a terminal
                state).
        """
        assert_transition_allowed(self.status, target)
        if target is SituationStatus.CLOSED and self.closed_at is None:
            return self.model_copy(
                update={"status": target, "closed_at": datetime.now(UTC)}
            )
        return self.model_copy(update={"status": target})
