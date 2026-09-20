"""RED P7-03 investigation contracts: EvidenceLookup / Correlation / Explanation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agents.authority.claims import AgentCapability, AuthorityBoundary
from agents.authority.evidence import AuthorityError, EvidenceRecord, EvidenceRegistry
from agents.runtime import RuntimeContext, RuntimeFactory

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


def _factory_context() -> RuntimeContext:
    factory = RuntimeFactory()
    return factory.create_context(
        situation_id="sit-p703-001",
        now=NOW,
        registry=_registry(),
        boundary=AuthorityBoundary(),
    )


class TestEvidenceLookupContract:
    """EvidenceLookup: typed request → typed result via registry."""

    def test_valid_lookup_returns_success_with_hmac_refs(self) -> None:
        from agents.tools.evidence_lookup import EvidenceLookupRequest, evidence_lookup

        ctx = _factory_context()
        req = EvidenceLookupRequest(
            capability=AgentCapability.READ,
            situation_id="sit-p703-001",
            company_id="meridian",
            now=NOW,
            evidence_ids=("ev-ledger-001",),
        )
        result = evidence_lookup(req, registry=ctx.registry, boundary=ctx.boundary)
        assert result.success is True
        assert result.evidence_refs is not None
        assert result.evidence_refs[0].evidence_id == "ev-ledger-001"
        assert result.failure is None
        assert result.provenance == "p6_evidence_store"

    def test_lookup_request_requires_typed_capability(self) -> None:
        from agents.tools.evidence_lookup import EvidenceLookupRequest

        with pytest.raises(AuthorityError):
            EvidenceLookupRequest(
                capability="read",  # type: ignore[arg-type]
                situation_id="sit-p703-001",
                company_id="meridian",
                now=NOW,
                evidence_ids=("ev-ledger-001",),
            )

    def test_lookup_rejects_blank_evidence_id(self) -> None:
        from agents.tools.evidence_lookup import EvidenceLookupRequest

        with pytest.raises(AuthorityError):
            EvidenceLookupRequest(
                capability=AgentCapability.READ,
                situation_id="sit-p703-001",
                company_id="meridian",
                now=NOW,
                evidence_ids=("",),
            )

    def test_lookup_returns_typed_failure_for_missing(self) -> None:
        from agents.tools.evidence_lookup import EvidenceLookupRequest, evidence_lookup

        ctx = _factory_context()
        req = EvidenceLookupRequest(
            capability=AgentCapability.READ,
            situation_id="sit-p703-001",
            company_id="meridian",
            now=NOW,
            evidence_ids=("ev-missing-999",),
        )
        result = evidence_lookup(req, registry=ctx.registry, boundary=ctx.boundary)
        assert result.success is False
        assert result.failure is not None
        assert result.failure.code == "MISSING_EVIDENCE"

    def test_lookup_freshness_enforced(self) -> None:
        from agents.tools.evidence_lookup import EvidenceLookupRequest, evidence_lookup

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
        ctx = RuntimeFactory().create_context(
            situation_id="sit-p703-001",
            now=NOW,
            registry=reg,
            boundary=AuthorityBoundary(),
        )
        req = EvidenceLookupRequest(
            capability=AgentCapability.READ,
            situation_id="sit-p703-001",
            company_id="meridian",
            now=NOW,
            evidence_ids=("ev-stale-001",),
        )
        result = evidence_lookup(req, registry=ctx.registry, boundary=ctx.boundary)
        assert result.success is False
        assert result.failure is not None
        assert result.failure.code == "STALE_EVIDENCE"


class TestCorrelationContract:
    """Correlation: evidence_ids → advisory correlation, registry-resolved."""

    def test_valid_correlation_returns_advisory_success(self) -> None:
        from agents.tools.correlation import CorrelationRequest, correlate

        ctx = _factory_context()
        req = CorrelationRequest(
            capability=AgentCapability.CORRELATE,
            situation_id="sit-p703-001",
            company_id="meridian",
            now=NOW,
            evidence_ids=("ev-ledger-001", "ev-ledger-002"),
        )
        result = correlate(req, registry=ctx.registry, boundary=ctx.boundary)
        assert result.success is True
        assert result.summary is not None
        assert "ev-ledger-001" in result.summary
        assert result.failure is None

    def test_correlation_requires_correlate_capability(self) -> None:
        from agents.tools.correlation import CorrelationRequest

        with pytest.raises(AuthorityError):
            CorrelationRequest(
                capability=AgentCapability.READ,  # wrong
                situation_id="sit-p703-001",
                company_id="meridian",
                now=NOW,
                evidence_ids=("ev-ledger-001",),
            )

    def test_correlation_inaccessible_returns_failure(self) -> None:
        from agents.tools.correlation import CorrelationRequest, correlate

        reg = _registry()
        # Make ev-002 inaccessible
        reg2 = EvidenceRegistry(
            {
                "ev-ledger-001": reg.get_record("ev-ledger-001"),
                "ev-ledger-002": reg.get_record("ev-ledger-002"),
            },
            accessible_ids={"ev-ledger-001"},
        )
        ctx = RuntimeFactory().create_context(
            situation_id="sit-p703-001",
            now=NOW,
            registry=reg2,
            boundary=AuthorityBoundary(),
        )
        req = CorrelationRequest(
            capability=AgentCapability.CORRELATE,
            situation_id="sit-p703-001",
            company_id="meridian",
            now=NOW,
            evidence_ids=("ev-ledger-002",),
        )
        result = correlate(req, registry=ctx.registry, boundary=ctx.boundary)
        assert result.success is False
        assert result.failure is not None
        assert result.failure.code == "INACCESSIBLE_EVIDENCE"

    def test_correlation_does_not_resolve_contradictory(self) -> None:
        """Contradictory evidence must remain flagged, not silently resolved."""
        from agents.tools.correlation import CorrelationRequest, correlate

        ctx = _factory_context()
        req = CorrelationRequest(
            capability=AgentCapability.CORRELATE,
            situation_id="sit-p703-001",
            company_id="meridian",
            now=NOW,
            evidence_ids=("ev-ledger-001", "ev-ledger-002"),
        )
        # The tool returns an advisory correlation, not a merged fact.
        result = correlate(req, registry=ctx.registry, boundary=ctx.boundary)
        assert result.success is True
        # Must not claim authoritative resolution.
        assert "VERIFIED" not in (result.summary or "")
        assert "FACT" not in (result.summary or "")


class TestExplanationContract:
    """Explanation: handoff → human-facing advisory explanation."""

    def test_valid_explanation_returns_advisory(self) -> None:
        from agents.tools.explanation import ExplanationRequest, explain

        factory = RuntimeFactory()
        reg = _registry()
        ctx = factory.create_context(
            situation_id="sit-p703-001",
            now=NOW,
            registry=reg,
            boundary=AuthorityBoundary(),
        )
        rt = factory.create_runtime(ctx)
        handoff = rt.propose(
            proposal_type="advisory_note",
            evidence_ids=("ev-ledger-001",),
            uncertainty="U",
            rationale="R",
        )
        req = ExplanationRequest(
            capability=AgentCapability.EXPLAIN,
            situation_id="sit-p703-001",
            company_id="meridian",
            now=NOW,
            handoff=handoff,
        )
        result = explain(req, boundary=ctx.boundary)
        assert result.success is True
        assert result.explanation is not None
        assert "advisory" in result.explanation.lower()

    def test_explanation_requires_explain_capability(self) -> None:
        from agents.tools.explanation import ExplanationRequest

        factory = RuntimeFactory()
        reg = _registry()
        ctx = factory.create_context(
            situation_id="sit-p703-001",
            now=NOW,
            registry=reg,
            boundary=AuthorityBoundary(),
        )
        rt = factory.create_runtime(ctx)
        handoff = rt.propose(
            proposal_type="advisory_note",
            evidence_ids=("ev-ledger-001",),
            uncertainty="U",
            rationale="R",
        )
        with pytest.raises(AuthorityError):
            ExplanationRequest(
                capability=AgentCapability.READ,  # wrong
                situation_id="sit-p703-001",
                company_id="meridian",
                now=NOW,
                handoff=handoff,
            )

    def test_explanation_rejects_wrong_situation_scope(self) -> None:
        from agents.tools.explanation import ExplanationRequest, explain

        factory = RuntimeFactory()
        reg = _registry()
        ctx = factory.create_context(
            situation_id="sit-p703-001",
            now=NOW,
            registry=reg,
            boundary=AuthorityBoundary(),
        )
        rt = factory.create_runtime(ctx)
        handoff = rt.propose(
            proposal_type="advisory_note",
            evidence_ids=("ev-ledger-001",),
            uncertainty="U",
            rationale="R",
        )
        req = ExplanationRequest(
            capability=AgentCapability.EXPLAIN,
            situation_id="sit-other-999",
            company_id="meridian",
            now=NOW,
            handoff=handoff,
        )
        result = explain(req, boundary=ctx.boundary)
        assert result.success is False
        assert result.failure is not None
        assert result.failure.code == "SCOPE_MISMATCH"
