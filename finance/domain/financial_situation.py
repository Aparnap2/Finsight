"""FinancialSituation aggregate for the P6-01 Meridian domain contract.

Central object of FinSight per ``docs/domain/meridian-process-model.md``
(section 1.6): one detected discrepancy, one case. The aggregate is a
frozen Pydantic v2 model (strict mode, ``Decimal``-only money) scoped to
the single company ``meridian``. State changes never mutate: use
:meth:`FinancialSituation.transition_to`, which enforces the lifecycle
in section 2 of the process model.
"""

import re
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

from finance.domain._types import MoneyDecimal

_SITUATION_ID_PATTERN = re.compile(r"FS-\d{4}-\d{4}-\d{5}")
"""Shape ``FS-YYYY-MMDD-NNNNN``, e.g. ``FS-2026-0916-00231``."""

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "DETECTED": frozenset({"TRIAGED"}),
    "TRIAGED": frozenset({"INVESTIGATING"}),
    "INVESTIGATING": frozenset({"CORRELATED", "ESCALATED"}),
    "CORRELATED": frozenset({"EXPLAINED", "ESCALATED"}),
    "EXPLAINED": frozenset({"PROPOSED", "ESCALATED"}),
    "PROPOSED": frozenset({"APPROVED", "REJECTED", "ESCALATED"}),
    "APPROVED": frozenset({"EXECUTING", "ESCALATED"}),
    "EXECUTING": frozenset({"VERIFYING", "ESCALATED"}),
    "VERIFYING": frozenset({"CLOSED", "INVESTIGATING", "ESCALATED"}),
    "ESCALATED": frozenset({"INVESTIGATING", "PROPOSED"}),
    "REJECTED": frozenset(),
    "CLOSED": frozenset(),
}
"""Forward chain plus side states, mirroring section 2.1 of the spec.

Every non-terminal state may escalate; ``ESCALATED`` re-enters only via
``INVESTIGATING`` or ``PROPOSED`` (a new proposal version). ``REJECTED``
and ``CLOSED`` are terminal: re-entry happens through a new version,
never through a transition on the same aggregate.
"""


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

    def transition_to(self, target: SituationStatus) -> "FinancialSituation":
        """Return a copy in ``target`` state when the move is allowed.

        Args:
            target: The lifecycle state to move into.

        Returns:
            A new frozen aggregate with ``status`` set to ``target``.

        Raises:
            ValueError: If ``target`` is not reachable from the current
                status under the allowed-transition table (this covers
                every banned move: execution without approval, close
                without ``EXECUTION_VERIFIED``, and any exit from a
                terminal state).
        """
        allowed = _ALLOWED_TRANSITIONS[self.status.value]
        if target.value not in allowed:
            raise ValueError(
                f"Transition {self.status.value} -> {target.value} is not "
                f"allowed; permitted targets are {sorted(allowed)}."
            )
        return self.model_copy(update={"status": target})
