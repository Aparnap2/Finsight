"""The 16 normative acceptance scenarios from spec section 5 (RED first).

Each scenario builds canonical facts with Decimal-only INR money and
drives ``finance.detection.engine.detect`` plus the creation, pending,
and escalation helpers. Forbidden variances (27500 / 17500) must never
size a case; the actionable variance is books minus provider only.
"""

from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256

import pytest
from pydantic import ValidationError

from finance.business_rules.meridian import CompanyConfiguration
from finance.detection.classification import (
    CASE_CREATING_CLASSIFICATIONS,
    DetectionClassification,
    map_p1_code,
    spec_code_for,
)
from finance.detection.creation import allocate_situation_id, creation_rules
from finance.detection.engine import (
    DetectionOutcome,
    DetectionVerdict,
    detect,
)
from finance.detection.escalation import decide_escalation
from finance.detection.pending import emit_pending
from finance.domain.financial_situation import SituationStatus
from finance.facts.books import BooksFact
from finance.facts.expected import ExpectedFact
from finance.facts.legacy import LegacyFact
from finance.facts.provenance import FactProvenance
from finance.facts.provider import ProviderNetFact, decompose_provider_net
from finance.reconciliation.errors import CurrencyMismatch
from finance.reconciliation.models import ExceptionCode

_AT = datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)
_TOL = CompanyConfiguration().tolerance_minor


def _hash(tag: str) -> str:
    """Return a deterministic 64-hex digest for a tag."""
    return sha256(tag.encode("utf-8")).hexdigest()


def _prov(tag: str, endpoint: str = "C-TEST") -> FactProvenance:
    """Build a valid provenance with a deterministic hash."""
    return FactProvenance(
        adapter="test-adapter-v1",
        endpoint=endpoint,
        correlation_id=f"corr-{tag}",
        content_hash=_hash(tag),
        retrieved_at=_AT,
    )


def _expected(total: str, tag: str) -> ExpectedFact:
    """Build a sheets expected fact for a decimal total."""
    return ExpectedFact(
        fact_id=f"exp-{tag}",
        batch_id="BATCH-1",
        expected_total=Decimal(total),
        observed_at=_AT,
        provenance=_prov(f"exp-{tag}", "C-SHEETS"),
    )


def _provider(
    gross: str,
    fee: str,
    refund: str,
    adj: str,
    pend: str,
    tag: str,
) -> ProviderNetFact:
    """Build a provider-net fact via the five-term decomposition."""
    return decompose_provider_net(
        Decimal(gross),
        Decimal(fee),
        Decimal(refund),
        Decimal(adj),
        Decimal(pend),
        provenance=_prov(f"prov-{tag}", "C-RAZORPAY"),
        fact_id=f"prov-{tag}",
        batch_id="BATCH-1",
    )


def _books(
    total: str,
    tag: str,
    *,
    booked_fee: str | None = None,
    duplicate_key: str | None = None,
) -> BooksFact:
    """Build a books fact with optional fee-slice and duplicate hooks."""
    return BooksFact(
        fact_id=f"qb-{tag}",
        batch_id="BATCH-1",
        qb_total=Decimal(total),
        period="2026-09",
        period_open=True,
        booked_fee=Decimal(booked_fee) if booked_fee is not None else None,
        duplicate_key=duplicate_key,
        posted_at=_AT,
        provenance=_prov(f"qb-{tag}", "C-QUICKBOOKS"),
    )


def _legacy(
    accepted: str,
    rejected: str,
    tag: str,
    reason: str | None = None,
) -> LegacyFact:
    """Build a legacy posting fact with a verbatim reason."""
    return LegacyFact(
        fact_id=f"leg-{tag}",
        batch_id="BATCH-1",
        accepted_total=Decimal(accepted),
        rejected_total=Decimal(rejected),
        rejected_reason=reason,
        posted_at=_AT,
        provenance=_prov(f"leg-{tag}", "C-LEGACY"),
    )


def test_scenario_01_exact_match_creates_nothing() -> None:
    """Scenario 1: exact agreement yields MATCHED with no situation."""
    verdict = detect(
        expected=_expected("496250", "s01"),
        provider=_provider("500000", "3750", "0", "0", "0", "s01"),
        books=_books("496250", "s01"),
        legacy=_legacy("496250", "0", "s01"),
    )
    assert verdict.verdict is DetectionOutcome.MATCHED
    assert verdict.actionable_variance == Decimal("0")
    assert verdict.expected_books_gap == Decimal("0")
    assert verdict.classification is DetectionClassification.MATCHED
    assert verdict.situation_id is None
    situation = creation_rules(
        verdict,
        expected=_expected("496250", "s01"),
        provider=_provider("500000", "3750", "0", "0", "0", "s01"),
        books=_books("496250", "s01"),
        legacy=_legacy("496250", "0", "s01"),
        date_str="2026-09-17",
        seq=1,
    )
    assert situation is None


def test_scenario_02_within_tolerance_creates_nothing() -> None:
    """Scenario 2: variance 1 sits inside tolerance, no situation."""
    verdict = detect(
        expected=_expected("496250", "s02"),
        provider=_provider("500000", "3750", "0", "0", "0", "s02"),
        books=_books("496251", "s02"),
        legacy=_legacy("496251", "0", "s02"),
    )
    assert verdict.verdict is DetectionOutcome.WITHIN_TOLERANCE
    assert verdict.actionable_variance == Decimal("1")
    assert verdict.situation_id is None
    assert (
        creation_rules(
            verdict,
            expected=_expected("496250", "s02"),
            provider=_provider("500000", "3750", "0", "0", "0", "s02"),
            books=_books("496251", "s02"),
            legacy=_legacy("496251", "0", "s02"),
            date_str="2026-09-17",
            seq=2,
        )
        is None
    )


def test_scenario_03_outside_tolerance_opens_case() -> None:
    """Scenario 3: variance 101 opens a DETECTED case sized at 101."""
    expected = _expected("496250", "s03")
    provider = _provider("500000", "3750", "0", "0", "0", "s03")
    books = _books("496351", "s03")
    legacy = _legacy("496351", "0", "s03")
    verdict = detect(
        expected=expected, provider=provider, books=books, legacy=legacy
    )
    assert verdict.verdict is DetectionOutcome.EXCEPTION
    assert verdict.actionable_variance == Decimal("101")
    assert verdict.classification in CASE_CREATING_CLASSIFICATIONS
    situation = creation_rules(
        verdict,
        expected=expected,
        provider=provider,
        books=books,
        legacy=legacy,
        date_str="2026-09-17",
        seq=3,
    )
    assert situation is not None
    assert situation.status is SituationStatus.DETECTED
    assert situation.variance() == Decimal("101")


def test_scenario_04_fee_mismatch() -> None:
    """Scenario 4: fee delta 500 with residual 500 is FEE_MISMATCH."""
    expected = _expected("193000", "s04")
    provider = _provider("200000", "7500", "0", "0", "0", "s04")
    books = _books("193000", "s04", booked_fee="7000")
    legacy = _legacy("193000", "0", "s04")
    verdict = detect(
        expected=expected, provider=provider, books=books, legacy=legacy
    )
    assert verdict.verdict is DetectionOutcome.EXCEPTION
    assert verdict.classification is DetectionClassification.FEE_MISMATCH
    assert verdict.actionable_variance == Decimal("500")
    situation = creation_rules(
        verdict,
        expected=expected,
        provider=provider,
        books=books,
        legacy=legacy,
        date_str="2026-09-17",
        seq=4,
    )
    assert situation is not None
    assert situation.variance() == Decimal("500")


def test_scenario_05_refund_lag() -> None:
    """Scenario 5: a 2500 refund missing in-window is PARTIAL_REFUND_LAG."""
    expected = _expected("496250", "s05")
    provider = _provider("500000", "3750", "2500", "0", "0", "s05")
    books = _books("496250", "s05")
    legacy = _legacy("496250", "0", "s05")
    verdict = detect(
        expected=expected, provider=provider, books=books, legacy=legacy
    )
    assert verdict.verdict is DetectionOutcome.EXCEPTION
    assert verdict.classification is DetectionClassification.PARTIAL_REFUND_LAG
    assert verdict.actionable_variance == Decimal("2500")


def test_scenario_06_duplicate_needs_fingerprint() -> None:
    """Scenario 6: same fingerprint duplicates; amount-only never does."""
    expected = _expected("496250", "s06")
    provider = _provider("500000", "3750", "0", "0", "0", "s06")
    dup_books = _books("498750", "s06", duplicate_key="idem-xyz")
    legacy = _legacy("498750", "0", "s06")
    verdict = detect(
        expected=expected, provider=provider, books=dup_books, legacy=legacy
    )
    assert verdict.classification is DetectionClassification.DUPLICATE_LEDGER_ENTRY
    assert verdict.actionable_variance == Decimal("2500")
    plain_books = _books("498750", "s06-plain")
    plain = detect(
        expected=expected, provider=provider, books=plain_books, legacy=legacy
    )
    assert plain.classification is not DetectionClassification.DUPLICATE_LEDGER_ENTRY


def test_scenario_07_legacy_posting_missing() -> None:
    """Scenario 7: an RJ record with residual 10000 is LEGACY_POSTING_MISSING."""
    expected = _expected("486250", "s07")
    provider = _provider("500000", "3750", "0", "0", "0", "s07")
    books = _books("486250", "s07")
    legacy = _legacy("486250", "10000", "s07", "INVALID_ACCOUNT_CODE")
    verdict = detect(
        expected=expected, provider=provider, books=books, legacy=legacy
    )
    assert verdict.classification is DetectionClassification.LEGACY_POSTING_MISSING
    assert abs(verdict.actionable_variance) == Decimal("10000")
    missing = detect(
        expected=expected, provider=provider, books=books, legacy=None
    )
    assert missing.classification is DetectionClassification.LEGACY_POSTING_MISSING


def test_scenario_08_fs231_golden() -> None:
    """Scenario 8: FS-231 yields one case with actionable exactly 10000."""
    expected = _expected("1000000", "s08")
    provider = _provider("1000000", "7500", "2500", "10000", "7500", "s08")
    assert provider.net == Decimal("972500")
    books = _books("982500", "s08")
    legacy = _legacy("982500", "10000", "s08", "INVALID_ACCOUNT_CODE")
    verdict = detect(
        expected=expected, provider=provider, books=books, legacy=legacy
    )
    assert verdict.verdict is DetectionOutcome.EXCEPTION
    assert verdict.actionable_variance == Decimal("10000")
    assert verdict.expected_books_gap == Decimal("17500")
    assert verdict.classification is DetectionClassification.LEGACY_POSTING_MISSING


def test_scenario_09_forbidden_variance_guard() -> None:
    """Scenario 9: filing 27500 or 17500 as actionable is rejected."""
    expected = _expected("1000000", "s09")
    provider = _provider("1000000", "7500", "2500", "10000", "7500", "s09")
    books = _books("982500", "s09")
    legacy = _legacy("982500", "10000", "s09", "INVALID_ACCOUNT_CODE")
    verdict = detect(
        expected=expected, provider=provider, books=books, legacy=legacy
    )
    assert verdict.actionable_variance == Decimal("10000")
    assert verdict.actionable_variance != Decimal("27500")
    assert verdict.actionable_variance != Decimal("17500")
    assert verdict.expected_books_gap == Decimal("17500")
    situation = creation_rules(
        verdict,
        expected=expected,
        provider=provider,
        books=books,
        legacy=legacy,
        date_str="2026-09-17",
        seq=9,
    )
    assert situation is not None
    assert situation.variance() == Decimal("10000")
    assert situation.variance() != Decimal("27500")
    assert situation.variance() != Decimal("17500")


def test_scenario_10_idempotent_redelivery() -> None:
    """Scenario 10: identical redelivery absorbs with no duplicate case."""
    expected = _expected("496250", "s10")
    provider = _provider("500000", "3750", "2500", "0", "0", "s10")
    books = _books("496250", "s10")
    legacy = _legacy("496250", "0", "s10")
    first = detect(
        expected=expected, provider=provider, books=books, legacy=legacy
    )
    second = detect(
        expected=expected, provider=provider, books=books, legacy=legacy
    )
    assert first.fingerprint == second.fingerprint
    assert first == second
    one = creation_rules(
        verdict=first,
        expected=expected,
        provider=provider,
        books=books,
        legacy=legacy,
        date_str="2026-09-17",
        seq=10,
    )
    two = creation_rules(
        verdict=second,
        expected=expected,
        provider=provider,
        books=books,
        legacy=legacy,
        date_str="2026-09-17",
        seq=10,
    )
    assert one is not None and two is not None
    assert one.situation_id == two.situation_id
    assert one == two


def test_scenario_11_conflicting_same_id_facts() -> None:
    """Scenario 11: same id with different bodies is CONFLICTING_AUTHORITIES."""
    expected = ExpectedFact(
        fact_id="ext-1",
        batch_id="BATCH-1",
        expected_total=Decimal("10000"),
        observed_at=_AT,
        provenance=_prov("conflict-a", "C-SHEETS"),
    )
    provider = _provider("500000", "3750", "0", "0", "0", "s11")
    books = BooksFact(
        fact_id="ext-1",
        batch_id="BATCH-1",
        qb_total=Decimal("12000"),
        period="2026-09",
        period_open=True,
        posted_at=_AT,
        provenance=_prov("conflict-b", "C-QUICKBOOKS"),
    )
    legacy = _legacy("12000", "0", "s11")
    verdict = detect(
        expected=expected, provider=provider, books=books, legacy=legacy
    )
    assert verdict.verdict is DetectionOutcome.CONFLICTING_AUTHORITIES
    assert verdict.classification is DetectionClassification.CONFLICTING_AUTHORITIES
    situation = creation_rules(
        verdict,
        expected=expected,
        provider=provider,
        books=books,
        legacy=legacy,
        date_str="2026-09-17",
        seq=11,
    )
    assert situation is not None
    assert situation.status is SituationStatus.DETECTED
    assert _hash("conflict-a") in situation.evidence_ids
    assert _hash("conflict-b") in situation.evidence_ids


def test_scenario_12_float_rejected() -> None:
    """Scenario 12: float facts never enter equations; gap stays pending."""
    with pytest.raises(ValidationError):
        ProviderNetFact(
            fact_id="prov-fl",
            batch_id="BATCH-1",
            gross=500000.0,  # type: ignore[arg-type]
            fee=Decimal("3750"),
            refund=Decimal("0"),
            adjustment=Decimal("0"),
            pending=Decimal("0"),
            observed_at=_AT,
            provenance=_prov("prov-fl", "C-RAZORPAY"),
        )
    verdict = detect(
        expected=_expected("496250", "s12"),
        provider=None,
        books=_books("496250", "s12"),
        legacy=None,
    )
    assert verdict.verdict is DetectionOutcome.PENDING_EVIDENCE
    assert verdict.classification is DetectionClassification.INSUFFICIENT_EVIDENCE


def test_scenario_13_currency_mismatch_rejected() -> None:
    """Scenario 13: non-INR facts are rejected; mixed pairs never compare."""
    with pytest.raises(ValidationError):
        ExpectedFact(
            fact_id="exp-usd",
            batch_id="BATCH-1",
            expected_total=Decimal("100"),
            currency="USD",
            observed_at=_AT,
            provenance=_prov("exp-usd", "C-SHEETS"),
        )
    provider = _provider("500000", "3750", "0", "0", "0", "s13")
    books = _books("496250", "s13").model_copy(update={"currency": "USD"})
    with pytest.raises(CurrencyMismatch):
        detect(
            expected=_expected("496250", "s13"),
            provider=provider,
            books=books,
            legacy=None,
        )


def test_scenario_14_missing_provenance_rejected() -> None:
    """Scenario 14: anonymous facts are rejected; creation stays refused."""
    with pytest.raises(ValidationError):
        ExpectedFact(
            fact_id="exp-np",
            batch_id="BATCH-1",
            expected_total=Decimal("496250"),
            observed_at=_AT,
            provenance=None,  # type: ignore[arg-type]
        )
    verdict = detect(
        expected=None,
        provider=_provider("500000", "3750", "0", "0", "0", "s14"),
        books=_books("496250", "s14"),
        legacy=None,
    )
    assert verdict.verdict is DetectionOutcome.PENDING_EVIDENCE
    assert (
        creation_rules(
            verdict,
            expected=None,
            provider=_provider("500000", "3750", "0", "0", "0", "s14"),
            books=_books("496250", "s14"),
            legacy=None,
            date_str="2026-09-17",
            seq=14,
        )
        is None
    )


def test_scenario_15_partial_data_stays_unknown() -> None:
    """Scenario 15: absent QB legs yield UNKNOWN with missing legs named."""
    verdict = detect(
        expected=_expected("496250", "s15"),
        provider=_provider("500000", "3750", "0", "0", "0", "s15"),
        books=None,
        legacy=None,
    )
    assert verdict.verdict is DetectionOutcome.PENDING_EVIDENCE
    assert verdict.classification is DetectionClassification.INSUFFICIENT_EVIDENCE
    pending = emit_pending("qb-s15", {"qb_total", "posted_at"}, "BATCH-1")
    assert pending.fact_id == "qb-s15"
    assert {"qb_total", "posted_at"} <= set(pending.missing_fields)
    assert len(pending.fingerprint) == 64


def test_scenario_16_conflict_routes_to_human_review() -> None:
    """Scenario 16: conflicts escalate; auto-resolve stays forbidden."""
    decision = decide_escalation(
        variance=Decimal("2000"), legacy_involved=True
    )
    assert decision.requires_approval is True
    assert decision.route == "HUMAN_REVIEW"
    expected = ExpectedFact(
        fact_id="ext-16",
        batch_id="BATCH-1",
        expected_total=Decimal("10000"),
        observed_at=_AT,
        provenance=_prov("conflict-16a", "C-SHEETS"),
    )
    provider = _provider("500000", "3750", "0", "0", "0", "s16")
    books = BooksFact(
        fact_id="ext-16",
        batch_id="BATCH-1",
        qb_total=Decimal("12000"),
        period="2026-09",
        period_open=True,
        posted_at=_AT,
        provenance=_prov("conflict-16b", "C-QUICKBOOKS"),
    )
    verdict = detect(
        expected=expected,
        provider=provider,
        books=books,
        legacy=_legacy("12000", "0", "s16"),
    )
    assert verdict.verdict is DetectionOutcome.CONFLICTING_AUTHORITIES
    situation = creation_rules(
        verdict,
        expected=expected,
        provider=provider,
        books=books,
        legacy=_legacy("12000", "0", "s16"),
        date_str="2026-09-17",
        seq=16,
    )
    assert situation is not None
    assert situation.status is SituationStatus.DETECTED


class TestCatalogWiring:
    """The 8-label catalog wraps the frozen P1 codes without extending them."""

    def test_p1_codes_map(self) -> None:
        """All three frozen P1 codes map onto catalog labels."""
        assert (
            map_p1_code(ExceptionCode.FEE_MISMATCH)
            is DetectionClassification.FEE_MISMATCH
        )
        assert (
            map_p1_code(ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG)
            is DetectionClassification.PARTIAL_REFUND_LAG
        )
        assert (
            map_p1_code(ExceptionCode.DUPLICATE_LEDGER_ENTRY)
            is DetectionClassification.DUPLICATE_LEDGER_ENTRY
        )

    def test_spec_codes_from_ontology(self) -> None:
        """Spec I-codes resolve through FinancialOntology, never literals."""
        assert spec_code_for(DetectionClassification.FEE_MISMATCH) == "I-FEE-DRIFT"
        assert (
            spec_code_for(DetectionClassification.LEGACY_POSTING_MISSING)
            == "I-LEGACY-REJECT"
        )

    def test_situation_id_allocator(self) -> None:
        """Allocator shapes FS-YYYY-MMDD-NNNNN with caller-supplied date.

        Adjudicated to the frozen aggregate validator (FS-\\d{4}-\\d{4}-
        \\d{5}): a compact datestamp would mint ids FinancialSituation
        rejects, so the allocator emits the persistable dashed shape.
        """
        assert allocate_situation_id("2026-09-17", 231) == "FS-2026-0917-00231"

    def test_verdict_model_frozen(self) -> None:
        """Detection verdicts are immutable once computed."""
        verdict = detect(
            expected=_expected("496250", "fz"),
            provider=_provider("500000", "3750", "0", "0", "0", "fz"),
            books=_books("496250", "fz"),
            legacy=_legacy("496250", "0", "fz"),
        )
        assert isinstance(verdict, DetectionVerdict)
        with pytest.raises(ValidationError):
            verdict.actionable_variance = Decimal("1")  # type: ignore[misc]
