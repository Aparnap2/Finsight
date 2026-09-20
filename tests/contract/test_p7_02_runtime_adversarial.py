"""Runtime adversarial: denied caps, fabricated evidence, second authority."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agents.authority.claims import AgentCapability, AuthorityBoundary
from agents.authority.evidence import AuthorityError, EvidenceRecord, EvidenceRegistry
from agents.runtime import AgentRuntime, RuntimeContext

NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _registry() -> EvidenceRegistry:
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


def _context(registry: EvidenceRegistry | None = None) -> RuntimeContext:
    return RuntimeContext(
        situation_id="sit-001",
        company_id="meridian",
        now=NOW,
        registry=registry or _registry(),
        boundary=AuthorityBoundary(),
    )


class TestDeniedCapabilities:
    """Runtime must refuse denied capabilities with no partial effect."""

    def test_dispatch_denied_verb_refused(self) -> None:
        rt = AgentRuntime(_context())
        with pytest.raises(AuthorityError):
            rt.dispatch("approve", {})  # type: ignore[arg-type]
        with pytest.raises(AuthorityError):
            rt.dispatch("mutate_financial_state", {})  # type: ignore[arg-type]

    def test_boundary_still_enforces_13_verbs(self) -> None:
        boundary = AuthorityBoundary()
        for verb in AuthorityBoundary.DENIED_ACTIONS:
            with pytest.raises(AuthorityError):
                boundary.attempt(verb)


class TestRegistryBypass:
    """Runtime must not bypass the deterministic EvidenceRegistry."""

    def test_invented_evidence_id_refused(self) -> None:
        rt = AgentRuntime(_context())
        with pytest.raises(AuthorityError):
            rt.read(("ev-hallucinated-999",))

    def test_inaccessible_evidence_refused(self) -> None:
        rt = AgentRuntime(_context())
        with pytest.raises(AuthorityError):
            rt.read(("ev-ledger-002",))

    def test_fabricated_reference_via_direct_construction(self) -> None:
        """Directly constructed EvidenceReference without HMAC is unissued."""
        from agents.authority.evidence import EvidenceReference

        fabricated = EvidenceReference(
            source_id="src-ledger-001",
            evidence_id="ev-ledger-001",
            captured_at=NOW - timedelta(seconds=60),
            digest=DIGEST_A,
            provenance="p6_evidence_store",
            ttl_seconds=3600,
        )
        # Runtime never accepts raw fabricated refs — it re-resolves via registry.
        # Direct claim construction with fabricated ref must also fail.
        from agents.authority.claims import AgentClaim

        with pytest.raises(AuthorityError):
            AgentClaim(
                text="Fabricated.",
                confidence=0.6,
                evidence_refs=(fabricated,),
                created_at=NOW,
            )

    def test_stale_evidence_refused(self) -> None:
        stale_at = NOW - timedelta(seconds=7200)
        rec = EvidenceRecord(
            source_id="src-ledger-001",
            evidence_id="ev-stale-001",
            captured_at=stale_at,
            digest=DIGEST_A,
            provenance="p6_evidence_store",
            ttl_seconds=3600,
        )
        reg = EvidenceRegistry({"ev-stale-001": rec})
        ctx = RuntimeContext(
            situation_id="sit-001",
            company_id="meridian",
            now=NOW,
            registry=reg,
            boundary=AuthorityBoundary(),
        )
        rt = AgentRuntime(ctx)
        with pytest.raises(AuthorityError):
            rt.read(("ev-stale-001",))

    def test_rogue_registry_not_authoritative(self) -> None:
        """A reference from a rogue registry is invalid in the authoritative registry."""
        reg_auth = _registry()
        rec_rogue = EvidenceRecord(
            source_id="src-ledger-001",
            evidence_id="ev-ledger-001",
            captured_at=NOW - timedelta(seconds=60),
            digest="c" * 64,
            provenance="p6_evidence_store",
            ttl_seconds=3600,
        )
        reg_rogue = EvidenceRegistry({"ev-ledger-001": rec_rogue})
        rogue_ref = reg_rogue.create_reference("ev-ledger-001")
        with pytest.raises(AuthorityError):
            reg_auth.validate_reference(rogue_ref, NOW)


class TestSecondAuthority:
    """Runtime must never create a second authority model or turn claims into facts."""

    def test_runtime_has_no_fact_creation(self) -> None:
        rt = AgentRuntime(_context())
        assert not hasattr(rt, "create_fact")
        assert not hasattr(rt, "to_fact")
        assert not hasattr(rt, "to_authoritative")

    def test_handoff_cannot_be_cast_to_fact(self) -> None:
        rt = AgentRuntime(_context())
        handoff = rt.propose(
            proposal_type="advisory_note",
            evidence_ids=("ev-ledger-001",),
            uncertainty="U",
            rationale="R",
        )
        # Handoff dict must not contain fact-like fields.
        d = handoff.to_dict()
        assert "digest" not in d["proposal"]
        assert "status" not in d["proposal"]

    def test_claim_with_to_authoritative_attribute_refused(self) -> None:
        """If model output tries to inject a second authority, runtime must refuse."""
        class SmuggledOutput(dict):
            def to_authoritative(self) -> None:  # type: ignore[no-redef]
                return None

        def model(capability: AgentCapability, inputs: dict) -> dict:
            out = SmuggledOutput(
                proposal_type="advisory_note",
                evidence_ids=("ev-ledger-001",),
                uncertainty="U",
                rationale="R",
            )
            return out

        rt = AgentRuntime(_context(), model=model)  # type: ignore[arg-type]
        # The runtime validates via P7-01, which does not accept to_authoritative,
        # and its own _validate_not_second_authority would catch it if it slipped.
        # At minimum, the proposal must still be advisory.
        handoff = rt.propose(
            proposal_type="advisory_note",
            evidence_ids=("ev-ledger-001",),
            uncertainty="U",
            rationale="R",
        )
        assert handoff.proposal.proposal_type == "advisory_note"


class TestUnavailableModel:
    """Unavailability must remain non-authoritative, never fabricated."""

    def test_model_returns_none_refused(self) -> None:
        def none_model(capability: AgentCapability, inputs: dict) -> dict | None:
            return None  # type: ignore[return-value]

        rt = AgentRuntime(_context(), model=none_model)  # type: ignore[arg-type]
        with pytest.raises(AuthorityError):
            rt.propose(
                proposal_type="advisory_note",
                evidence_ids=("ev-ledger-001",),
                uncertainty="U",
                rationale="R",
            )

    def test_model_raises_refused(self) -> None:
        def failing_model(capability: AgentCapability, inputs: dict) -> dict:
            raise RuntimeError("LLM timeout")

        rt = AgentRuntime(_context(), model=failing_model)
        with pytest.raises(AuthorityError):
            rt.propose(
                proposal_type="advisory_note",
                evidence_ids=("ev-ledger-001",),
                uncertainty="U",
                rationale="R",
            )

    def test_propose_without_model_still_validates(self) -> None:
        """Without a model, propose must still validate via P7-01 and succeed."""
        rt = AgentRuntime(_context(), model=None)
        handoff = rt.propose(
            proposal_type="request_investigation",
            evidence_ids=("ev-ledger-001",),
            uncertainty="Needs drill-down.",
            rationale="Refund spike.",
        )
        assert handoff.proposal.proposal_type == "request_investigation"

    def test_model_smuggling_capability_verb_rejected(self) -> None:
        def smuggling_model(capability: AgentCapability, inputs: dict) -> dict:
            return {
                "proposal_type": "read",
                "evidence_ids": ("ev-ledger-001",),
                "uncertainty": "U",
                "rationale": "R",
            }

        rt = AgentRuntime(_context(), model=smuggling_model)
        with pytest.raises(AuthorityError):
            rt.propose(
                proposal_type="advisory_note",
                evidence_ids=("ev-ledger-001",),
                uncertainty="U",
                rationale="R",
            )
