"""Property-based tests for FinSight's financial invariants (APA-94 slice 2).

Every property here is derived from code that already exists and already
enforces the invariant at runtime — the properties do not invent an
accounting identity, they check that the *enforcement* holds across a
generated input space rather than across hand-picked examples.

## Sign and rounding conventions (defined before the properties)

These are the conventions the code actually uses. They are stated here so
a reader does not have to infer them, and so a future change that breaks
one of them fails a test rather than passing silently.

- **Money is ``Decimal`` throughout.** ``float``/``bool`` are rejected at
  the boundary (``finance/reconciliation/models.py::_require_decimal``).
- **Fee and refund are deductions.** The net equation is
  ``net == gross - fee - refund`` — enforced in
  ``PaymentRecord.__post_init__`` and derived in
  ``finance/reconciliation/normalizer.py`` when ``net`` is absent.
  A *negative* fee is a fee reversal and therefore *increases* the net;
  the arithmetic is the invariant, and the sign convention is carried by
  the value, not by a separate rule.
- **No implicit rounding.** All arithmetic is exact ``Decimal``; nothing
  in the normalizer or the reconciler rounds. Normalization may change
  the *scale* of a value (minor units ``1050`` with exponent 2 becomes
  ``Decimal("10.5")``, not ``Decimal("10.50")``) but never its numeric
  value.
- **Reconciliation difference is signed and observed-minus-expected:**
  ``difference == observed - expected`` and ``variance == abs(difference)``
  (``ReconciliationResult.__post_init__``).
- **Tolerance is boundary-inclusive:** ``abs(difference) <= allowance``
  is a match; strictly greater is a break
  (``ReconciliationTolerance.allows``). The allowance is
  ``absolute + abs(percent * base)`` with ``base = abs(processor.net)``.
- **Materiality is strict:** ``MATERIAL`` exactly when
  ``abs(difference) > allowance`` — a difference exactly equal to the
  allowance is ``IMMATERIAL`` and ``TOLERANCE_MATCHED``.

## The four properties

1. **Conservation** — ``net == gross - fee - refund`` for any generated
   leg, and ``difference == observed - expected`` /
   ``variance == abs(difference)`` for any generated reconciliation.
2. **Normalization invariance** — equivalent monetary inputs (same value
   expressed as minor units, as a decimal string, or as a ``Decimal``)
   normalize to the same numeric money, and equivalent scalar inputs
   (currency case, timestamp offset) normalize to the same record.
3. **Idempotency** — the same financial event presented twice does not
   change the outcome twice: duplicate detection groups by
   ``idempotency_key``, and a repeat of the same leg reconciles to the
   same verdict.
4. **Reconciliation consistency** — matching and aggregation preserve the
   defined financial totals: the matched verdict follows from the
   difference, materiality follows from the tolerance, and the
   fingerprint is stable for the same pair.

## Determinism and budget

Hypothesis runs with a fixed profile: ``max_examples`` bounded, no
deadline (the suite is CPU-bound and a deadline would make CI flaky),
and a derandomized seed so a failure reproduces exactly. The example
database is disabled so no run leaves state behind.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from finance.reconciliation.fingerprints import canonical_payment, fingerprint_pair
from finance.reconciliation.matcher import exact_match, find_duplicates, find_match
from finance.reconciliation.models import PaymentRecord, PaymentStatus
from finance.reconciliation.normalizer import normalize
from finance.reconciliation.reconciler import reconcile
from finance.reconciliation.tolerances import ReconciliationTolerance

#: Bounded example count: enough to explore the space, small enough that
#: the suite stays inside the CI fast gate's budget.
MAX_EXAMPLES = 100

#: Derandomized so a CI failure reproduces exactly; the example database
#: is disabled so no run leaves state in the working tree.
PROPERTY_SETTINGS = settings(
    max_examples=MAX_EXAMPLES,
    deadline=None,
    derandomize=True,
    database=None,
    suppress_health_check=[HealthCheck.too_slow],
)

#: Monetary magnitudes: whole units up to a million, with cents. Bounded so
#: generated values stay realistic and the Decimal arithmetic stays exact.
money = st.decimals(
    min_value=Decimal("-1000000.00"),
    max_value=Decimal("1000000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

#: ISO 4217 codes with non-zero minor-unit exponents, so the
#: minor-units path is exercised and not just the default exponent 2.
CURRENCIES = ("INR", "USD", "EUR", "JPY", "KWD", "CLP", "BHD")

#: The minor-unit exponent each currency normalizes with.
_EXPONENTS = {"JPY": 0, "CLP": 0, "KWD": 3, "BHD": 3}


@st.composite
def payment_legs(draw: st.DrawFn) -> PaymentRecord:
    """Generate a valid payment leg with an exact net.

    The net is derived the same way the normalizer derives it, so the
    generated leg is one the domain itself would accept.
    """
    gross = draw(money)
    fee = draw(money)
    refund = draw(money)
    currency = draw(st.sampled_from(CURRENCIES))
    return PaymentRecord(
        payment_id=f"pay_{draw(st.integers(min_value=0, max_value=10**6))}",
        provider="razorpay",
        provider_event_id=f"evt_{draw(st.integers(min_value=0, max_value=10**6))}",
        idempotency_key=f"idem_{draw(st.integers(min_value=0, max_value=10**6))}",
        gross=gross,
        fee=fee,
        refund=refund,
        net=gross - fee - refund,
        currency=currency,
        status=draw(st.sampled_from(list(PaymentStatus))),
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC)
        + timedelta(seconds=draw(st.integers(min_value=0, max_value=10**7))),
        tenant_id="meridian",
    )


@st.composite
def raw_payloads(draw: st.DrawFn) -> dict[str, Any]:
    """Generate a raw provider payload the normalizer accepts.

    The gross amount is generated as an *integer number of minor units*
    and the decimal string is derived from it, so the payload always has
    an exact minor-unit representation.  (A value like ``0.01`` in JPY —
    exponent 0 — has no integer minor-unit form, so deriving the string
    the other way round would generate unrepresentable values.)
    """
    currency = draw(st.sampled_from(CURRENCIES))
    exponent = _EXPONENTS.get(currency, 2)
    minor_units = draw(st.integers(min_value=0, max_value=100_000_000))
    gross = minor_units / (Decimal(10) ** exponent)
    return {
        "payment_id": f"pay_{draw(st.integers(min_value=0, max_value=10**6))}",
        "provider": "razorpay",
        "provider_event_id": f"evt_{draw(st.integers(min_value=0, max_value=10**6))}",
        "idempotency_key": f"idem_{draw(st.integers(min_value=0, max_value=10**6))}",
        "currency": currency,
        "status": "CAPTURED",
        "occurred_at": "2026-01-01T10:00:00+05:30",
        "gross": str(gross),
        "gross_minor": minor_units,
    }


class TestConservation:
    """Property 1 — money is conserved across normalization and reconciliation."""

    @PROPERTY_SETTINGS
    @given(leg=payment_legs())
    def test_net_is_gross_minus_fee_minus_refund(self, leg: PaymentRecord) -> None:
        """A leg's net is exactly gross − fee − refund."""
        assert leg.net == leg.gross - leg.fee - leg.refund

    @PROPERTY_SETTINGS
    @given(leg=payment_legs(), delta=money)
    def test_constructor_refuses_a_non_conserving_net(
        self, leg: PaymentRecord, delta: Decimal
    ) -> None:
        """A leg whose net does not conserve is refused, not accepted.

        Without this the conservation property would only ever re-derive
        the identity the constructor already enforces: a guard that was
        removed would go unnoticed, because the generated legs satisfy the
        identity by construction.
        """
        from finance.reconciliation.errors import InvariantViolation

        broken_net = leg.net + delta
        if broken_net == leg.gross - leg.fee - leg.refund:
            return
        with pytest.raises(InvariantViolation, match="net invariant"):
            PaymentRecord(
                payment_id=leg.payment_id,
                provider=leg.provider,
                provider_event_id=leg.provider_event_id,
                idempotency_key=leg.idempotency_key,
                gross=leg.gross,
                fee=leg.fee,
                refund=leg.refund,
                net=broken_net,
                currency=leg.currency,
                status=leg.status,
                occurred_at=leg.occurred_at,
                tenant_id=leg.tenant_id,
            )

    @PROPERTY_SETTINGS
    @given(raw=raw_payloads(), delta=money)
    def test_normalizer_refuses_an_inconsistent_explicit_net(
        self, raw: dict[str, Any], delta: Decimal
    ) -> None:
        """A payload whose explicit ``net`` contradicts its components is refused."""
        from finance.reconciliation.errors import InvariantViolation

        payload = {key: value for key, value in raw.items() if key != "gross_minor"}
        record = normalize(payload, tenant_id="meridian")
        stated = record.gross - record.fee - record.refund + delta
        if stated == record.gross - record.fee - record.refund:
            return
        with pytest.raises(InvariantViolation, match="net invariant"):
            normalize({**payload, "net": str(stated)}, tenant_id="meridian")

    @PROPERTY_SETTINGS
    @given(raw=raw_payloads())
    def test_derived_net_conserves_the_leg(self, raw: dict[str, Any]) -> None:
        """The net the normalizer derives satisfies the conservation identity."""
        record = normalize(raw, tenant_id="meridian")
        assert record.net == record.gross - record.fee - record.refund
        assert record.gross == Decimal(raw["gross"])

    @PROPERTY_SETTINGS
    @given(processor=payment_legs(), ledger=payment_legs())
    def test_reconciliation_difference_is_observed_minus_expected(
        self, processor: PaymentRecord, ledger: PaymentRecord
    ) -> None:
        """A reconciliation's difference and variance are exact Decimals."""
        processor = replace(processor, currency="INR")
        ledger = replace(ledger, currency="INR")
        result = reconcile(processor, ledger, ReconciliationTolerance())
        assert result.difference == result.observed - result.expected
        assert result.variance == abs(result.difference)
        assert result.expected == processor.net
        assert result.observed == ledger.net


class TestNormalizationInvariance:
    """Property 2 — equivalent inputs normalize to the same record."""

    @PROPERTY_SETTINGS
    @given(raw=raw_payloads())
    def test_minor_units_and_decimal_string_agree_numerically(self, raw: dict[str, Any]) -> None:
        """The same value as minor units and as a decimal string normalizes alike."""
        minor_record = normalize(
            {**raw, "gross": str(raw["gross"])},
            tenant_id="meridian",
        )
        major_record = normalize(
            {key: value for key, value in raw.items() if key != "gross_minor"},
            tenant_id="meridian",
        )

        assert minor_record.gross == major_record.gross
        assert minor_record.net == major_record.net
        assert minor_record.currency == major_record.currency

    @PROPERTY_SETTINGS
    @given(raw=raw_payloads())
    def test_currency_case_does_not_change_the_record(self, raw: dict[str, Any]) -> None:
        """Currency case and surrounding whitespace are normalized away."""
        currency = str(raw["currency"])
        upper = normalize({**raw, "currency": currency}, tenant_id="meridian")
        lower = normalize({**raw, "currency": currency.lower()}, tenant_id="meridian")
        padded = normalize({**raw, "currency": f"  {currency}  "}, tenant_id="meridian")
        assert upper.currency == lower.currency == padded.currency == currency
        assert upper.net == lower.net == padded.net

    @PROPERTY_SETTINGS
    @given(raw=raw_payloads())
    def test_timestamp_offset_normalizes_to_utc(self, raw: dict[str, Any]) -> None:
        """The same instant expressed in another offset normalizes to UTC."""
        offset_form = normalize(
            {**raw, "occurred_at": "2026-01-01T10:00:00+05:30"},
            tenant_id="meridian",
        )
        utc_form = normalize({**raw, "occurred_at": "2026-01-01T04:30:00Z"}, tenant_id="meridian")
        assert offset_form.occurred_at == utc_form.occurred_at
        assert offset_form.occurred_at.tzinfo is UTC

    @PROPERTY_SETTINGS
    @given(raw=raw_payloads())
    def test_float_money_is_refused(self, raw: dict[str, Any]) -> None:
        """Float money is rejected at the boundary, not silently coerced."""
        from finance.reconciliation.errors import FloatMoneyError

        # Drop the minor-unit key: it takes precedence over the major-unit
        # key, so leaving it in would never read the float at all.
        payload = {key: value for key, value in raw.items() if key != "gross_minor"}
        try:
            normalize({**payload, "gross": 10.5}, tenant_id="meridian")
        except FloatMoneyError:
            return
        raise AssertionError("float money must be refused")


class TestIdempotency:
    """Property 3 — the same event presented twice does not act twice."""

    @PROPERTY_SETTINGS
    @given(leg=payment_legs())
    def test_repeating_a_leg_does_not_change_its_verdict(self, leg: PaymentRecord) -> None:
        """Reconciling a leg against itself twice yields the same verdict."""
        tolerance = ReconciliationTolerance()
        first = reconcile(leg, leg, tolerance)
        second = reconcile(leg, leg, tolerance)
        assert first.outcome is second.outcome
        assert first.difference == second.difference == Decimal("0")
        assert first.fingerprint == second.fingerprint
        assert exact_match(leg, leg)

    @PROPERTY_SETTINGS
    @given(legs=st.lists(payment_legs(), min_size=2, max_size=12))
    def test_duplicate_detection_groups_by_idempotency_key(self, legs: list[PaymentRecord]) -> None:
        """Duplicates are found by idempotency key, and only by that key."""
        duplicates = find_duplicates(legs)
        counts: dict[str, int] = {}
        for leg in legs:
            counts[leg.idempotency_key] = counts.get(leg.idempotency_key, 0) + 1
        assert set(duplicates) == {key for key, count in counts.items() if count > 1}
        for key, group in duplicates.items():
            assert len(group) == counts[key]
            assert all(leg.idempotency_key == key for leg in group)

    @PROPERTY_SETTINGS
    @given(leg=payment_legs())
    def test_canonical_form_is_stable_for_the_same_leg(self, leg: PaymentRecord) -> None:
        """The canonical form of a leg is a pure function of its content."""
        assert canonical_payment(leg) == canonical_payment(leg)


class TestReconciliationConsistency:
    """Property 4 — matching and aggregation preserve the defined totals."""

    @PROPERTY_SETTINGS
    @given(
        processor=payment_legs(),
        ledger=payment_legs(),
        absolute=st.decimals(
            min_value=Decimal("0"), max_value=Decimal("1000"), places=2, allow_nan=False
        ),
    )
    def test_materiality_follows_the_tolerance_allowance(
        self,
        processor: PaymentRecord,
        ledger: PaymentRecord,
        absolute: Decimal,
    ) -> None:
        """MATERIAL exactly when the absolute difference exceeds the allowance."""
        processor = replace(processor, currency="INR")
        ledger = replace(ledger, currency="INR")
        tolerance = ReconciliationTolerance(absolute=absolute)
        result = reconcile(processor, ledger, tolerance)
        allowance = tolerance.apply(abs(processor.net))
        difference = abs(result.difference)
        if difference > allowance:
            assert result.materiality.value == "MATERIAL"
        else:
            assert result.materiality.value == "IMMATERIAL"
        # Boundary: a difference exactly at the allowance is not material.
        assert (difference > allowance) == (result.materiality.value == "MATERIAL")

    @PROPERTY_SETTINGS
    @given(
        processor=payment_legs(),
        ledger=payment_legs(),
        absolute=st.decimals(
            min_value=Decimal("0"), max_value=Decimal("1000"), places=2, allow_nan=False
        ),
    )
    def test_outcome_follows_the_difference(
        self,
        processor: PaymentRecord,
        ledger: PaymentRecord,
        absolute: Decimal,
    ) -> None:
        """The verdict follows from the difference and the allowance."""
        processor = replace(processor, currency="INR")
        ledger = replace(ledger, currency="INR")
        tolerance = ReconciliationTolerance(absolute=absolute)
        result = reconcile(processor, ledger, tolerance)
        allowance = tolerance.apply(abs(processor.net))
        if result.difference == Decimal("0"):
            assert result.outcome.value == "MATCHED"
        elif abs(result.difference) <= allowance:
            assert result.outcome.value == "TOLERANCE_MATCHED"
        else:
            assert result.outcome.value == "EXCEPTION"
            assert result.exception_code

    @PROPERTY_SETTINGS
    @given(leg=payment_legs(), other=payment_legs())
    def test_fingerprint_is_stable_for_the_same_pair(
        self, leg: PaymentRecord, other: PaymentRecord
    ) -> None:
        """The pair fingerprint is a pure function of the two legs."""
        assert fingerprint_pair(leg, other) == fingerprint_pair(leg, other)

    @PROPERTY_SETTINGS
    @given(
        target=payment_legs(),
        candidates=st.lists(payment_legs(), min_size=1, max_size=8),
    )
    def test_match_preserves_the_defined_totals(
        self, target: PaymentRecord, candidates: list[PaymentRecord]
    ) -> None:
        """A matched candidate keeps the target's net within the allowance."""
        target = replace(target, currency="INR")
        candidates = [replace(candidate, currency="INR") for candidate in candidates]
        tolerance = ReconciliationTolerance(absolute=Decimal("1.00"))
        match = find_match(target, candidates, tolerance)
        if match is None:
            return
        difference = abs(match.net - target.net)
        assert tolerance.allows(match.net - target.net, abs(target.net))
        assert difference <= tolerance.apply(abs(target.net))
