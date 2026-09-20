"""RED runtime contract: capability-gated, registry-bound, typed handoff."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agents.authority.claims import AgentCapability, AuthorityBoundary
from agents.authority.evidence import AuthorityError, EvidenceRecord, EvidenceRegistry
from agents.runtime import (
    AgentRuntime,
    RuntimeContext,
    RuntimeFactory,
    RuntimeHandoff,
    RuntimeRequest,
)

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
        accessible_ids={"ev-ledger-001", "ev-ledger-002"},
    )


def _context(registry: EvidenceRegistry | None = None) -> RuntimeContext:
    return RuntimeContext(
        situation_id="sit-001",
        company_id="meridian",
        now=NOW,
        registry=registry or _registry(),
        boundary=AuthorityBoundary(),
    )


class TestRuntimeContext:
    """Context must be registry-bound and company-scoped."""

    def test_context_requires_meridian(self) -> None:
        reg = _registry()
        with pytest.raises(AuthorityError):
            RuntimeContext(
                situation_id="sit-001",
                company_id="other",
                now=NOW,
                registry=reg,
                boundary=AuthorityBoundary(),
            )

    def test_context_requires_tz_aware_now(self) -> None:
        reg = _registry()
        with pytest.raises(AuthorityError):
            RuntimeContext(
                situation_id="sit-001",
                company_id="meridian",
                now=datetime(2026, 9, 1, 12, 0, 0),
                registry=reg,
                boundary=AuthorityBoundary(),
            )

    def test_context_requires_registry(self) -> None:
        with pytest.raises(AuthorityError):
            RuntimeContext(
                situation_id="sit-001",
                company_id="meridian",
                now=NOW,
                registry="not-a-registry",  # type: ignore[arg-type]
                boundary=AuthorityBoundary(),
            )


class TestRuntimeCapabilities:
    """Every capability dispatch must be gated through P7-01."""

    def test_read_via_registry(self) -> None:
        rt = AgentRuntime(_context())
        refs = rt.read(("ev-ledger-001",))
        assert len(refs) == 1
        assert refs[0].evidence_id == "ev-ledger-001"

    def test_correlate_via_registry(self) -> None:
        rt = AgentRuntime(_context())
        summary = rt.correlate(("ev-ledger-001", "ev-ledger-002"))
        assert "ev-ledger-001" in summary
        assert "ev-ledger-002" in summary

    def test_hypothesize_gated(self) -> None:
        rt = AgentRuntime(_context())
        hyp = rt.hypothesize(
            text="Dip may be seasonal.",
            evidence_ids=("ev-ledger-001",),
            uncertainty="Seasonality unconfirmed.",
        )
        assert hyp.uncertainty != ""

    def test_propose_returns_typed_handoff(self) -> None:
        rt = AgentRuntime(_context())
        handoff = rt.propose(
            proposal_type="advisory_note",
            evidence_ids=("ev-ledger-001",),
            uncertainty="Causation unconfirmed.",
            rationale="Overlap observed.",
        )
        assert isinstance(handoff, RuntimeHandoff)
        assert handoff.proposal.proposal_type == "advisory_note"
        assert handoff.situation_id == "sit-001"
        assert "status" not in handoff.to_dict()["proposal"]

    def test_explain_gated(self) -> None:
        rt = AgentRuntime(_context())
        handoff = rt.propose(
            proposal_type="explain_reasoning",
            evidence_ids=("ev-ledger-001",),
            uncertainty="U",
            rationale="R",
        )
        text = rt.explain(handoff)
        assert "advisory" in text.lower()

    def test_dispatch_generic_typed(self) -> None:
        rt = AgentRuntime(_context())
        result = rt.dispatch(
            AgentCapability.PROPOSE,
            {
                "proposal_type": "flag_ambiguity",
                "evidence_ids": ("ev-ledger-001",),
                "uncertainty": "U",
                "rationale": "R",
            },
        )
        assert isinstance(result, RuntimeHandoff)
        assert result.proposal.proposal_type == "flag_ambiguity"

    def test_proposal_type_not_capability_verb(self) -> None:
        rt = AgentRuntime(_context())
        with pytest.raises(AuthorityError):
            rt.propose(
                proposal_type="read",
                evidence_ids=("ev-ledger-001",),
                uncertainty="U",
                rationale="R",
            )


class TestRuntimeHandoffExplicit:
    """Handoff must be explicit and never carry authoritative status."""

    def test_handoff_is_not_authoritative_fact(self) -> None:
        rt = AgentRuntime(_context())
        handoff = rt.propose(
            proposal_type="advisory_note",
            evidence_ids=("ev-ledger-001",),
            uncertainty="U",
            rationale="R",
        )
        d = handoff.to_dict()
        assert d["tier"] == "handoff"
        assert "status" not in d["proposal"]
        assert "VERIFIED" not in str(d)

    def test_handoff_requires_meridian(self) -> None:
        rt = AgentRuntime(_context())
        handoff = rt.propose(
            proposal_type="advisory_note",
            evidence_ids=("ev-ledger-001",),
            uncertainty="U",
            rationale="R",
        )
        assert handoff.company_id == "meridian"

    def test_model_output_revalidated(self) -> None:
        """Fake model that smuggles status must be re-validated and rejected."""
        def smuggling_model(capability: AgentCapability, inputs: dict) -> dict:
            return {
                "proposal_type": "advisory_note",
                "evidence_ids": ("ev-ledger-001",),
                "uncertainty": "U",
                "rationale": "R",
                "status": "VERIFIED",
                "amount": 10000,
            }

        rt = AgentRuntime(_context(), model=smuggling_model)
        with pytest.raises(AuthorityError):
            rt.propose(
                proposal_type="advisory_note",
                evidence_ids=("ev-ledger-001",),
                uncertainty="U",
                rationale="R",
            )

    def test_runtime_validates_through_p7_01(self) -> None:
        """Proposals are validated via P7-01 — smuggled amount is refused."""
        rt = AgentRuntime(_context())
        # Directly test that validate_proposal_dict is the gate — runtime uses it.
        with pytest.raises(AuthorityError):
            rt.dispatch(
                AgentCapability.PROPOSE,
                {
                    "proposal_type": "advisory_note",
                    "evidence_ids": ("ev-ledger-001",),
                    "uncertainty": "U",
                    "rationale": "R",
                    "status": "VERIFIED",
                },
            )


class TestDeterministicPreservation:
    """Positive invariant: handoff remains bound to deterministic request."""

    def test_model_output_preserves_deterministic_context_and_scope(self) -> None:
        """Normal model output must preserve situation, company, capability, and scope."""
        factory = RuntimeFactory()
        reg = _registry()
        boundary = AuthorityBoundary()
        ctx = factory.create_context(
            situation_id="sit-preserve-001",
            now=NOW,
            registry=reg,
            boundary=boundary,
        )
        # Model contributes only advisory content, not context.
        def normal_model(capability: AgentCapability, inputs: dict) -> dict:
            return {
                "proposal_type": "advisory_note",
                "evidence_ids": ("ev-ledger-001",),
                "uncertainty": "Model uncertainty — still advisory.",
                "rationale": "Model rationale — based on deterministic evidence.",
            }

        rt = factory.create_runtime(ctx, model=normal_model)
        handoff = rt.propose(
            proposal_type="advisory_note",
            evidence_ids=("ev-ledger-001",),
            uncertainty="Original U",
            rationale="Original R",
        )
        # Deterministic request context wins.
        assert handoff.situation_id == "sit-preserve-001"
        assert handoff.company_id == "meridian"
        assert handoff.proposal.proposal_type == "advisory_note"
        assert tuple(r.evidence_id for r in handoff.proposal.evidence_refs) == (
            "ev-ledger-001",
        )
        # Model contributed content is present but context/scope unchanged.
        assert "Model rationale" in handoff.proposal.rationale

    def test_dispatch_request_preserves_typed_envelope(self) -> None:
        """Dispatch via RuntimeRequest preserves typed envelope."""
        factory = RuntimeFactory()
        reg = _registry()
        boundary = AuthorityBoundary()
        ctx = factory.create_context(
            situation_id="sit-req-001",
            now=NOW,
            registry=reg,
            boundary=boundary,
        )
        rt = factory.create_runtime(ctx)
        req = RuntimeRequest(
            capability=AgentCapability.PROPOSE,
            inputs={
                "proposal_type": "flag_ambiguity",
                "uncertainty": "U",
                "rationale": "R",
            },
            evidence_ids=("ev-ledger-001",),
        )
        result = rt.dispatch_request(req)
        assert isinstance(result, RuntimeHandoff)
        assert result.situation_id == "sit-req-001"
        assert result.proposal.proposal_type == "flag_ambiguity"
