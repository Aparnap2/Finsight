"""Matcher and reconciler behavior incl. the flagship partial-refund lag.

Covers exact ``MATCHED``, the flagship 50k-charge / 15k-refund shape
(35k expected vs 50k ledger -> 15000 break, ``PARTIAL_REFUND_ACCOUNTING_LAG``,
``EXCEPTION``/``MATERIAL`` with zero LLM calls), the settled 35k==35k
``MATCHED``, the missing-leg ``PENDING_EVIDENCE`` path, and the
multi-candidate closest-in-tolerance scan.
"""

import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from finance.reconciliation.classifier import classify
from finance.reconciliation.errors import InvariantViolation
from finance.reconciliation.fingerprints import fingerprint_pair
from finance.reconciliation.matcher import exact_match, find_match, within_tolerance
from finance.reconciliation.models import (
    ExceptionCode,
    MaterialityVerdict,
    PaymentRecord,
    PaymentStatus,
    ReconciliationOutcome,
    ReconciliationResult,
)
from finance.reconciliation.reconciler import reconcile
from finance.reconciliation.tolerances import ReconciliationTolerance

_ZERO = ReconciliationTolerance()
_TENANT_ID = "tenant-acme"


def _leg(
    *,
    payment_id: str,
    gross: Decimal,
    fee: Decimal,
    refund: Decimal,
    net: Decimal,
    key: str = "key-shared",
    tenant_id: str = _TENANT_ID,
    currency: str = "USD",
    occurred_at: datetime | None = None,
) -> PaymentRecord:
    """Build one deterministic leg with Decimal-only money."""
    return PaymentRecord(
        payment_id=payment_id,
        provider="stripe",
        provider_event_id=f"evt-{payment_id}",
        idempotency_key=key,
        gross=gross,
        fee=fee,
        refund=refund,
        net=net,
        currency=currency,
        status=PaymentStatus.SETTLED,
        occurred_at=occurred_at or datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
        tenant_id=tenant_id,
    )


def _flagship_pair() -> tuple[PaymentRecord, PaymentRecord]:
    """Flagship lag: 50k gross, 15k refund seen by processor, missed by ledger."""
    expected = _leg(
        payment_id="proc-flagship",
        gross=Decimal("50000.00"),
        fee=Decimal("0.00"),
        refund=Decimal("15000.00"),
        net=Decimal("35000.00"),
        key="key-flagship-001",
    )
    observed = _leg(
        payment_id="ledger-flagship",
        gross=Decimal("50000.00"),
        fee=Decimal("0.00"),
        refund=Decimal("0.00"),
        net=Decimal("50000.00"),
        key="key-flagship-001",
    )
    return expected, observed


class TestExactMatched:
    """Exact agreement closes as MATCHED."""

    def test_identical_nets_match(self) -> None:
        """Arrange equal legs; Act exact_match; Assert True."""
        expected, _ = _flagship_pair()
        twin = _leg(
            payment_id="ledger-twin",
            gross=Decimal("50000.00"),
            fee=Decimal("0.00"),
            refund=Decimal("15000.00"),
            net=Decimal("35000.00"),
            key="key-flagship-001",
        )
        assert exact_match(expected, twin) is True

    def test_reconcile_exact_returns_matched(self) -> None:
        """Reconciling equal nets yields MATCHED, zero diff, null code."""
        expected = _leg(
            payment_id="proc-exact",
            gross=Decimal("35000.00"),
            fee=Decimal("0.00"),
            refund=Decimal("0.00"),
            net=Decimal("35000.00"),
        )
        observed = _leg(
            payment_id="ledger-exact",
            gross=Decimal("35000.00"),
            fee=Decimal("0.00"),
            refund=Decimal("0.00"),
            net=Decimal("35000.00"),
        )
        result = reconcile(expected, observed, _ZERO)
        assert result.outcome is ReconciliationOutcome.MATCHED
        assert result.difference == Decimal("0.00")
        assert result.variance == Decimal("0.00")
        assert result.exception_code is None
        assert result.materiality is MaterialityVerdict.IMMATERIAL
        assert result.fingerprint == fingerprint_pair(expected, observed)

    def test_scale_insensitive_equality_matches(self) -> None:
        """Decimal('35000') equals Decimal('35000.00') numerically."""
        expected = _leg(
            payment_id="proc-scale",
            gross=Decimal("35000"),
            fee=Decimal("0"),
            refund=Decimal("0"),
            net=Decimal("35000"),
        )
        observed = _leg(
            payment_id="ledger-scale",
            gross=Decimal("35000.00"),
            fee=Decimal("0.00"),
            refund=Decimal("0.00"),
            net=Decimal("35000.00"),
        )
        assert exact_match(expected, observed) is True
        assert reconcile(expected, observed, _ZERO).outcome is ReconciliationOutcome.MATCHED


class TestFlagshipPartialRefundLag:
    """Flagship 50k/15k/35k accounting-lag break."""

    def test_flagship_is_exception_with_refund_lag_code(self) -> None:
        """35k expected vs 50k ledger breaks 15000 with the I-REFUND-LAG code."""
        expected, observed = _flagship_pair()
        result = reconcile(expected, observed, _ZERO)
        assert result.outcome is ReconciliationOutcome.EXCEPTION
        assert result.expected == Decimal("35000.00")
        assert result.observed == Decimal("50000.00")
        assert result.difference == Decimal("15000.00")
        assert result.variance == Decimal("15000.00")
        assert result.exception_code == ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG.value
        assert result.exception_code == "I-REFUND-LAG"
        assert result.materiality is MaterialityVerdict.MATERIAL
        assert result.tolerance_applied == Decimal("0")
        assert len(result.fingerprint) == 64

    def test_flagship_classification_is_refund_lag(self) -> None:
        """The classifier attributes gross-agreeing/refund-lagging legs."""
        expected, observed = _flagship_pair()
        assert classify(expected, observed) is ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG

    def test_settled_35k_vs_35k_matches(self) -> None:
        """Once the ledger books the refund, 35k==35k closes MATCHED."""
        expected, _ = _flagship_pair()
        settled = _leg(
            payment_id="ledger-settled",
            gross=Decimal("50000.00"),
            fee=Decimal("0.00"),
            refund=Decimal("15000.00"),
            net=Decimal("35000.00"),
            key="key-flagship-001",
        )
        result = reconcile(expected, settled, _ZERO)
        assert result.outcome is ReconciliationOutcome.MATCHED
        assert result.difference == Decimal("0.00")
        assert result.exception_code is None

    def test_reconcile_is_pure_with_zero_llm_calls(self) -> None:
        """Two runs are byte-identical and no LLM/network stack is touched."""
        expected, observed = _flagship_pair()
        first = reconcile(expected, observed, _ZERO)
        second = reconcile(expected, observed, _ZERO)
        assert first == second
        assert first.fingerprint == second.fingerprint
        assert first.difference == Decimal("15000.00")

        package_dir = Path(__file__).resolve().parents[3] / "finance" / "reconciliation"
        forbidden_imports = (
            "import openai",
            "import anthropic",
            "import langchain",
            "import litellm",
            "import httpx",
            "import requests",
            "import urllib",
            "import socket",
            "import psycopg",
            "import sqlalchemy",
            "import random",
            "from openai",
            "from anthropic",
            "from langchain",
            "from litellm",
            "from httpx",
            "from requests",
            "from urllib",
            "from socket",
            "from random",
            "datetime.now(",
        )
        sources = "".join(
            (package_dir / name).read_text()
            for name in (
                "reconciler.py",
                "matcher.py",
                "classifier.py",
                "tolerances.py",
                "fingerprints.py",
                "models.py",
                "normalizer.py",
            )
        ).lower()
        for token in forbidden_imports:
            assert token not in sources, f"pure core must not reference {token}"
        for module in ("openai", "anthropic", "langchain_core", "litellm"):
            assert module not in sys.modules, f"LLM module {module} must not load"


class TestMissingLegPendingEvidence:
    """A missing leg cannot reconcile and waits for evidence."""

    def test_find_match_empty_returns_none(self) -> None:
        """No candidates means no match (upstream maps to PENDING_EVIDENCE)."""
        target, _ = _flagship_pair()
        assert find_match(target, [], _ZERO) is None

    def test_find_match_all_currency_mismatched_returns_none(self) -> None:
        """Incomparable currencies are skipped, yielding no match."""
        target, _ = _flagship_pair()
        eur = _leg(
            payment_id="ledger-eur",
            gross=Decimal("35000.00"),
            fee=Decimal("0.00"),
            refund=Decimal("0.00"),
            net=Decimal("35000.00"),
            currency="EUR",
        )
        assert find_match(target, [eur], _ZERO) is None

    def test_pending_evidence_result_shape(self) -> None:
        """PENDING_EVIDENCE carries zero diff, null code, stable fingerprint."""
        expected, _ = _flagship_pair()
        pending = ReconciliationResult(
            outcome=ReconciliationOutcome.PENDING_EVIDENCE,
            expected=expected.net,
            observed=expected.net,
            difference=Decimal("0.00"),
            variance=Decimal("0.00"),
            tolerance_applied=Decimal("0"),
            currency=expected.currency,
            exception_code=None,
            fingerprint=fingerprint_pair(expected, expected),
            materiality=MaterialityVerdict.IMMATERIAL,
        )
        assert pending.outcome is ReconciliationOutcome.PENDING_EVIDENCE
        assert pending.exception_code is None
        assert pending.difference == Decimal("0.00")

    def test_non_record_target_rejected(self) -> None:
        """Passing a non-record target raises instead of going pending."""
        with pytest.raises(InvariantViolation):
            find_match("not-a-record", [], _ZERO)  # type: ignore[arg-type]


class TestMultiCandidateClosestInTolerance:
    """1:N scans prefer reference, then exact, then closest-in-tolerance."""

    def _target(self) -> PaymentRecord:
        """Target leg with net 1000.00."""
        return _leg(
            payment_id="target",
            gross=Decimal("1000.00"),
            fee=Decimal("0.00"),
            refund=Decimal("0.00"),
            net=Decimal("1000.00"),
            key="key-target",
        )

    def test_closest_in_tolerance_wins(self) -> None:
        """Of 1000.08 and 1000.03 with +/-0.10, the 0.03 drift wins."""
        target = self._target()
        tolerance = ReconciliationTolerance(absolute=Decimal("0.10"))
        far = _leg(
            payment_id="cand-far",
            gross=Decimal("1000.08"),
            fee=Decimal("0.00"),
            refund=Decimal("0.00"),
            net=Decimal("1000.08"),
            key="key-far",
        )
        near = _leg(
            payment_id="cand-near",
            gross=Decimal("1000.03"),
            fee=Decimal("0.00"),
            refund=Decimal("0.00"),
            net=Decimal("1000.03"),
            key="key-near",
        )
        assert find_match(target, [far, near], tolerance) is near
        assert find_match(target, [near, far], tolerance) is near

    def test_exact_beats_nearer_tolerance_candidate(self) -> None:
        """An exact net wins even when listed after a tolerant candidate."""
        target = self._target()
        tolerance = ReconciliationTolerance(absolute=Decimal("0.10"))
        near = _leg(
            payment_id="cand-near",
            gross=Decimal("1000.03"),
            fee=Decimal("0.00"),
            refund=Decimal("0.00"),
            net=Decimal("1000.03"),
            key="key-near",
        )
        exact = _leg(
            payment_id="cand-exact",
            gross=Decimal("1000.00"),
            fee=Decimal("0.00"),
            refund=Decimal("0.00"),
            net=Decimal("1000.00"),
            key="key-exact",
        )
        assert find_match(target, [near, exact], tolerance) is exact

    def test_reference_linkage_wins_within_tolerance(self) -> None:
        """Same idempotency_key wins when its net fits the window."""
        target = self._target()
        tolerance = ReconciliationTolerance(absolute=Decimal("0.10"))
        linked = _leg(
            payment_id="cand-linked",
            gross=Decimal("1000.09"),
            fee=Decimal("0.00"),
            refund=Decimal("0.00"),
            net=Decimal("1000.09"),
            key="key-target",
        )
        closer = _leg(
            payment_id="cand-closer",
            gross=Decimal("1000.01"),
            fee=Decimal("0.00"),
            refund=Decimal("0.00"),
            net=Decimal("1000.01"),
            key="key-other",
        )
        assert find_match(target, [closer, linked], tolerance) is linked

    def test_outside_tolerance_returns_none(self) -> None:
        """Nothing within +/-0.10 matches a 1000.50 candidate."""
        target = self._target()
        tolerance = ReconciliationTolerance(absolute=Decimal("0.10"))
        outsider = _leg(
            payment_id="cand-out",
            gross=Decimal("1000.50"),
            fee=Decimal("0.00"),
            refund=Decimal("0.00"),
            net=Decimal("1000.50"),
            key="key-out",
        )
        assert find_match(target, [outsider], tolerance) is None
        assert within_tolerance(target, outsider, tolerance) is False

    def test_window_seconds_gates_match(self) -> None:
        """A candidate outside the time window is skipped."""
        target = self._target()
        tolerance = ReconciliationTolerance(absolute=Decimal("100.00"))
        late = _leg(
            payment_id="cand-late",
            gross=Decimal("1000.00"),
            fee=Decimal("0.00"),
            refund=Decimal("0.00"),
            net=Decimal("1000.00"),
            key="key-late",
            occurred_at=datetime(2026, 5, 2, 12, 0, 0, tzinfo=UTC),
        )
        assert find_match(target, [late], tolerance, window_seconds=60) is None
        assert find_match(target, [late], tolerance, window_seconds=90000) is late
