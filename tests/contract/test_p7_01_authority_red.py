"""RED contract: forbidden authorities must fail; capabilities must stay advisory."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agents.authority.claims import (
    AgentCapability,
    AgentClaim,
    AgentHypothesis,
    AgentObservation,
    AgentProposal,
    AuthorityBoundary,
    correlate_evidence,
    detect_ambiguity,
    explain_proposal,
    find_missing_info,
    reason_over_evidence,
)
from agents.authority.evidence import (
    AuthoritativeFact,
    AuthorityError,
    EvidenceRecord,
    EvidenceReference,
    EvidenceRegistry,
)

NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
"""Caller-supplied frozen clock; no wall-clock reads in tests."""

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _registry() -> EvidenceRegistry:
    """Deterministic accessor with two records; only ev-001 is accessible."""
    rec_a = EvidenceRecord(
        source_id="src-ledger-001",
        evidence_id="ev-ledger-001",
        captured_at=NOW - timedelta(seconds=60),
        digest=DIGEST_A,
        provenance="p6_evidence_store",
        ttl_seconds=3600,
    )
    rec_b = EvidenceRecord(
        source_id="src-ledger-002",
        evidence_id="ev-ledger-002",
        captured_at=NOW - timedelta(seconds=60),
        digest=DIGEST_B,
        provenance="p6_evidence_store",
        ttl_seconds=3600,
    )
    return EvidenceRegistry(
        {"ev-ledger-001": rec_a, "ev-ledger-002": rec_b},
        accessible_ids={"ev-ledger-001"},
    )


def _fresh_ref(registry: EvidenceRegistry | None = None) -> EvidenceReference:
    """Build a fresh, HMAC-bound evidence pointer valid at NOW."""
    reg = registry or _registry()
    return reg.create_reference("ev-ledger-001")


def _claim(registry: EvidenceRegistry | None = None) -> AgentClaim:
    """Build a minimal valid advisory claim for positive-path tests."""
    reg = registry or _registry()
    return AgentClaim(
        text="Revenue dip correlates with refund spike.",
        confidence=0.6,
        evidence_refs=(_fresh_ref(reg),),
        created_at=NOW,
    )


def _proposal(registry: EvidenceRegistry | None = None) -> AgentProposal:
    """Build a minimal valid advisory proposal for positive-path tests."""
    reg = registry or _registry()
    return AgentProposal(
        proposal_type="advisory_note",
        evidence_refs=(_fresh_ref(reg),),
        uncertainty="Refund causation unconfirmed; needs ledger drill-down.",
        rationale="Refund spike overlaps the dip window.",
        created_at=NOW,
    )


FORBIDDEN_ACTIONS = [
    "mutate_financial_state",
    "execute_financial_correction",
    "approve",
    "reject_authorize",
    "establish_verdict",
    "declare_verification_successful",
    "close_case",
    "modify_authoritative_evidence",
    "fabricate_missing_evidence",
    "convert_unsupported_claim_into_fact",
    "use_stale_evidence_as_current",
    "bypass_deterministic_policy",
    "bypass_p6_verification",
]
"""The 13 denied verbs; boundary must refuse each with no side effects."""


class TestForbiddenAuthority:
    """Each forbidden verb must raise AuthorityError with zero partial effect."""

    @pytest.mark.parametrize("action", FORBIDDEN_ACTIONS)  # type: ignore[untyped-decorator]
    def test_denied_verb_raises_without_side_effect(self, action: str) -> None:
        """Arrange a boundary; Act attempt forbidden verb; Assert refuse, no effect."""
        boundary = AuthorityBoundary()
        before = boundary.audit_log()
        with pytest.raises(AuthorityError):
            boundary.attempt(action)
        assert boundary.audit_log() == before

    def test_deny_list_covers_all_thirteen_verbs(self) -> None:
        """The deny-list must contain exactly the 13 forbidden verbs."""
        assert len(AuthorityBoundary.DENIED_ACTIONS) == 13
        assert set(FORBIDDEN_ACTIONS) == set(AuthorityBoundary.DENIED_ACTIONS)

    def test_capability_verbs_are_not_proposal_intents(self) -> None:
        """A proposal whose type is a capability verb must be refused."""
        reg = _registry()
        with pytest.raises(AuthorityError):
            AgentProposal(
                proposal_type="read",
                evidence_refs=(_fresh_ref(reg),),
                uncertainty="x",
                rationale="y",
                created_at=NOW,
            )
        with pytest.raises(AuthorityError):
            AgentProposal(
                proposal_type="propose",
                evidence_refs=(_fresh_ref(reg),),
                uncertainty="x",
                rationale="y",
                created_at=NOW,
            )

    def test_claim_cannot_convert_to_authoritative_fact(self) -> None:
        """A claim must never expose a promotion path into an AuthoritativeFact."""
        claim = _claim()
        assert not hasattr(claim, "to_authoritative")
        assert not hasattr(claim, "to_fact")
        assert not hasattr(AgentClaim, "to_authoritative")

    def test_proposal_has_no_authoritative_escape(self) -> None:
        """AgentProposal must not carry any to_authoritative-style escape."""
        proposal = _proposal()
        assert not hasattr(proposal, "to_authoritative")
        assert not hasattr(proposal, "to_fact")
        assert not hasattr(proposal, "to_decision")
        assert not hasattr(AgentProposal, "to_authoritative")

    def test_smuggled_verified_payload_stays_claim_not_fact(self) -> None:
        """A VERIFIED-shaped payload through a proposal must remain a claim."""
        proposal = _proposal()
        assert isinstance(proposal, AgentProposal)
        assert not isinstance(proposal, AuthoritativeFact)
        assert "status" not in proposal.to_dict()
        assert "VERIFIED" not in str(proposal.to_dict())

    def test_capability_and_proposal_namespaces_are_disjoint(self) -> None:
        """Capability verbs and advisory intents must be disjoint sets."""
        caps = {c.value for c in AgentCapability}
        # Advisory intents are the only valid proposal_type values.
        from agents.authority.claims import _ADVISORY_PROPOSAL_TYPES

        assert caps.isdisjoint(_ADVISORY_PROPOSAL_TYPES)


class TestPositiveCapabilities:
    """Advisory capabilities must succeed without granting authority."""

    def test_read_authorized_case_evidence(self) -> None:
        """Fresh evidence pointers satisfy the freshness guard via registry."""
        reg = _registry()
        ref = _fresh_ref(reg)
        reg.validate_reference(ref, NOW)
        assert not ref.is_stale(NOW)

    def test_correlate_evidence(self) -> None:
        """Correlating two refs returns an advisory summary, never a decision."""
        # Need two accessible refs — use a registry where both are accessible.
        rec_a = EvidenceRecord(
            source_id="src-a",
            evidence_id="ev-a",
            captured_at=NOW - timedelta(seconds=60),
            digest=DIGEST_A,
            provenance="p6_evidence_store",
            ttl_seconds=3600,
        )
        rec_b = EvidenceRecord(
            source_id="src-b",
            evidence_id="ev-b",
            captured_at=NOW - timedelta(seconds=60),
            digest=DIGEST_B,
            provenance="p6_evidence_store",
            ttl_seconds=3600,
        )
        reg2 = EvidenceRegistry({"ev-a": rec_a, "ev-b": rec_b})
        refs = (reg2.create_reference("ev-a"), reg2.create_reference("ev-b"))
        summary = correlate_evidence(refs, now=NOW)
        assert "ev-a" in summary and "ev-b" in summary
        assert "VERIFIED" not in summary

    def test_identify_ambiguity(self) -> None:
        """Conflicting values are flagged as ambiguous, not resolved by fiat."""
        outcome = detect_ambiguity({"revenue": ["100", "120"]})
        assert outcome.is_ambiguous is True

    def test_form_hypothesis(self) -> None:
        """A hypothesis over evidence refs constructs successfully."""
        reg = _registry()
        hyp = AgentHypothesis(
            text="Dip may be seasonal.",
            evidence_refs=(_fresh_ref(reg),),
            uncertainty="Seasonality unconfirmed.",
            created_at=NOW,
        )
        assert hyp.uncertainty != ""

    def test_reason_over_evidence(self) -> None:
        """Reasoning returns an explanation string carrying uncertainty."""
        text = reason_over_evidence(_claim())
        assert "uncertain" in text.lower() or "hypothesis" in text.lower()

    def test_request_further_investigation(self) -> None:
        """Requesting investigation is an allowed advisory proposal."""
        boundary = AuthorityBoundary()
        boundary.attempt(AgentCapability.PROPOSE.value)
        reg = _registry()
        proposal = AgentProposal(
            proposal_type="request_investigation",
            evidence_refs=(_fresh_ref(reg),),
            uncertainty="Ledger detail missing.",
            rationale="Request ledger drill-down.",
            created_at=NOW,
        )
        assert "drill-down" in proposal.rationale

    def test_identify_missing_info(self) -> None:
        """Missing required sources are reported, never fabricated."""
        missing = find_missing_info(
            present_ids=("ev-a",),
            required_ids=("ev-a", "ev-b"),
        )
        assert missing == ("ev-b",)

    def test_structured_proposal_with_evidence_refs(self) -> None:
        """A proposal carries typed intent, refs, and uncertainty — no status."""
        proposal = _proposal()
        assert proposal.proposal_type == "advisory_note"
        assert len(proposal.evidence_refs) == 1
        assert proposal.uncertainty != ""
        assert "status" not in proposal.to_dict()

    def test_state_uncertainty(self) -> None:
        """Stating uncertainty preserves the advisory tier of a claim."""
        claim = _claim()
        assert 0.0 < claim.confidence < 1.0
        assert claim.tier == "claim"

    def test_human_facing_explanation(self) -> None:
        """Explanations surface uncertainty without authoritative language."""
        text = explain_proposal(_proposal())
        assert "uncertain" in text.lower() or "proposal" in text.lower()
        assert "VERIFIED" not in text

    def test_observation_is_not_fact(self) -> None:
        """An observation over evidence refs is advisory, never authoritative."""
        reg = _registry()
        obs = AgentObservation(
            text="Refund spike observed.",
            evidence_refs=(_fresh_ref(reg),),
            observed_at=NOW,
        )
        assert not isinstance(obs, AuthoritativeFact)
        assert obs.tier == "observation"

    def test_capability_attempt_succeeds_for_allowed(self) -> None:
        """Each advisory capability must be grantable via the boundary."""
        boundary = AuthorityBoundary()
        for cap in AgentCapability:
            boundary.attempt_capability(cap)
        assert len(boundary.audit_log()) == len(AgentCapability)
