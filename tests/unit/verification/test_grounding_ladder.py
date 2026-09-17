"""P5-04 grounding ladder tests: HYPOTHESIS != FACT != VERIFIED + provenance.

Covers :func:`finance.evidence.grounding` ladder and its wiring into
:class:`agents.verification.verifier.Verifier` stage 3:

- Positive: cited tenant-owned hash-valid tz-aware supported item passes
  the full ladder (eligible for VERIFIED, verifier ACCEPTED with registry).
- Negative: high confidence (0.99) without citation still REJECTED;
  cross-tenant registry entry surfaces uniform unknown_evidence_id (no leak);
  hash mismatch / naive retrieved_at / missing provenance surface
  provenance_invalid.
- Adversarial: LLM fabricates FACT wording without evidence, or stamps a
  VERIFIED marker — rejected via grounding + claim-classification gates.
- Ladder: HYPOTHESIS != FACT != VERIFIED tier assertions; confidence never
  promotes a tier (confidence != authority).
- Immutability: EvidenceItem frozen, registry loop never mutates items.

Style: Arrange-Act-Assert, typed, deterministic, no network or LLM.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from agents.investigation.plan import InvestigationPlan
from agents.verification.verifier import Verifier
from finance.evidence.grounding import (
    ClaimTier,
    classify_tier,
    compute_content_hash,
    evaluate_ladder,
    is_tz_aware,
    is_verified_eligible,
    verify_provenance,
)
from finance.evidence.models import EvidenceItem, EvidenceProvenance

_TENANT = "meridian"
_OTHER_TENANT = "tenant-b"
_HYPOTHESIS = "Possible refund posting lag between processor and ledger records."


def _bytes_for(source_id: str) -> bytes:
    """Deterministic raw bytes for one evidence id (hash source of truth)."""
    return f"raw-bytes-for:{source_id}".encode()


def _hash_for(source_id: str) -> str:
    """SHA-256 hex of the canonical raw bytes for one evidence id."""
    return hashlib.sha256(_bytes_for(source_id)).hexdigest()


def _provenance(correlation: str = "corr-001") -> EvidenceProvenance:
    """Valid provenance triple (adapter, endpoint, correlation_id)."""
    return EvidenceProvenance(
        adapter="stripe-adapter",
        endpoint="GET /v1/payments/pay_123",
        correlation_id=correlation,
    )


def _item(
    source_id: str = "ev-ledger-001",
    tenant_id: str | None = _TENANT,
    claim: str = "Ledger shows settlement batch total 100.00.",
    correlation: str = "corr-001",
) -> EvidenceItem:
    """Build a fully provenance-valid EvidenceItem for ``source_id``."""
    return EvidenceItem(
        claim=claim,
        source_type="ledger",
        source_id=source_id,
        source_value=Decimal("100.00"),
        confidence="high",
        tenant_id=tenant_id,
        content_hash=_hash_for(source_id),
        retrieved_at=datetime.now(UTC),
        provenance=_provenance(correlation),
    )


def _plan(
    hypothesis: str = _HYPOTHESIS,
    evidence: tuple[str, ...] = ("ev-ledger-001",),
) -> InvestigationPlan:
    """Build a schema-valid candidate plan through strict validation."""
    return InvestigationPlan.model_validate(
        {
            "hypothesis_text": hypothesis,
            "capability_calls": [
                {
                    "capability": "get_stripe_payment",
                    "args": {"payment_id": "pay_123"},
                    "order_index": 0,
                },
            ],
            "evidence_required": list(evidence),
            "escalation": False,
        }
    )


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block real sockets so every test stays deterministic and offline."""

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("live network is forbidden in grounding tests")

    monkeypatch.setattr("socket.socket", _explode)


# ===========================================================================
# Helpers: hash + tz-awareness
# ===========================================================================


class TestGroundingHelpers:
    """Verify the pure helper contracts (hash, tz-awareness)."""

    def test_compute_content_hash_matches_sha256(self) -> None:
        """compute_content_hash equals hashlib.sha256 hex."""
        data = b"hello meridian"
        assert compute_content_hash(data) == hashlib.sha256(data).hexdigest()

    def test_is_tz_aware_accepts_utc(self) -> None:
        """UTC-aware datetimes pass."""
        assert is_tz_aware(datetime.now(UTC)) is True

    def test_is_tz_aware_rejects_naive(self) -> None:
        """Naive datetimes fail."""
        assert is_tz_aware(datetime.now()) is False


# ===========================================================================
# Positive: full ladder passes → VERIFIED eligible
# ===========================================================================


class TestLadderPositive:
    """A cited tenant-owned hash-valid tz-aware supported item passes."""

    def test_verify_provenance_clean_item_no_violations(self) -> None:
        """A fully valid item yields zero provenance violations."""
        item = _item()
        reasons = verify_provenance(
            item,
            expected_tenant=_TENANT,
            expected_bytes=_bytes_for("ev-ledger-001"),
        )
        assert reasons == ()

    def test_evaluate_ladder_clean_registry_no_violations(self) -> None:
        """Full ladder passes for a cited tenant-owned supported item."""
        registry = {"ev-ledger-001": _item()}
        reasons = evaluate_ladder(
            evidence_ids=("ev-ledger-001",),
            evidence_registry=registry,
            expected_tenant=_TENANT,
            content_bytes={"ev-ledger-001": _bytes_for("ev-ledger-001")},
        )
        assert reasons == ()

    def test_is_verified_eligible_true_for_clean_citation(self) -> None:
        """Clean citation is eligible for VERIFIED."""
        registry = {"ev-ledger-001": _item()}
        assert (
            is_verified_eligible(
                evidence_ids=("ev-ledger-001",),
                evidence_registry=registry,
                expected_tenant=_TENANT,
                content_bytes={"ev-ledger-001": _bytes_for("ev-ledger-001")},
            )
            is True
        )

    def test_classify_tier_verified_for_clean_citation(self) -> None:
        """Clean citation classifies as VERIFIED."""
        registry = {"ev-ledger-001": _item()}
        assert (
            classify_tier(
                evidence_ids=("ev-ledger-001",),
                evidence_registry=registry,
                expected_tenant=_TENANT,
                content_bytes={"ev-ledger-001": _bytes_for("ev-ledger-001")},
            )
            == ClaimTier.VERIFIED
        )

    def test_verifier_accepts_with_clean_registry(self) -> None:
        """Verifier ACCEPTS a cited plan when the registry passes the ladder."""
        plan = _plan()
        registry = {"ev-ledger-001": _item()}
        verdict = Verifier().verify(
            plan,
            {"ev-ledger-001"},
            evidence_registry=registry,  # type: ignore[arg-type]
            tenant_id=_TENANT,
            content_bytes={"ev-ledger-001": _bytes_for("ev-ledger-001")},
        )
        assert verdict.status == "ACCEPTED"
        assert verdict.reasons == ()


# ===========================================================================
# Negative: confidence != authority, cross-tenant uniform, provenance_invalid
# ===========================================================================


class TestLadderNegative:
    """Confidence never proves truth; failures map to uniform codes."""

    def test_high_confidence_without_citation_rejected(self) -> None:
        """confidence 0.99 without citation still REJECTED_REPLAN."""
        plan = _plan(
            hypothesis="Refund of 100.00 confirmed with confidence 0.99.",
            evidence=("ev-missing-999",),
        )
        verdict = Verifier().verify(plan, {"ev-ledger-001"})
        assert verdict.status == "REJECTED_REPLAN"
        assert any("unknown_evidence_id" in r for r in verdict.reasons)

    def test_cross_tenant_registry_entry_uniform_unknown(self) -> None:
        """Cross-tenant item surfaces as unknown_evidence_id (no leak)."""
        registry = {"ev-other-001": _item("ev-other-001", tenant_id=_OTHER_TENANT)}
        reasons = evaluate_ladder(
            evidence_ids=("ev-other-001",),
            evidence_registry=registry,
            expected_tenant=_TENANT,
        )
        assert reasons == ("grounding_violation:unknown_evidence_id:ev-other-001",)

    def test_cross_tenant_missing_indistinguishable(self) -> None:
        """Genuinely missing id yields the identical code as cross-tenant."""
        registry = {"ev-other-001": _item("ev-other-001", tenant_id=_OTHER_TENANT)}
        cross = evaluate_ladder(
            evidence_ids=("ev-other-001",),
            evidence_registry=registry,
            expected_tenant=_TENANT,
        )
        missing = evaluate_ladder(
            evidence_ids=("ev-ghost-404",),
            evidence_registry={},
            expected_tenant=_TENANT,
        )
        assert cross[0].split(":")[:2] == missing[0].split(":")[:2]
        assert "unknown_evidence_id" in cross[0]
        assert "unknown_evidence_id" in missing[0]

    def test_hash_mismatch_provenance_invalid(self) -> None:
        """Wrong content_hash surfaces provenance_invalid."""
        bad = EvidenceItem.model_validate(
            {
                **_item().model_dump(mode="python"),
                "content_hash": "0" * 64,
            }
        )
        registry = {"ev-ledger-001": bad}
        reasons = evaluate_ladder(
            evidence_ids=("ev-ledger-001",),
            evidence_registry=registry,
            expected_tenant=_TENANT,
            content_bytes={"ev-ledger-001": _bytes_for("ev-ledger-001")},
        )
        assert reasons == ("grounding_violation:provenance_invalid:ev-ledger-001",)

    def test_naive_retrieved_at_provenance_invalid(self) -> None:
        """Naive retrieved_at surfaces provenance_invalid."""
        valid = _item()
        naive = valid.model_copy(update={"retrieved_at": datetime.now()})
        # model_copy bypasses validation by design; confirm the test premise
        assert naive.retrieved_at is not None and not is_tz_aware(naive.retrieved_at)
        reasons = verify_provenance(naive, expected_tenant=_TENANT)
        assert any("retrieved_at" in code for code in reasons)

    def test_missing_provenance_provenance_invalid(self) -> None:
        """Missing provenance surfaces provenance_invalid."""
        no_prov = EvidenceItem.model_validate(
            {
                "claim": "Ledger total 100.00.",
                "source_type": "ledger",
                "source_id": "ev-ledger-001",
                "source_value": Decimal("100.00"),
                "tenant_id": _TENANT,
                "content_hash": _hash_for("ev-ledger-001"),
                "retrieved_at": datetime.now(UTC),
            }
        )
        reasons = verify_provenance(no_prov, expected_tenant=_TENANT)
        assert any("provenance_missing" in code for code in reasons)

    def test_verifier_rejects_hash_mismatch_with_registry(self) -> None:
        """Verifier REJECTS when the registry hash does not match bytes."""
        plan = _plan()
        bad = EvidenceItem.model_validate(
            {
                **_item().model_dump(mode="python"),
                "content_hash": "0" * 64,
            }
        )
        verdict = Verifier().verify(
            plan,
            {"ev-ledger-001"},
            evidence_registry={"ev-ledger-001": bad},  # type: ignore[dict-item]
            tenant_id=_TENANT,
            content_bytes={"ev-ledger-001": _bytes_for("ev-ledger-001")},
        )
        assert verdict.status == "REJECTED_REPLAN"
        assert any("provenance_invalid" in r for r in verdict.reasons)


# ===========================================================================
# Adversarial: fabricated FACT / VERIFIED stamps rejected
# ===========================================================================


class TestLadderAdversarial:
    """LLM fabrications never pass the deterministic gate."""

    def test_fabricated_fact_without_evidence_rejected(self) -> None:
        """FACT wording ('refund 100.00 is factual') without citation rejects."""
        plan = _plan(
            hypothesis="FACT: refund 100.00 posted to ledger account 4812.",
            evidence=("ev-ghost-001",),
        )
        verdict = Verifier().verify(plan, {"ev-ledger-001"})
        assert verdict.status == "REJECTED_REPLAN"
        assert any("unknown_evidence_id" in r for r in verdict.reasons)

    def test_verified_marker_rejected_even_with_citation(self) -> None:
        """A VERIFIED stamp is rejected even when evidence is cited."""
        plan = _plan(hypothesis="Refund hypothesis verified by ledger review.")
        registry = {"ev-ledger-001": _item()}
        verdict = Verifier().verify(
            plan,
            {"ev-ledger-001"},
            evidence_registry=registry,  # type: ignore[arg-type]
            tenant_id=_TENANT,
            content_bytes={"ev-ledger-001": _bytes_for("ev-ledger-001")},
        )
        assert verdict.status == "REJECTED_REPLAN"
        assert any("declare_verified" in r for r in verdict.reasons)

    def test_blank_claim_never_supported(self) -> None:
        """A blank claim can never be supported (unsupported_claim)."""
        blank = EvidenceItem.model_construct(
            claim="",
            source_type="ledger",
            source_id="ev-blank-001",
            source_value=Decimal("0"),
            tenant_id=_TENANT,
            content_hash=_hash_for("ev-blank-001"),
            retrieved_at=datetime.now(UTC),
            provenance=_provenance(),
        )
        reasons = evaluate_ladder(
            evidence_ids=("ev-blank-001",),
            evidence_registry={"ev-blank-001": blank},
            expected_tenant=_TENANT,
            content_bytes={"ev-blank-001": _bytes_for("ev-blank-001")},
        )
        assert any("unsupported_claim" in code for code in reasons)


# ===========================================================================
# Ladder tiers: HYPOTHESIS != FACT != VERIFIED; confidence != authority
# ===========================================================================


class TestLadderTiers:
    """Tier ordering is strict and independent of confidence."""

    def test_no_citation_is_hypothesis(self) -> None:
        """Empty evidence set classifies as HYPOTHESIS."""
        assert (
            classify_tier(
                evidence_ids=(),
                evidence_registry={},
                expected_tenant=_TENANT,
            )
            == ClaimTier.HYPOTHESIS
        )

    def test_missing_registry_is_hypothesis(self) -> None:
        """No registry (existence-only mode) classifies as HYPOTHESIS."""
        assert (
            classify_tier(
                evidence_ids=("ev-ledger-001",),
                evidence_registry=None,
                expected_tenant=_TENANT,
            )
            == ClaimTier.HYPOTHESIS
        )

    def test_exists_but_provenance_pending_is_fact(self) -> None:
        """Tenant-owned but hash-pending citation classifies as FACT."""
        no_hash = EvidenceItem.model_validate(
            {
                "claim": "Ledger total 100.00.",
                "source_type": "ledger",
                "source_id": "ev-ledger-001",
                "source_value": Decimal("100.00"),
                "tenant_id": _TENANT,
            }
        )
        tier = classify_tier(
            evidence_ids=("ev-ledger-001",),
            evidence_registry={"ev-ledger-001": no_hash},
            expected_tenant=_TENANT,
        )
        assert tier == ClaimTier.FACT

    def test_tiers_are_distinct_ordered_values(self) -> None:
        """HYPOTHESIS, FACT, VERIFIED are three distinct tier values."""
        assert len({ClaimTier.HYPOTHESIS, ClaimTier.FACT, ClaimTier.VERIFIED}) == 3
        assert ClaimTier.HYPOTHESIS != ClaimTier.FACT != ClaimTier.VERIFIED

    def test_confidence_never_promotes_tier(self) -> None:
        """confidence='critical' without ladder pass stays below VERIFIED."""
        item = _item()
        tier = classify_tier(
            evidence_ids=("ev-ledger-001",),
            evidence_registry={"ev-ledger-001": item},
            expected_tenant=_TENANT,
            content_bytes={"ev-ledger-001": b"wrong-bytes"},
        )
        assert tier != ClaimTier.VERIFIED


# ===========================================================================
# Immutability: frozen items, registry never mutated
# ===========================================================================


class TestLadderImmutability:
    """Evidence items are frozen; evaluation never mutates the registry."""

    def test_evidence_item_frozen(self) -> None:
        """EvidenceItem rejects attribute assignment (frozen model)."""
        item = _item()
        with pytest.raises(ValueError):
            item.claim = "mutated"  # type: ignore[misc]

    def test_evaluate_ladder_does_not_mutate_registry(self) -> None:
        """evaluate_ladder leaves registry items identical (hash-stable)."""
        item = _item()
        registry = {"ev-ledger-001": item}
        before = item.model_dump(mode="json")
        evaluate_ladder(
            evidence_ids=("ev-ledger-001",),
            evidence_registry=registry,
            expected_tenant=_TENANT,
            content_bytes={"ev-ledger-001": _bytes_for("ev-ledger-001")},
        )
        assert registry["ev-ledger-001"].model_dump(mode="json") == before
        assert registry["ev-ledger-001"] is item
