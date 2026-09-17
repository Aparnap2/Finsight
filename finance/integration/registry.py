"""Static integration registry and 4-way financial-state correlator.

``INTEGRATIONS`` is the frozen six-entry registry from section 5 of
``docs/domain/meridian-process-model.md``: FinSight correlates and never
invents facts (existing systems own truth; Gmail is untrusted DATA).

:func:`compare_financial_states` correlates the four FS-231 money states
(expected, Razorpay net, QuickBooks, legacy). Pairwise comparison is
delegated to the frozen P1 :func:`reconcile` over net-carrying
``PaymentRecord`` legs — matching is never reimplemented here. The
variance breakdown itself is exact ``Decimal`` arithmetic owned by this
module.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from finance.reconciliation.errors import FloatMoneyError
from finance.reconciliation.models import (
    PaymentRecord,
    PaymentStatus,
    ReconciliationResult,
)
from finance.reconciliation.reconciler import reconcile
from finance.reconciliation.tolerances import ReconciliationTolerance

_MERIDIAN_TOLERANCE_MINOR = Decimal("100")
"""Pairwise allowance, mirroring CompanyConfiguration.tolerance_minor."""

_LEG_TIMESTAMP = datetime(2026, 9, 16, tzinfo=UTC)
"""Fixed leg timestamp: the correlator takes no clock reads."""


class Integration(BaseModel):
    """One static registry entry: who owns truth and what FinSight may do."""

    model_config = ConfigDict(frozen=True, strict=True)

    name: str
    """Integration key, e.g. ``razorpay``."""

    owns_truth: str
    """The truth this system owns (FinSight never invents it)."""

    finsight_read: str
    """What FinSight may read."""

    finsight_writes: bool
    """Whether FinSight may write back (only legacy S3 transport)."""

    facts_vs_reasoning: str
    """How this system splits facts (theirs) from reasoning (ours)."""


INTEGRATIONS: tuple[Integration, ...] = (
    Integration(
        name="razorpay",
        owns_truth="Provider state: capture, fee, refund, adjustment.",
        finsight_read="Read-only SDK: settlements, refunds, adjustments.",
        finsight_writes=False,
        facts_vs_reasoning="Facts: provider legs. Reasoning: FinSight net math.",
    ),
    Integration(
        name="quickbooks",
        owns_truth="Accounting truth: journals, balances, periods.",
        finsight_read="Read-only entries and period open/closed state.",
        finsight_writes=False,
        facts_vs_reasoning="Facts: journal entries. Reasoning: variance hypotheses.",
    ),
    Integration(
        name="sheets",
        owns_truth="Expected settlement business view (one watched cell).",
        finsight_read="Read the expected settlement cell.",
        finsight_writes=False,
        facts_vs_reasoning="Facts: expected figure. Reasoning: variance vs actuals.",
    ),
    Integration(
        name="gmail",
        owns_truth="Context only: refund requests, fee notes (untrusted DATA).",
        finsight_read="Search as DATA, never as instruction.",
        finsight_writes=False,
        facts_vs_reasoning="Facts: none (context). Reasoning: never follows it.",
    ),
    Integration(
        name="slack",
        owns_truth="Approval signal: the human decision, hash-pinned.",
        finsight_read="Read the approve/reject decision on a proposal hash.",
        finsight_writes=True,
        facts_vs_reasoning="Facts: human decision. Reasoning: posts proposal only.",
    ),
    Integration(
        name="cobol_legacy_s3",
        owns_truth="Legacy settlement truth per batch (no HTTP).",
        finsight_read="Read the COBOL result file per batch.",
        finsight_writes=True,
        facts_vs_reasoning="Facts: accept/reject per record. Writes: S3 file only.",
    ),
)
"""The frozen six-entry registry (static, not a plugin platform)."""


@dataclass(frozen=True)
class FourWayComparison:
    """Variance breakdown across the four financial states.

    Pairwise legs are verdicts from the frozen P1 ``reconcile()``;
    every ``*_minus_*`` field is exact ``Decimal`` arithmetic where the
    ``expected_minus_*`` fields are absolute gaps and
    ``books_minus_provider`` is the signed books-over-provider gap whose
    absolute value is the residual variance.
    """

    expected: Decimal
    razorpay_net: Decimal
    quickbooks: Decimal
    legacy: Decimal
    expected_minus_razorpay: Decimal
    expected_minus_quickbooks: Decimal
    expected_minus_legacy: Decimal
    books_minus_provider: Decimal
    residual_variance: Decimal
    books_agree: bool
    expected_vs_razorpay: ReconciliationResult
    expected_vs_quickbooks: ReconciliationResult
    quickbooks_vs_legacy: ReconciliationResult


def _require_money(field_name: str, value: object) -> Decimal:
    """Narrow a correlator input to ``Decimal``, rejecting float/bool."""
    if isinstance(value, bool | float) or not isinstance(value, Decimal):
        raise FloatMoneyError(
            f"Correlator field '{field_name}' must be Decimal, got "
            f"{type(value).__name__}: float/bool money is rejected."
        )
    if not value.is_finite():
        raise FloatMoneyError(
            f"Correlator field '{field_name}' must be finite, got {value}."
        )
    return value


def _total_leg(
    *,
    leg_id: str,
    provider: str,
    event_id: str,
    idempotency_key: str,
    total: Decimal,
    fee: Decimal = Decimal("0"),
    refund: Decimal = Decimal("0"),
) -> PaymentRecord:
    """Build a net-carrying comparison leg satisfying the P1 invariant.

    P1 legs model only gross/fee/refund components, so non-component
    reconciling items (provider adjustments, pending) are carried in
    the gross delta; the full FS-231 decomposition lives in the
    Razorpay fixture. ``net == gross - fee - refund`` holds exactly.
    """
    return PaymentRecord(
        payment_id=leg_id,
        provider=provider,
        provider_event_id=event_id,
        idempotency_key=idempotency_key,
        gross=total + fee + refund,
        fee=fee,
        refund=refund,
        net=total,
        currency="INR",
        status=PaymentStatus.SETTLED,
        occurred_at=_LEG_TIMESTAMP,
        tenant_id="meridian",
    )


def compare_financial_states(
    *,
    expected: Decimal,
    razorpay_net: Decimal,
    quickbooks: Decimal,
    legacy: Decimal,
) -> FourWayComparison:
    """Correlate the four money states, delegating pairs to ``reconcile()``.

    Args:
        expected: Sheets expected settlement, INR.
        razorpay_net: Provider net, INR.
        quickbooks: Accounting total, INR.
        legacy: Legacy accepted total, INR.

    Returns:
        The frozen :class:`FourWayComparison` with three frozen pairwise
        verdicts (expected vs provider, expected vs books, books vs
        legacy) and the exact ``Decimal`` variance breakdown. For FS-231
        the residual is 10000: the 17500 gross gap to legacy splits into
        the 7500 known pending timing item plus the rejected leg.

    Raises:
        FloatMoneyError: If any input is not a finite ``Decimal``.
    """
    expected_value = _require_money("expected", expected)
    razorpay_value = _require_money("razorpay_net", razorpay_net)
    quickbooks_value = _require_money("quickbooks", quickbooks)
    legacy_value = _require_money("legacy", legacy)
    tolerance = ReconciliationTolerance(absolute=_MERIDIAN_TOLERANCE_MINOR)
    expected_leg = _total_leg(
        leg_id="expected-sheets",
        provider="sheets",
        event_id="expected-settlement",
        idempotency_key="expected-sheets-20260916",
        total=expected_value,
    )
    razorpay_leg = _total_leg(
        leg_id="razorpay-net",
        provider="razorpay",
        event_id="razorpay-settlement",
        idempotency_key="razorpay-net-20260916",
        total=razorpay_value,
        fee=Decimal("7500"),
        refund=Decimal("2500"),
    )
    quickbooks_leg = _total_leg(
        leg_id="quickbooks-total",
        provider="quickbooks",
        event_id="quickbooks-balance",
        idempotency_key="quickbooks-total-20260916",
        total=quickbooks_value,
    )
    legacy_leg = _total_leg(
        leg_id="legacy-accepted",
        provider="cobol_legacy",
        event_id="LEGACY-20260916-0042",
        idempotency_key="legacy-accepted-20260916",
        total=legacy_value,
    )
    expected_vs_razorpay = reconcile(expected_leg, razorpay_leg, tolerance)
    expected_vs_quickbooks = reconcile(expected_leg, quickbooks_leg, tolerance)
    quickbooks_vs_legacy = reconcile(quickbooks_leg, legacy_leg, tolerance)
    books_gap = quickbooks_value - razorpay_value
    return FourWayComparison(
        expected=expected_value,
        razorpay_net=razorpay_value,
        quickbooks=quickbooks_value,
        legacy=legacy_value,
        expected_minus_razorpay=abs(expected_value - razorpay_value),
        expected_minus_quickbooks=abs(expected_value - quickbooks_value),
        expected_minus_legacy=abs(expected_value - legacy_value),
        books_minus_provider=books_gap,
        residual_variance=abs(books_gap),
        books_agree=quickbooks_value == legacy_value,
        expected_vs_razorpay=expected_vs_razorpay,
        expected_vs_quickbooks=expected_vs_quickbooks,
        quickbooks_vs_legacy=quickbooks_vs_legacy,
    )
