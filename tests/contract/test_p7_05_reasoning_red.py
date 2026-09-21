"""RED P7-05 resolution reasoning — Gates A-I advisory invariants (no GREEN yet).

Gate 1 is RED-only: these tests specify the contract and must FAIL until the
minimal reasoning boundary is implemented. Frozen P7-01..P7-04 must remain GREEN.

Business-auditor lens: can the system represent and control the business
situation without losing, prematurely closing, misrepresenting, or bypassing it?
Reasoning must not masquerade as financial verdict.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from agents.authority.claims import AgentCapability, AuthorityBoundary
from agents.authority.evidence import AuthorityError, EvidenceRecord, EvidenceRegistry
from agents.discovery import DiscoveryRequest, DiscoveryResult
from agents.runtime import RuntimeFactory

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


def _context():
    factory = RuntimeFactory()
    return factory.create_context(
        situation_id="sit-p705-001",
        now=NOW,
        registry=_registry(),
        boundary=AuthorityBoundary(),
    )


def _valid_discovery() -> DiscoveryResult:
    ctx = _context()
    req = DiscoveryRequest(
        situation_id="sit-p705-001",
        company_id="meridian",
        now=NOW,
        allowed_evidence_ids=("ev-ledger-001",),
        objective="Investigate refund spike correlation.",
        allowed_capabilities=(AgentCapability.READ,),
    )
    from agents.discovery.engine import discover

    return discover(req, context=ctx)


# ---------------------------------------------------------------------------
# Gate A — Input authority: only valid bounded DiscoveryResult
# ---------------------------------------------------------------------------


class TestAValidInputRepresented:
    def test_a1_valid_bounded_discovery_can_be_reasoned(self) -> None:
        from agents.reasoning.resolution import reason  # type: ignore[import-not-found]

        disc = _valid_discovery()
        ctx = _context()
        result = reason(disc, context=ctx)
        assert result.situation_id == "sit-p705-001"
        assert result.company_id == "meridian"
        assert result.now == NOW


class TestAInvalidDiscoveryRejected:
    def test_a2_success_false_is_invalid_discovery_result(self) -> None:
        from agents.reasoning.resolution import reason  # type: ignore[import-not-found]

        from agents.discovery.result import DiscoveryFailure

        bad2 = DiscoveryResult(
            success=False,
            situation_id="sit-p705-001",
            company_id="meridian",
            now=NOW,
            evidence_refs=None,
            observations=None,
            hypotheses=None,
            proposals=None,
            failure=DiscoveryFailure(code="MISSING_EVIDENCE", detail="missing"),
        )
        ctx = _context()
        out = reason(bad2, context=ctx)
        assert getattr(out, "success", True) is False
        assert getattr(out.failure, "code", "") == "INVALID_DISCOVERY_RESULT"

    def test_a_blank_situation_rejected(self) -> None:
        from agents.reasoning.resolution import reason  # type: ignore[import-not-found]

        reg = _registry()
        ref = reg.create_reference("ev-ledger-001")
        bad = DiscoveryResult(
            success=True,
            situation_id="   ",
            company_id="meridian",
            now=NOW,
            evidence_refs=(ref,),
            observations=("advisory",),
            hypotheses=None,
            proposals=None,
            failure=None,
        )
        ctx = _context()
        with pytest.raises((ValidationError, AuthorityError, ValueError)):
            reason(bad, context=ctx)

    def test_a_cannot_invent_evidence_scope(self) -> None:
        from agents.reasoning.resolution import reason  # type: ignore[import-not-found]

        reg = _registry()
        extra_ref = reg.create_reference("ev-ledger-002")
        disc_invented = DiscoveryResult(
            success=True,
            situation_id="sit-p705-001",
            company_id="meridian",
            now=NOW,
            evidence_refs=(extra_ref,),
            observations=("advisory",),
            hypotheses=None,
            proposals=None,
            failure=None,
        )
        ctx = _context()
        out = reason(disc_invented, context=ctx)
        assert getattr(out, "success", True) is False
        assert getattr(getattr(out, "failure", None), "code", "") in (
            "SCOPE_MISMATCH",
            "INVALID_DISCOVERY_RESULT",
        )


class TestAContextMismatch:
    def test_a_scope_mismatch_context_vs_discovery(self) -> None:
        from agents.reasoning.resolution import reason  # type: ignore[import-not-found]

        disc = _valid_discovery()
        factory = RuntimeFactory()
        other_ctx = factory.create_context(
            situation_id="sit-other-999",
            now=NOW,
            registry=_registry(),
            boundary=AuthorityBoundary(),
        )
        out = reason(disc, context=other_ctx)
        assert getattr(out, "success", True) is False
        assert getattr(getattr(out, "failure", None), "code", "") == "SCOPE_MISMATCH"


# ---------------------------------------------------------------------------
# Gate B — Output: advisory fields, never authoritative markers
# ---------------------------------------------------------------------------


class TestBAdvisoryOutputShape:
    def test_b_success_carries_required_advisory_fields(self) -> None:
        from agents.reasoning.resolution import reason  # type: ignore[import-not-found]

        disc = _valid_discovery()
        ctx = _context()
        result = reason(disc, context=ctx)
        assert hasattr(result, "candidate_interpretation")
        assert hasattr(result, "evidence_refs")
        assert hasattr(result, "conflicting_evidence")
        assert hasattr(result, "uncertainty")
        assert hasattr(result, "rationale")
        assert hasattr(result, "unresolved_questions")
        assert hasattr(result, "advisory_proposal")
        assert hasattr(result, "tier")
        assert result.tier == "reasoning"
        assert result.candidate_interpretation.strip()
        assert result.uncertainty.strip()
        assert result.rationale.strip()

    def test_b_never_contains_authoritative_markers(self) -> None:
        from agents.reasoning.resolution import reason  # type: ignore[import-not-found]

        disc = _valid_discovery()
        ctx = _context()
        result = reason(disc, context=ctx)
        blob = str(result.to_dict() if hasattr(result, "to_dict") else str(result))
        for marker in (
            "VERIFIED",
            "FAILED",
            "APPROVED",
            "EXECUTED",
            "SETTLED",
            "FACT",
            "DECISION",
        ):
            assert marker not in blob
        d = result.to_dict() if hasattr(result, "to_dict") else {}
        for k in ("status", "verdict", "decision", "amount"):
            assert k not in d

    def test_b_advisory_proposal_disjoint_from_capability_verbs(self) -> None:
        from agents.reasoning.resolution import reason  # type: ignore[import-not-found]

        disc = _valid_discovery()
        ctx = _context()
        result = reason(disc, context=ctx)
        if getattr(result, "advisory_proposal", None) is not None:
            assert result.advisory_proposal not in {c.value for c in AgentCapability}
            assert result.advisory_proposal not in {
                "mutate_financial_state",
                "execute_financial_correction",
                "approve",
                "VERIFIED",
            }


# ---------------------------------------------------------------------------
# Gate C — Evidence-grounded
# ---------------------------------------------------------------------------


class TestCEvidenceGrounded:
    def test_c_every_conclusion_traceable_to_discovery_evidence(self) -> None:
        from agents.reasoning.resolution import reason  # type: ignore[import-not-found]

        disc = _valid_discovery()
        ctx = _context()
        result = reason(disc, context=ctx)
        disc_ids = {r.evidence_id for r in disc.evidence_refs or ()}
        result_ids = {r.evidence_id for r in getattr(result, "evidence_refs", ()) or ()}
        assert result_ids.issubset(disc_ids)
        for eid in getattr(result, "conflicting_evidence", ()):
            assert eid in disc_ids
        for q in getattr(result, "unresolved_questions", ()):
            assert isinstance(q, str) and q.strip()

    def test_c_unsupported_assertion_is_refused(self) -> None:
        from agents.reasoning.resolution import reason  # type: ignore[import-not-found]

        empty_disc = DiscoveryResult(
            success=True,
            situation_id="sit-p705-001",
            company_id="meridian",
            now=NOW,
            evidence_refs=None,
            observations=None,
            hypotheses=None,
            proposals=None,
            failure=None,
        )
        ctx = _context()
        out = reason(empty_disc, context=ctx)
        assert getattr(out, "success", True) is False
        assert getattr(getattr(out, "failure", None), "code", "") in (
            "INSUFFICIENT_EVIDENCE",
            "INVALID_DISCOVERY_RESULT",
            "REASONING_FAILED",
        )


# ---------------------------------------------------------------------------
# Gate D — Uncertainty preservation
# ---------------------------------------------------------------------------


class TestDUncertaintyPreservation:
    def test_d_contradictory_remains_flagged(self) -> None:
        from agents.reasoning.resolution import reason  # type: ignore[import-not-found]

        from agents.discovery.engine import discover

        reg = _registry()
        ctx = RuntimeFactory().create_context(
            situation_id="sit-p705-001",
            now=NOW,
            registry=reg,
            boundary=AuthorityBoundary(),
        )
        req = DiscoveryRequest(
            situation_id="sit-p705-001",
            company_id="meridian",
            now=NOW,
            allowed_evidence_ids=("ev-ledger-001", "ev-ledger-002"),
            objective="Correlate contradictory evidence.",
            allowed_capabilities=(AgentCapability.CORRELATE,),
        )
        disc = discover(req, context=ctx)
        result = reason(disc, context=ctx)
        has_conflict = len(getattr(result, "conflicting_evidence", ())) > 0
        has_uncertain = "contradict" in getattr(result, "uncertainty", "").lower()
        assert has_conflict or has_uncertain

    def test_d_missing_evidence_remains_unresolved(self) -> None:
        from agents.reasoning.resolution import reason  # type: ignore[import-not-found]

        disc = _valid_discovery()
        ctx = _context()
        result = reason(disc, context=ctx)
        assert getattr(result, "uncertainty", "").strip() != ""
        assert "VERIFIED" not in getattr(result, "candidate_interpretation", "")

    def test_d_stale_not_resolved_by_confidence(self) -> None:
        from agents.reasoning.resolution import reason  # type: ignore[import-not-found]

        from agents.discovery.engine import discover

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
        factory = RuntimeFactory()
        ctx = factory.create_context(
            situation_id="sit-p705-001",
            now=NOW,
            registry=reg,
            boundary=AuthorityBoundary(),
        )
        req = DiscoveryRequest(
            situation_id="sit-p705-001",
            company_id="meridian",
            now=NOW,
            allowed_evidence_ids=("ev-stale-001",),
            objective="Check stale handling.",
            allowed_capabilities=(AgentCapability.READ,),
        )
        disc = discover(req, context=ctx)
        out = reason(disc, context=ctx)
        assert getattr(out, "success", True) is False
        assert getattr(getattr(out, "failure", None), "code", "") in (
            "STALE_EVIDENCE",
            "INVALID_DISCOVERY_RESULT",
        )


# ---------------------------------------------------------------------------
# Gate E — Capability boundary: no WRITE/EXECUTE/APPROVE/VERIFY
# ---------------------------------------------------------------------------


class TestECapabilityBoundary:
    def test_e_no_mutation_attributes(self) -> None:
        path = Path("agents/reasoning/resolution.py")
        assert path.exists(), "RED: agents/reasoning/resolution.py not yet implemented"
        text = path.read_text()
        for kw in ("mutate_financial", "execute_financial"):
            assert kw not in text.lower()
        for kw in ("def approve", "def verify", "def write", "def commit"):
            assert kw not in text.lower()

    def test_e_remains_advisory_not_verified(self) -> None:
        from agents.reasoning.resolution import reason  # type: ignore[import-not-found]

        disc = _valid_discovery()
        ctx = _context()
        result = reason(disc, context=ctx)
        assert getattr(result, "tier", "") == "reasoning"
        blob = str(result.to_dict() if hasattr(result, "to_dict") else "")
        assert "VERIFIED" not in blob


# ---------------------------------------------------------------------------
# Gate F — No second authority
# ---------------------------------------------------------------------------


class TestFNoSecondAuthority:
    def test_f_no_registry_or_boundary_instantiation(self) -> None:
        path = Path("agents/reasoning/resolution.py")
        assert path.exists(), "RED: agents/reasoning/resolution.py not yet implemented"
        text = path.read_text()
        assert "EvidenceRegistry(" not in text
        assert "AuthorityBoundary(" not in text
        assert "to_authoritative" not in text
        assert "to_fact" not in text

    def test_f_no_direct_external_imports(self) -> None:
        path = Path("agents/reasoning/resolution.py")
        assert path.exists(), "RED: agents/reasoning/resolution.py not yet implemented"
        text = path.read_text()
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in (
                        "httpx",
                        "requests",
                        "boto3",
                        "psycopg",
                        "openai",
                        "temporalio",
                    )
            if isinstance(node, ast.ImportFrom):
                assert node.module not in (
                    "httpx",
                    "requests",
                    "boto3",
                    "psycopg",
                    "openai",
                    "temporalio",
                )


# ---------------------------------------------------------------------------
# Gate G — Deterministic/probabilistic separation
# ---------------------------------------------------------------------------


class TestGConfidenceSeparation:
    def test_g_high_confidence_still_advisory(self) -> None:
        from agents.reasoning.resolution import reason  # type: ignore[import-not-found]

        disc = _valid_discovery()
        ctx = _context()
        result = reason(disc, context=ctx)
        d = result.to_dict() if hasattr(result, "to_dict") else {}
        assert "VERIFIED" not in str(d)
        assert d.get("tier") == "reasoning"
        if hasattr(result, "confidence"):
            assert result.confidence < 1.0

    def test_g_absolute_certainty_refused(self) -> None:
        try:
            from agents.reasoning.resolution import (  # type: ignore[import-not-found]
                ReasoningResult,
            )

            reg = _registry()
            ref = reg.create_reference("ev-ledger-001")
            with pytest.raises((ValidationError, AuthorityError, ValueError)):
                ReasoningResult(  # type: ignore[call-arg]
                    situation_id="sit-p705-001",
                    company_id="meridian",
                    now=NOW,
                    evidence_refs=(ref,),
                    candidate_interpretation="interpretation",
                    conflicting_evidence=(),
                    uncertainty="uncertain",
                    rationale="grounded",
                    unresolved_questions=(),
                    advisory_proposal=None,
                    confidence=1.0,
                )
        except ImportError:
            pytest.fail("RED: ReasoningResult not yet implemented")


# ---------------------------------------------------------------------------
# Gate H — Replay/context integrity
# ---------------------------------------------------------------------------


class TestHReplayIntegrity:
    def test_h_preserves_situation_company_now_scope(self) -> None:
        from agents.reasoning.resolution import reason  # type: ignore[import-not-found]

        disc = _valid_discovery()
        ctx = _context()
        result = reason(disc, context=ctx)
        assert result.situation_id == disc.situation_id == ctx.situation_id
        assert result.company_id == disc.company_id == ctx.company_id
        assert result.now == disc.now == ctx.now
        disc_ids = {r.evidence_id for r in disc.evidence_refs or ()}
        result_ids = {r.evidence_id for r in result.evidence_refs or ()}
        assert result_ids.issubset(disc_ids)

    def test_h_no_wall_clock(self) -> None:
        path = Path("agents/reasoning/resolution.py")
        assert path.exists(), "RED: agents/reasoning/resolution.py not yet implemented"
        text = path.read_text()
        assert "datetime.now" not in text
        assert "datetime.utcnow" not in text
        assert "time.time" not in text


# ---------------------------------------------------------------------------
# Gate I — Failure semantics: typed, not plausible
# ---------------------------------------------------------------------------


class TestIFailureSemantics:
    def test_i_typed_failure_codes_only(self) -> None:
        from agents.reasoning.resolution import reason  # type: ignore[import-not-found]

        from agents.discovery.result import DiscoveryFailure

        allowed = {
            "INSUFFICIENT_EVIDENCE",
            "CONTRADICTORY_EVIDENCE",
            "STALE_EVIDENCE",
            "SCOPE_MISMATCH",
            "INVALID_DISCOVERY_RESULT",
            "REASONING_FAILED",
        }
        bad_disc = DiscoveryResult(
            success=False,
            situation_id="sit-p705-001",
            company_id="meridian",
            now=NOW,
            evidence_refs=None,
            observations=None,
            hypotheses=None,
            proposals=None,
            failure=DiscoveryFailure(code="MISSING_EVIDENCE", detail="missing"),
        )
        ctx = _context()
        out = reason(bad_disc, context=ctx)
        assert getattr(out, "success", True) is False
        assert getattr(getattr(out, "failure", None), "code", "") in allowed

    def test_i_no_plausible_resolution_on_failure(self) -> None:
        from agents.reasoning.resolution import reason  # type: ignore[import-not-found]

        from agents.discovery.result import DiscoveryFailure

        bad_disc = DiscoveryResult(
            success=False,
            situation_id="sit-p705-001",
            company_id="meridian",
            now=NOW,
            evidence_refs=None,
            observations=None,
            hypotheses=None,
            proposals=None,
            failure=DiscoveryFailure(code="STALE_EVIDENCE", detail="stale"),
        )
        ctx = _context()
        out = reason(bad_disc, context=ctx)
        assert getattr(out, "success", True) is False
        has_interp = hasattr(out, "candidate_interpretation")
        is_none = getattr(out, "candidate_interpretation", None) is None
        assert not has_interp or is_none
