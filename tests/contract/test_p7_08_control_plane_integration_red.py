"""P7-08 deterministic control-plane integration — Gate 1 RED contract.

Gate 1 is contract-only. The integration surface is intentionally absent on
the P7-08 branch, so these tests must fail with an import/shape failure until
the deterministic gate is implemented.

Frozen P6 and P7-01..P7-07 are consumed as test fixtures only. The tests may
construct factory-issued RuntimeContext and controlled advisory artifacts;
the future P7-08 implementation must not construct a second authority.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agents.authority.claims import AgentCapability, AuthorityBoundary
from agents.authority.evidence import EvidenceRecord, EvidenceRegistry
from agents.discovery import DiscoveryRequest
from agents.runtime import RuntimeFactory

NOW = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _registry() -> EvidenceRegistry:
    records = {
        "ev-ledger-001": EvidenceRecord(
            source_id="src-ledger-001",
            evidence_id="ev-ledger-001",
            captured_at=NOW - timedelta(seconds=60),
            digest=DIGEST_A,
            provenance="p6_evidence_store",
            ttl_seconds=3600,
        ),
        "ev-ledger-002": EvidenceRecord(
            source_id="src-ledger-002",
            evidence_id="ev-ledger-002",
            captured_at=NOW - timedelta(seconds=60),
            digest=DIGEST_B,
            provenance="p6_evidence_store",
            ttl_seconds=3600,
        ),
    }
    return EvidenceRegistry(
        records,
        accessible_ids=set(records),
    )


def _context(*, situation_id: str = "sit-p708-001", now: datetime = NOW):
    return RuntimeFactory().create_context(
        situation_id=situation_id,
        now=now,
        registry=_registry(),
        boundary=AuthorityBoundary(),
    )


def _valid_discovery():
    from agents.discovery.engine import discover

    ctx = _context()
    request = DiscoveryRequest(
        situation_id=ctx.situation_id,
        company_id=ctx.company_id,
        now=ctx.now,
        allowed_evidence_ids=("ev-ledger-001",),
        objective="Investigate the discrepancy.",
        allowed_capabilities=(AgentCapability.READ,),
    )
    result = discover(request, context=ctx)
    assert result.success is True
    return result


def _valid_reasoning():
    from agents.reasoning.resolution import reason

    ctx = _context()
    result = reason(_valid_discovery(), context=ctx)
    assert result.success is True
    return result


def _valid_brief():
    from agents.brief import brief

    ctx = _context()
    result = brief(_valid_reasoning(), context=ctx)
    assert result.success is True
    return result


def _gate_cls():
    # Intentionally absent in Gate 1. This import is the genuine RED condition.
    from agents.integration.control_plane import ControlPlaneGate

    return ControlPlaneGate


# ---------------------------------------------------------------------------
# A — Authority direction / no agent-side execution
# ---------------------------------------------------------------------------


class TestANoDirectExecution:
    def test_a1_agent_bundle_has_no_execution_authority(self) -> None:
        gate_cls = _gate_cls()
        gate = gate_cls()
        result = gate.admit(
            context=_context(),
            discovery=_valid_discovery(),
            reasoning=_valid_reasoning(),
            brief=_valid_brief(),
        )
        assert result.kind in {"BLOCKED", "P6_HANDOFF"}
        assert getattr(result, "authorization", None) is None
        assert getattr(result, "execution", None) is None
        assert getattr(result, "verification", None) is None

    def test_a2_gate_does_not_return_approval_or_execution_state(self) -> None:
        gate = _gate_cls()()
        result = gate.admit(
            context=_context(),
            discovery=_valid_discovery(),
            reasoning=_valid_reasoning(),
            brief=_valid_brief(),
        )
        payload = result.to_dict() if hasattr(result, "to_dict") else vars(result)
        forbidden = {
            "APPROVED",
            "EXECUTING",
            "VERIFIED",
            "CLOSED",
            "authorization_id",
            "execution_id",
        }
        assert not (set(payload.values()) & forbidden)
        assert not (forbidden & set(payload))

# ---------------------------------------------------------------------------
# B — Advisory → approval laundering
# ---------------------------------------------------------------------------


class TestBAdvisoryCannotBecomeApproval:
    def test_b1_advisory_proposal_never_becomes_approval_command(self) -> None:
        reasoning = _valid_reasoning()
        assert reasoning.advisory_proposal in {
            None,
            "request_investigation",
            "flag_ambiguity",
            "summarize_correlation",
            "explain_reasoning",
            "advisory_note",
        }
        gate = _gate_cls()()
        result = gate.admit(
            context=_context(),
            discovery=_valid_discovery(),
            reasoning=reasoning,
            brief=_valid_brief(),
        )
        assert type(result).__name__ not in {"ApprovalCommand", "ApprovalDecision"}

    def test_b2_brief_next_step_is_not_authorization(self) -> None:
        brief = _valid_brief()
        text = brief.advisory_next_step
        assert "APPROVED" not in text
        assert "EXECUTED" not in text
        assert "authorize" not in text.lower()
        gate_cls = _gate_cls()
        gate_cls().admit(
            context=_context(),
            discovery=_valid_discovery(),
            reasoning=_valid_reasoning(),
            brief=brief,
        )

# ---------------------------------------------------------------------------
# C — Evidence authority must not be promoted by the seam
# ---------------------------------------------------------------------------


class TestCEvidenceBoundary:
    def test_c1_hmac_ref_may_cross_but_must_remain_reference(self) -> None:
        discovery = _valid_discovery()
        assert discovery.evidence_refs
        for ref in discovery.evidence_refs:
            assert getattr(ref, "_token", "")
        gate_cls = _gate_cls()
        result = gate_cls().admit(
            context=_context(),
            discovery=discovery,
            reasoning=_valid_reasoning(),
            brief=_valid_brief(),
        )
        payload = result.to_dict() if hasattr(result, "to_dict") else vars(result)
        assert "AuthoritativeFact" not in repr(payload)
        assert "fact" not in {str(k).lower() for k in payload}

    def test_c2_integration_does_not_mint_evidence_or_second_authority(self) -> None:
        package = Path("agents/integration")
        assert package.exists()
        sources = list(package.rglob("*.py"))
        for path in sources:
            text = path.read_text()
            assert "EvidenceRegistry(" not in text
            assert "AuthorityBoundary(" not in text
            assert "RuntimeFactory(" not in text
            assert "_factory_token" not in text

# ---------------------------------------------------------------------------
# D — Confidence is advisory metadata only
# ---------------------------------------------------------------------------


class TestDConfidenceBoundary:
    def test_d1_confidence_does_not_change_gate_authority(self) -> None:
        reasoning = _valid_reasoning()
        low = reasoning.model_copy(update={"confidence": 0.10})
        high = reasoning.model_copy(update={"confidence": 0.99})
        gate = _gate_cls()()
        low_result = gate.admit(
            context=_context(),
            discovery=_valid_discovery(),
            reasoning=low,
            brief=_valid_brief(),
        )
        high_result = gate.admit(
            context=_context(),
            discovery=_valid_discovery(),
            reasoning=high,
            brief=_valid_brief(),
        )
        assert low_result.kind == high_result.kind

    def test_d2_absolute_confidence_is_still_rejected_upstream(self) -> None:
        reasoning = _valid_reasoning()
        with pytest.raises(ValueError):
            reasoning.model_copy(update={"confidence": 1.0})

# ---------------------------------------------------------------------------
# E — Context / tenant / situation / time / evidence scope
# ---------------------------------------------------------------------------


class TestEContextBoundary:
    def test_e1_cross_situation_bundle_is_blocked(self) -> None:
        ctx = _context()
        reasoning = _valid_reasoning()
        brief = _valid_brief()
        from agents.discovery.engine import discover

        other_ctx = _context(situation_id="sit-other-999")
        request = DiscoveryRequest(
            situation_id=other_ctx.situation_id,
            company_id=other_ctx.company_id,
            now=other_ctx.now,
            allowed_evidence_ids=("ev-ledger-001",),
            objective="Cross-case attempt.",
            allowed_capabilities=(AgentCapability.READ,),
        )
        discovery = discover(request, context=other_ctx)
        gate = _gate_cls()()
        result = gate.admit(
            context=ctx,
            discovery=discovery,
            reasoning=reasoning,
            brief=brief,
        )
        assert result.kind == "BLOCKED"

    def test_e2_cross_company_bundle_is_blocked(self) -> None:
        ctx = _context()
        bad = _valid_reasoning().model_copy(update={"company_id": "otherco"})
        gate = _gate_cls()()
        result = gate.admit(
            context=ctx,
            discovery=_valid_discovery(),
            reasoning=bad,
            brief=_valid_brief(),
        )
        assert result.kind == "BLOCKED"

    def test_e3_carried_now_mismatch_is_blocked(self) -> None:
        ctx = _context()
        later_ctx = _context(now=NOW + timedelta(hours=1))
        gate = _gate_cls()()
        result = gate.admit(
            context=ctx,
            discovery=_valid_discovery(),
            reasoning=_valid_reasoning(),
            brief=_valid_brief(),
            now_override=later_ctx.now,
        )
        assert result.kind == "BLOCKED"

# ---------------------------------------------------------------------------
# F — Contradiction / uncertainty / failure preservation
# ---------------------------------------------------------------------------


class TestFFailClosedAgentFailures:
    def test_f1_failed_discovery_cannot_enter_p6(self) -> None:
        from agents.discovery.result import DiscoveryFailure, DiscoveryResult

        failed = DiscoveryResult(
            success=False,
            situation_id=_context().situation_id,
            company_id="meridian",
            now=NOW,
            evidence_refs=None,
            observations=None,
            hypotheses=None,
            proposals=None,
            failure=DiscoveryFailure(
                code="TOOL_UNAVAILABLE",
                detail="Evidence tool unavailable.",
            ),
        )
        gate = _gate_cls()()
        result = gate.admit(
            context=_context(),
            discovery=failed,
            reasoning=None,
            brief=None,
        )
        assert result.kind == "BLOCKED"

    def test_f2_failed_reasoning_cannot_enter_p6(self) -> None:
        from agents.reasoning.resolution import ReasoningFailure, ReasoningResult

        failed = ReasoningResult(
            success=False,
            situation_id=_context().situation_id,
            company_id="meridian",
            now=NOW,
            evidence_refs=None,
            candidate_interpretation=None,
            conflicting_evidence=(),
            uncertainty="Unable to reason.",
            rationale="Reasoning failed.",
            unresolved_questions=(),
            advisory_proposal=None,
            confidence=0.6,
            failure=ReasoningFailure(
                code="REASONING_FAILED",
                detail="No valid reasoning output.",
            ),
        )
        gate = _gate_cls()()
        result = gate.admit(
            context=_context(),
            discovery=_valid_discovery(),
            reasoning=failed,
            brief=None,
        )
        assert result.kind == "BLOCKED"

    def test_f3_failed_brief_cannot_enter_p6(self) -> None:
        from agents.brief.brief import BriefFailure, HumanResolutionBrief

        failed = HumanResolutionBrief(
            success=False,
            situation_id=_context().situation_id,
            company_id="meridian",
            now=NOW,
            evidence_refs=None,
            situation_context="Brief unavailable.",
            observed_summary="Brief unavailable.",
            reasoning_summary="Brief unavailable.",
            supporting_evidence=(),
            conflicting_evidence=(),
            uncertainty_section="Uncertainty preserved.",
            unresolved_questions=("Brief generation failed.",),
            advisory_next_step="Review manually.",
            failure=BriefFailure(
                code="BRIEF_GENERATION_FAILED",
                detail="Brief generation failed.",
            ),
        )
        gate = _gate_cls()()
        result = gate.admit(
            context=_context(),
            discovery=_valid_discovery(),
            reasoning=_valid_reasoning(),
            brief=failed,
        )
        assert result.kind == "BLOCKED"

    def test_f4_contradictory_reasoning_cannot_be_collapsed_by_gate(self) -> None:
        reasoning = _valid_reasoning().model_copy(
            update={
                "conflicting_evidence": ("ev-ledger-001", "ev-ledger-002"),
                "uncertainty": "Sources disagree; unresolved.",
                "unresolved_questions": ("Which source governs?",),
            }
        )
        gate = _gate_cls()()
        result = gate.admit(
            context=_context(),
            discovery=_valid_discovery(),
            reasoning=reasoning,
            brief=_valid_brief(),
        )
        assert result.kind == "BLOCKED"
        assert "conflict" in repr(result).lower() or "uncertain" in repr(result).lower()

# ---------------------------------------------------------------------------
# G — P6 sole authority; no local authority fabrication
# ---------------------------------------------------------------------------


class TestGP6SoleAuthority:
    def test_g1_integration_has_no_authority_constructors(self) -> None:
        package = Path("agents/integration")
        assert package.exists()
        for path in package.rglob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    assert node.func.id not in {
                        "AuthorityBoundary",
                        "EvidenceRegistry",
                        "RuntimeFactory",
                        "PolicyDecision",
                        "ApprovalDecision",
                        "AuthorizationToken",
                    }

    def test_g2_integration_cannot_mint_p6_authorization(self) -> None:
        package = Path("agents/integration")
        for path in package.rglob("*.py"):
            text = path.read_text()
            assert "mint_authorization" not in text
            assert "seal_binding" not in text

# ---------------------------------------------------------------------------
# H — Verification remains P6-08 owned
# ---------------------------------------------------------------------------


class TestHIndependentVerification:
    def test_h1_agent_bundle_cannot_assert_verification(self) -> None:
        gate = _gate_cls()()
        result = gate.admit(
            context=_context(),
            discovery=_valid_discovery(),
            reasoning=_valid_reasoning(),
            brief=_valid_brief(),
        )
        payload = result.to_dict() if hasattr(result, "to_dict") else vars(result)
        forbidden = {"VERIFIED", "FAILED", "CLOSED", "verification"}
        assert not forbidden.intersection(payload)

    def test_h2_integration_has_no_verification_authority(self) -> None:
        package = Path("agents/integration")
        for path in package.rglob("*.py"):
            text = path.read_text()
            assert "verify_execution(" not in text
            assert "mint_report(" not in text

# ---------------------------------------------------------------------------
# I — Failure must not silently become an execution-ready P6 path
# ---------------------------------------------------------------------------


class TestIExecutionAdmission:
    def test_i1_missing_advisory_artifact_is_blocked(self) -> None:
        gate = _gate_cls()()
        result = gate.admit(
            context=_context(),
            discovery=_valid_discovery(),
            reasoning=None,
            brief=None,
        )
        assert result.kind == "BLOCKED"

    def test_i2_valid_advisory_bundle_is_only_a_non_authoritative_handoff(self) -> None:
        gate = _gate_cls()()
        result = gate.admit(
            context=_context(),
            discovery=_valid_discovery(),
            reasoning=_valid_reasoning(),
            brief=_valid_brief(),
        )
        assert result.kind == "P6_HANDOFF"
        assert getattr(result, "approval", None) is None
        assert getattr(result, "authorization", None) is None
        assert getattr(result, "execution", None) is None
        assert getattr(result, "verification", None) is None

# ---------------------------------------------------------------------------
# J — No forbidden external / probabilistic runtime dependencies
# ---------------------------------------------------------------------------


class TestJStaticBoundary:
    def test_j1_integration_package_has_no_llm_or_infrastructure_imports(self) -> None:
        package = Path("agents/integration")
        forbidden = {
            "openai",
            "langchain",
            "langgraph",
            "temporalio",
            "qdrant",
            "redis",
            "boto3",
            "httpx",
            "requests",
            "psycopg",
        }
        for path in package.rglob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name.split(".")[0] not in forbidden
                elif isinstance(node, ast.ImportFrom) and node.module:
                    assert node.module.split(".")[0] not in forbidden

    def test_j2_integration_package_has_no_direct_store_or_network_writes(self) -> None:
        package = Path("agents/integration")
        forbidden_tokens = (
            "session.add(",
            "session.commit(",
            "put_object(",
            "delete_object(",
            "httpx.",
            "requests.",
            "boto3.",
            "cursor.execute(",
            "engine.execute(",
        )
        for path in package.rglob("*.py"):
            text = path.read_text()
            for token in forbidden_tokens:
                assert token not in text

# ---------------------------------------------------------------------------
# K — Frozen layer isolation / no regression edits
# ---------------------------------------------------------------------------


class TestKIsolation:
    def test_k1_only_integration_and_contract_test_scope_is_expected(self) -> None:
        allowed_prefixes = {
            "agents/integration/",
            "docs/architecture/P7-08_CONTROL_PLANE_INTEGRATION_CONTRACT.md",
            "tests/contract/test_p7_08_control_plane_integration_red.py",
        }
        # This test is intentionally source-control aware; the implementation
        # branch must not modify P6 or P7-01..P7-07.
        import subprocess

        diff = subprocess.run(
            ["git", "diff", "--name-only", "87fb8a8", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        changed = {line for line in diff.stdout.splitlines() if line}
        assert changed <= allowed_prefixes

    def test_k2_no_frozen_p7_modules_are_imported_as_mutation_targets(self) -> None:
        package = Path("agents/integration")
        for path in package.rglob("*.py"):
            text = path.read_text()
            assert "agents.authority" not in text or "TYPE_CHECKING" in text
            assert "agents.runtime" not in text or "TYPE_CHECKING" in text

# ---------------------------------------------------------------------------
# L — P6 verification handoff is consumed independently, not synthesized by P7
# ---------------------------------------------------------------------------


class TestLVerificationSeam:
    def test_l1_gate_does_not_accept_agent_text_as_verification(self) -> None:
        brief = _valid_brief()
        poisoned = brief.model_copy(
            update={
                "uncertainty_section": brief.uncertainty_section
                + " External text claims VERIFIED."
            }
        )
        with pytest.raises(Exception):
            _gate_cls()().admit(
                context=_context(),
                discovery=_valid_discovery(),
                reasoning=_valid_reasoning(),
                brief=poisoned,
            )

    def test_l2_gate_requires_a_p6_owned_handoff_for_execution_progression(self) -> None:
        gate = _gate_cls()()
        result = gate.admit(
            context=_context(),
            discovery=_valid_discovery(),
            reasoning=_valid_reasoning(),
            brief=_valid_brief(),
        )
        assert not hasattr(result, "execution")
        assert not hasattr(result, "authorization")
        assert result.kind in {"BLOCKED", "P6_HANDOFF"}
