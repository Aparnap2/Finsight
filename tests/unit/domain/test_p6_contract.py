"""TDD contract tests for P6-01 Meridian reconciliation (FS-231 golden).

Covers ``finance/domain/financial_situation.py``,
``finance/domain/ontology.py``, ``finance/domain/account_mappings.py``,
``finance/business_rules/meridian.py`` and
``finance/integration/registry.py`` against the frozen
``docs/domain/meridian-process-model.md`` spec. All figures come from
``tests/fixtures/reconciliation/meridian/``; the 4-way correlator test
calls the real frozen P1 ``reconcile()`` (pure, no network).
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from finance.business_rules.meridian import (
    CompanyConfiguration,
    MeridianBusinessRules,
    RefundAuthority,
)
from finance.domain.account_mappings import (
    ACCOUNT_MAPPINGS,
    is_valid_cobol_code,
    lookup_by_cobol,
)
from finance.domain.financial_situation import FinancialSituation, SituationStatus
from finance.domain.ontology import (
    DISCREPANCY_CATALOG,
    DiscrepancyType,
    FinancialOntology,
    LegacyRejectionReason,
)
from finance.integration.registry import INTEGRATIONS, compare_financial_states
from finance.reconciliation.models import ExceptionCode, ReconciliationOutcome

MERIDIAN_FIXTURES = (
    Path(__file__).parents[2] / "fixtures" / "reconciliation" / "meridian"
)
"""Directory holding the FS-231 golden fixtures."""

SITUATION_ID = "FS-2026-0916-00231"
"""Golden FinancialSituation id from the process-model worked example."""


def _load_fixture(name: str) -> dict[str, str]:
    """Load a meridian JSON fixture as a raw string-valued mapping."""
    path = MERIDIAN_FIXTURES / name
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)  # type: ignore[no-any-return]


def _decimal(value: str) -> Decimal:
    """Parse a fixture money string into an exact Decimal."""
    return Decimal(value)


def _fs231(**overrides: object) -> FinancialSituation:
    """Build the golden FS-231 FinancialSituation (status DETECTED)."""
    fields: dict[str, object] = {
        "situation_id": SITUATION_ID,
        "company_id": "meridian",
        "expected": Decimal("1000000"),
        "razorpay_net": Decimal("972500"),
        "quickbooks": Decimal("982500"),
        "legacy": Decimal("982500"),
        "status": SituationStatus.DETECTED,
    }
    fields.update(overrides)
    return FinancialSituation(**fields)  # type: ignore[arg-type]


def test_fs231_expected_fixture_total() -> None:
    """Sheets expected state is exactly 1000000 INR for meridian."""
    data = _load_fixture("fs_231_expected.json")
    assert data["company_id"] == "meridian"
    assert data["currency"] == "INR"
    assert _decimal(data["expected_total"]) == Decimal("1000000")


def test_fs231_razorpay_net_decomposition_sums() -> None:
    """Provider net is gross minus fee, refund, adjustment and pending."""
    data = _load_fixture("fs_231_razorpay.json")
    gross = _decimal(data["gross"])
    assert gross == Decimal("1000000")
    computed = (
        gross
        - _decimal(data["fee"])
        - _decimal(data["refund"])
        - _decimal(data["adjustment"])
        - _decimal(data["pending"])
    )
    assert computed == _decimal(data["net"]) == Decimal("972500")
    assert _decimal(data["fee"]) == Decimal("7500")
    assert _decimal(data["refund"]) == Decimal("2500")
    assert _decimal(data["adjustment"]) == Decimal("10000")
    assert _decimal(data["pending"]) == Decimal("7500")


def test_fs231_quickbooks_and_legacy_totals() -> None:
    """QB and legacy agree at 982500; the QB gap to expected is 17500."""
    qb = _load_fixture("fs_231_qb.json")
    legacy = _load_fixture("fs_231_legacy.json")
    assert _decimal(qb["quickbooks_total"]) == Decimal("982500")
    assert _decimal(legacy["accepted_total"]) == Decimal("982500")
    assert legacy["batch_id"] == "LEGACY-20260916-0042"


def test_fs231_legacy_batch_accept_reject_counts() -> None:
    """Legacy batch sent 500 records: 499 accepted, 1 rejected."""
    legacy = _load_fixture("fs_231_legacy.json")
    assert int(legacy["records_sent"]) == 500
    assert int(legacy["accepted"]) == 499
    assert int(legacy["rejected"]) == 1
    assert int(legacy["accepted"]) + int(legacy["rejected"]) == int(
        legacy["records_sent"]
    )


def test_fs231_rejected_record_is_4812_invalid_account_code() -> None:
    """The single rejection is INVALID_ACCOUNT_CODE on code 4812 (10000)."""
    legacy = _load_fixture("fs_231_legacy.json")
    rejections = legacy["rejections"]
    assert isinstance(rejections, list) and len(rejections) == 1
    rejected = rejections[0]
    assert rejected["reason"] == "INVALID_ACCOUNT_CODE"
    assert rejected["account_code"] == "4812"
    assert _decimal(rejected["amount"]) == Decimal("10000")
    assert not is_valid_cobol_code("9999")
    assert is_valid_cobol_code("4812")


def test_fs231_variance_is_exactly_10000() -> None:
    """Golden variance: QB minus provider net equals the rejected leg."""
    situation = _fs231()
    assert situation.situation_id == SITUATION_ID
    assert situation.company_id == "meridian"
    assert situation.variance() == Decimal("10000")


def test_financial_situation_rejects_float_money() -> None:
    """Float money is rejected at the Pydantic boundary (Decimal only)."""
    with pytest.raises(ValidationError):
        _fs231(expected=1000000.0)


def test_financial_situation_rejects_non_meridian_company() -> None:
    """Single-company boundary: only company_id meridian is accepted."""
    with pytest.raises(ValidationError):
        _fs231(company_id="acme")


def test_financial_situation_rejects_bad_situation_id() -> None:
    """Situation ids must match the FS-YYYYMMDD-NNNNN shape."""
    with pytest.raises(ValidationError):
        _fs231(situation_id="not-a-situation")


def test_financial_situation_is_frozen() -> None:
    """The aggregate is immutable; state changes go via transition_to."""
    situation = _fs231()
    with pytest.raises(ValidationError):
        situation.status = SituationStatus.CLOSED  # type: ignore[misc]


def test_lifecycle_full_forward_chain() -> None:
    """The canonical chain walks DETECTED all the way to CLOSED."""
    chain = [
        SituationStatus.DETECTED,
        SituationStatus.TRIAGED,
        SituationStatus.INVESTIGATING,
        SituationStatus.CORRELATED,
        SituationStatus.EXPLAINED,
        SituationStatus.PROPOSED,
        SituationStatus.APPROVED,
        SituationStatus.EXECUTING,
        SituationStatus.VERIFYING,
        SituationStatus.CLOSED,
    ]
    situation = _fs231(status=chain[0])
    for target in chain[1:]:
        situation = situation.transition_to(target)
        assert situation.status is target
    assert situation.situation_id == SITUATION_ID


def test_lifecycle_proposed_may_reject() -> None:
    """PROPOSED -> REJECTED is the terminal refusal path for a version."""
    situation = _fs231(status=SituationStatus.PROPOSED)
    refused = situation.transition_to(SituationStatus.REJECTED)
    assert refused.status is SituationStatus.REJECTED


def test_lifecycle_verifying_may_reinvestigate() -> None:
    """VERIFYING -> INVESTIGATING reopens work after a FAILED verdict."""
    situation = _fs231(status=SituationStatus.VERIFYING)
    reopened = situation.transition_to(SituationStatus.INVESTIGATING)
    assert reopened.status is SituationStatus.INVESTIGATING


def test_lifecycle_escalation_and_return() -> None:
    """Any active state may escalate; escalation returns to the chain."""
    escalated = _fs231(status=SituationStatus.INVESTIGATING).transition_to(
        SituationStatus.ESCALATED
    )
    assert escalated.status is SituationStatus.ESCALATED
    assert (
        escalated.transition_to(SituationStatus.INVESTIGATING).status
        is SituationStatus.INVESTIGATING
    )
    assert (
        escalated.transition_to(SituationStatus.PROPOSED).status
        is SituationStatus.PROPOSED
    )


def test_lifecycle_banned_transitions() -> None:
    """No execution without approval; no close without verification."""
    with pytest.raises(ValueError, match="EXECUTING"):
        _fs231(status=SituationStatus.INVESTIGATING).transition_to(
            SituationStatus.EXECUTING
        )
    with pytest.raises(ValueError, match="EXECUTING"):
        _fs231(status=SituationStatus.PROPOSED).transition_to(
            SituationStatus.EXECUTING
        )
    with pytest.raises(ValueError, match="CLOSED"):
        _fs231(status=SituationStatus.DETECTED).transition_to(SituationStatus.CLOSED)
    with pytest.raises(ValueError, match="CLOSED"):
        _fs231(status=SituationStatus.CLOSED).transition_to(
            SituationStatus.INVESTIGATING
        )
    with pytest.raises(ValueError, match="REJECTED"):
        _fs231(status=SituationStatus.REJECTED).transition_to(
            SituationStatus.PROPOSED
        )


def test_refund_approval_tiers() -> None:
    """4999 auto-approves; 5000/50000 need a manager; 50001 a director."""
    rules = MeridianBusinessRules()
    assert rules.evaluate_refund(Decimal("4999")) is RefundAuthority.AUTO
    assert rules.evaluate_refund(Decimal("5000")) is RefundAuthority.MANAGER
    assert rules.evaluate_refund(Decimal("50000")) is RefundAuthority.MANAGER
    assert rules.evaluate_refund(Decimal("50001")) is RefundAuthority.DIRECTOR


def test_refund_rejects_float_and_negative() -> None:
    """Refunds are Decimal-only and never negative."""
    rules = MeridianBusinessRules()
    with pytest.raises((TypeError, ValidationError, ValueError)):
        rules.evaluate_refund(4999.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="[Nn]egative"):
        rules.evaluate_refund(Decimal("-1"))


def test_legacy_correction_always_requires_approval() -> None:
    """Legacy corrections always need human approval (no auto path)."""
    assert MeridianBusinessRules().legacy_always_requires_approval() is True


def test_closed_period_never_modifies() -> None:
    """Closed accounting periods hard-block mutation; open ones pass."""
    rules = MeridianBusinessRules()
    assert rules.closed_period_never_modify("2026-09", frozenset({"2026-09"})) is True
    assert rules.closed_period_never_modify("2026-10", frozenset({"2026-09"})) is False


def test_company_configuration_defaults() -> None:
    """Meridian config: INR, minor tolerance 100, auto limit 500000."""
    config = CompanyConfiguration()
    assert config.company_id == "meridian"
    assert config.base_currency == "INR"
    assert config.tolerance_minor == Decimal("100")
    assert config.auto_approval_limit == Decimal("500000")
    assert config.legacy_correction_requires_approval is True


def test_company_configuration_rejects_other_company() -> None:
    """CompanyConfiguration is frozen to the single-company boundary."""
    with pytest.raises(ValidationError):
        CompanyConfiguration(company_id="acme")


def test_ontology_catalog_has_six_types() -> None:
    """The Meridian catalog holds exactly the six spec variance types."""
    assert len(DISCREPANCY_CATALOG) == 6
    assert {item.value for item in DISCREPANCY_CATALOG} == {
        "fee-mismatch",
        "refund-lag",
        "legacy-rejection",
        "timing-difference",
        "duplicate",
        "adjustment",
    }


def test_ontology_maps_core_types_to_frozen_exception_codes() -> None:
    """Fee, refund-lag and duplicate map onto the frozen P1 I-codes."""
    assert (
        FinancialOntology(
            discrepancy=DiscrepancyType.FEE_MISMATCH
        ).exception_code
        is ExceptionCode.FEE_MISMATCH
    )
    assert (
        FinancialOntology(
            discrepancy=DiscrepancyType.REFUND_LAG
        ).exception_code
        is ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG
    )
    assert (
        FinancialOntology(discrepancy=DiscrepancyType.DUPLICATE).exception_code
        is ExceptionCode.DUPLICATE_LEDGER_ENTRY
    )


def test_ontology_legacy_rejection_uses_spec_code() -> None:
    """Legacy rejection has no P1 counterpart: frozen code None, spec I-code set."""
    finding = FinancialOntology(
        discrepancy=DiscrepancyType.LEGACY_REJECTION,
        legacy_reason=LegacyRejectionReason.INVALID_ACCOUNT_CODE,
        offending_account_code="4812",
    )
    assert finding.exception_code is None
    assert finding.spec_code == "I-LEGACY-REJECT"
    assert (
        FinancialOntology(
            discrepancy=DiscrepancyType.TIMING_DIFFERENCE
        ).spec_code
        == "I-TIMING"
    )
    assert (
        FinancialOntology(discrepancy=DiscrepancyType.ADJUSTMENT).spec_code
        == "I-ADJUSTMENT"
    )


def test_ontology_requires_reason_for_legacy_rejection() -> None:
    """I-LEGACY-REJECT must carry the COBOL reason verbatim plus the code."""
    with pytest.raises(ValidationError):
        FinancialOntology(discrepancy=DiscrepancyType.LEGACY_REJECTION)
    with pytest.raises(ValidationError):
        FinancialOntology(
            discrepancy=DiscrepancyType.FEE_MISMATCH,
            legacy_reason=LegacyRejectionReason.INVALID_ACCOUNT_CODE,
        )


def test_account_mappings_cover_razorpay_qb_cobol() -> None:
    """Every mapping row binds a Razorpay event to QB and COBOL codes."""
    assert len(ACCOUNT_MAPPINGS) >= 5
    for mapping in ACCOUNT_MAPPINGS:
        assert mapping.razorpay_event.strip()
        assert mapping.quickbooks_account.strip()
        assert mapping.cobol_gl_code.strip()
        assert is_valid_cobol_code(mapping.cobol_gl_code)


def test_account_mappings_4812_is_correction_code() -> None:
    """Code 4812 is the valid correction-leg account for the FS-231 reprocess."""
    mapping = lookup_by_cobol("4812")
    assert mapping is not None
    assert is_valid_cobol_code("4812")
    assert lookup_by_cobol("9999") is None


def test_integration_registry_has_six_entries() -> None:
    """The static registry holds exactly the six spec authorities."""
    assert len(INTEGRATIONS) == 6
    assert {entry.name for entry in INTEGRATIONS} == {
        "razorpay",
        "quickbooks",
        "sheets",
        "gmail",
        "slack",
        "cobol_legacy_s3",
    }


def test_integration_registry_authorities() -> None:
    """Razorpay owns provider state read-only; legacy writes only via S3."""
    by_name = {entry.name: entry for entry in INTEGRATIONS}
    assert by_name["razorpay"].finsight_writes is False
    assert by_name["quickbooks"].finsight_writes is False
    assert by_name["sheets"].finsight_writes is False
    assert by_name["gmail"].finsight_writes is False
    assert by_name["cobol_legacy_s3"].finsight_writes is True
    assert by_name["razorpay"].owns_truth
    assert by_name["cobol_legacy_s3"].owns_truth


def test_compare_financial_states_fs231_breakdown() -> None:
    """The 4-way correlator decomposes FS-231 with residual exactly 10000."""
    expected = _load_fixture("fs_231_expected.json")
    razorpay = _load_fixture("fs_231_razorpay.json")
    qb = _load_fixture("fs_231_qb.json")
    legacy = _load_fixture("fs_231_legacy.json")
    comparison = compare_financial_states(
        expected=_decimal(expected["expected_total"]),
        razorpay_net=_decimal(razorpay["net"]),
        quickbooks=_decimal(qb["quickbooks_total"]),
        legacy=_decimal(legacy["accepted_total"]),
    )
    assert comparison.expected == Decimal("1000000")
    assert comparison.razorpay_net == Decimal("972500")
    assert comparison.quickbooks == Decimal("982500")
    assert comparison.legacy == Decimal("982500")
    assert comparison.expected_minus_razorpay == Decimal("27500")
    assert comparison.expected_minus_quickbooks == Decimal("17500")
    assert comparison.expected_minus_legacy == Decimal("17500")
    assert comparison.books_minus_provider == Decimal("10000")
    assert comparison.residual_variance == Decimal("10000")
    assert comparison.books_agree is True


def test_compare_financial_states_delegates_to_frozen_reconcile() -> None:
    """Pairwise legs go through frozen reconcile(): QB/legacy MATCHED, provider break."""
    comparison = compare_financial_states(
        expected=Decimal("1000000"),
        razorpay_net=Decimal("972500"),
        quickbooks=Decimal("982500"),
        legacy=Decimal("982500"),
    )
    assert (
        comparison.quickbooks_vs_legacy.outcome is ReconciliationOutcome.MATCHED
    )
    assert comparison.quickbooks_vs_legacy.variance == Decimal("0")
    assert (
        comparison.expected_vs_razorpay.outcome is ReconciliationOutcome.EXCEPTION
    )
    assert (
        comparison.expected_vs_razorpay.exception_code
        == ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG.value
    )
    assert comparison.expected_vs_quickbooks.variance == Decimal("17500")
