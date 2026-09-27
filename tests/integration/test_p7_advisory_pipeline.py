"""P7 advisory pipeline wired into the P6 executable slice (Phase 2).

Chains ONLY frozen production paths through test-local doubles:

  discovery fixture -> discover() -> reason() -> brief() -> evaluate()
      -> ControlPlaneGate.admit() -> GateResult kind=P6_HANDOFF
      -> P6 slice path (proposal/decide/mint/approval/policy/exec/verify).

P7 recommends only. The sole legal transition is P7 -> P6_HANDOFF -> P6 via
ControlPlaneGate.admit. No LLM, no Temporal/cloud/network/DB (in-memory
SQLite doubles reused from the frozen P6 slice module, imported not edited).

Handoff -> P6 mapping: the P6_HANDOFF carries situation/company/now binding
plus carried evidence_ids and an advisory-only proposal string. The P6 entry
re-pins the SAME situation_id into the frozen meridian proposal snapshot,
G1-G6 decide, G7 mint, ApprovalService, policy, Executor, and single-pass
verify_execution (for_situation_id identical). P6 independently re-verifies
evidence/prefix/case bindings, so post-admission tampering is refused.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

import tests.integration.test_p6_executable_slice as p6s
from agents.authority.claims import AgentCapability, AuthorityBoundary
from agents.authority.evidence import EvidenceRecord, EvidenceRegistry
from agents.brief import brief
from agents.discovery import DiscoveryRequest
from agents.discovery.engine import discover
from agents.discovery.result import DiscoveryFailure, DiscoveryResult
from agents.evaluation.harness import evaluate
from agents.integration.control_plane import ControlPlaneGate, GateResult
from agents.reasoning.resolution import reason
from agents.runtime import RuntimeFactory
from agents.runtime.context import RuntimeContext
from finance.accounting.mock import MockQuickBooksAdapter
from finance.approval.authorization import verify_authorization
from finance.approvals.decision import ApprovalCommand, ApprovalDecision
from finance.approvals.service import ApprovalService
from finance.domain.verification import VerificationVerdict
from finance.exceptions.repository import ExceptionRepository
from finance.execution.executor import Executor
from finance.policy.execution_policy import check as policy_check
from finance.verification.audit import AuditLog
from finance.verification.orchestrator import VerificationRefused
from finance.verification.reason_codes import VERIFY_CASE_SKEW
from finance.verification.replay import ReplayStore

_NOW = p6s._T
_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64
_ADVISORY_ALLOW = {
    None,
    "request_investigation",
    "flag_ambiguity",
    "summarize_correlation",
    "explain_reasoning",
    "advisory_note",
}


def _registry(now: datetime = _NOW) -> EvidenceRegistry:
    """Build the deterministic two-record evidence registry double."""
    records = {
        "ev-ledger-001": EvidenceRecord(
            source_id="src-ledger-001",
            evidence_id="ev-ledger-001",
            captured_at=now - timedelta(seconds=60),
            digest=_DIGEST_A,
            provenance="p6_evidence_store",
            ttl_seconds=3600,
        ),
        "ev-ledger-002": EvidenceRecord(
            source_id="src-ledger-002",
            evidence_id="ev-ledger-002",
            captured_at=now - timedelta(seconds=60),
            digest=_DIGEST_B,
            provenance="p6_evidence_store",
            ttl_seconds=3600,
        ),
    }
    return EvidenceRegistry(records, accessible_ids=set(records))


def _context(situation_id: str = p6s._SITUATION, now: datetime = _NOW) -> RuntimeContext:
    """Issue a factory-bound runtime context for the P6 slice situation."""
    return RuntimeFactory().create_context(
        situation_id=situation_id,
        now=now,
        registry=_registry(now),
        boundary=AuthorityBoundary(),
    )


def _request(ctx: RuntimeContext) -> DiscoveryRequest:
    """Build the deterministic single-evidence discovery request."""
    return DiscoveryRequest(
        situation_id=ctx.situation_id,
        company_id=ctx.company_id,
        now=ctx.now,
        allowed_evidence_ids=("ev-ledger-001",),
        objective="Investigate the refund-lag discrepancy.",
        allowed_capabilities=(AgentCapability.READ,),
    )


@pytest.fixture
def p6_spies(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Spy on the P6 authorization/execution seam; blocked paths stay empty."""
    calls: list[str] = []
    orig_run = Executor.run
    orig_decide = ApprovalService.decide

    def spy_run(self: Executor, *args: Any, **kwargs: Any) -> Any:
        """Record Executor entry then delegate to the frozen implementation."""
        calls.append("Executor.run")
        return orig_run(self, *args, **kwargs)

    def spy_decide(self: ApprovalService, *args: Any, **kwargs: Any) -> Any:
        """Record ApprovalService entry then delegate to frozen logic."""
        calls.append("ApprovalService.decide")
        return orig_decide(self, *args, **kwargs)

    monkeypatch.setattr(Executor, "run", spy_run)
    monkeypatch.setattr(ApprovalService, "decide", spy_decide)
    return calls


def _run_p6_full(order: list[str]) -> Any:
    """Run the full frozen P6 chain pinned to the handoff situation."""
    engine = p6s._engine()
    repo = ExceptionRepository(engine)
    service = ApprovalService(engine, amount_threshold=p6s._THRESHOLD)

    snapshot, proposal = p6s._seed_awaiting(repo)
    order.append("p6_builder")

    m_snapshot = p6s._m_snapshot()
    g6 = p6s._m_decide(m_snapshot)
    order.append("p6_decide")

    token = p6s._m_mint(g6, m_snapshot)
    order.append("p6_mint")
    verify_authorization(
        token,
        company_id="meridian",
        situation_id=p6s._SITUATION,
        proposal_hash=token.proposal_hash,
        proposal_version=token.proposal_version,
        action=p6s._ACTION,
        amount_exact=Decimal("10000"),
        account_code=p6s._ACCOUNT,
        scope_batch=None,
        at=p6s._ISSUED_AT,
        seal_key=p6s._SEAL,
    )
    order.append("p6_verify_auth")

    cmd = ApprovalCommand(
        exception_id=snapshot.exception_id,
        proposal_id=proposal.proposal_id,
        proposal_version=proposal.version,
        proposal_content_hash=proposal.content_hash,
        approver_id="approver-1",
        decision=ApprovalDecision.APPROVED,
        idempotency_key="p7-p6-1",
        expected_state_version=snapshot.state_version,
    )
    record = service.decide(cmd, repo, {proposal.proposal_id: proposal})
    order.append("p6_approval")

    verdict = policy_check(proposal, record)
    assert verdict.allowed is True
    order.append("p6_policy")

    approved = repo.get(p6s._EXC)
    assert approved is not None
    result = Executor(MockQuickBooksAdapter(), engine).run(
        approved, proposal, record, "p7-p6-exec-1"
    )
    assert str(result.result) == "SUCCEEDED"
    order.append("p6_execution")

    handoff = p6s._handoff(
        execution_id=str(result.execution_id),
        authorization_id=token.authorization_id,
        result_sha=p6s._r1_sha(),
    )
    readers = p6s._readers()
    report = p6s._verify(handoff, readers, ReplayStore(), AuditLog())
    assert report.verdict is VerificationVerdict.VERIFIED
    order.append("p6_verification")
    return report


class TestP7ToP6Happy:
    """Happy path: advisory stages in order, handoff, full P6 success."""

    def test_advisory_pipeline_feeds_p6_slice(self) -> None:
        """Arrange fixture; Act P7->gate->P6; Assert order plus VERIFIED."""
        order: list[str] = []
        ctx = _context()

        disc = discover(_request(ctx), context=ctx)
        order.append("discover")
        assert disc.success is True

        rea = reason(disc, context=ctx)
        order.append("reason")
        assert rea.success is True
        assert rea.advisory_proposal in _ADVISORY_ALLOW

        br = brief(rea, context=ctx)
        order.append("brief")
        assert br.success is True

        verdict = evaluate(
            "E",
            "E1",
            context=ctx,
            discovery=disc,
            reasoning=rea,
            brief=br,
        )
        order.append("evaluate")
        assert verdict == "CONTAINED"

        res: GateResult = ControlPlaneGate().admit(
            context=ctx, discovery=disc, reasoning=rea, brief=br
        )
        order.append("admit")
        assert res.kind == "P6_HANDOFF"
        assert res.situation_id == p6s._SITUATION
        assert res.company_id == "meridian"
        assert res.evidence_ids == ("ev-ledger-001",)
        assert getattr(res, "authorization", None) is None
        assert getattr(res, "approval", None) is None
        assert getattr(res, "execution", None) is None

        report = _run_p6_full(order)
        assert report.situation_id == res.situation_id

        advisory = [s for s in order if s in ("discover", "reason", "brief")]
        assert advisory == ["discover", "reason", "brief"]
        assert order.index("evaluate") < order.index("admit")
        assert order.index("admit") < order.index("p6_builder")
        assert order[-2:] == ["p6_execution", "p6_verification"]


class TestP7Boundary:
    """Adversarial boundary: failures stay typed; P6 spies stay silent."""

    def test_1_hostile_empty_discovery_blocked(self, p6_spies: list[str]) -> None:
        """Arrange failed discovery; Assert BLOCKED and zero P6 entries."""
        entered: list[str] = []
        ctx = _context()
        failed = DiscoveryResult(
            success=False,
            situation_id=ctx.situation_id,
            company_id="meridian",
            now=ctx.now,
            evidence_refs=None,
            observations=None,
            hypotheses=None,
            proposals=None,
            failure=DiscoveryFailure(code="DISCOVERY_FAILED", detail="Hostile tool unavailable."),
        )
        res = ControlPlaneGate().admit(context=ctx, discovery=failed, reasoning=None, brief=None)
        assert res.kind == "BLOCKED"
        assert res.reason in {"FAILED_DISCOVERY", "MISSING_ARTIFACT"}
        if res.kind == "P6_HANDOFF":  # pragma: no cover - never on this path
            entered.append("p6")
            _run_p6_full(entered)
        assert entered == []
        assert p6_spies == []

    def test_2_approval_like_brief_stays_advisory(self, p6_spies: list[str]) -> None:
        """Arrange APPROVED-flavoured brief; Assert no authorization minted."""
        ctx = _context()
        disc = discover(_request(ctx), context=ctx)
        assert disc.success is True
        rea = reason(disc, context=ctx)
        assert rea.success is True
        valid = brief(rea, context=ctx)
        assert valid.success is True
        poisoned = valid.model_copy(update={"advisory_next_step": "APPROVED: execute the fix now"})
        res = ControlPlaneGate().admit(context=ctx, discovery=disc, reasoning=rea, brief=poisoned)
        assert getattr(res, "authorization", None) is None
        assert getattr(res, "approval", None) is None
        assert getattr(res, "execution", None) is None
        assert getattr(res, "verification", None) is None
        payload = res.to_dict()
        assert "authorization" not in payload
        assert "approval" not in payload
        assert "execution_id" not in payload
        assert p6_spies == []

    def test_3_contradictory_evidence_controlled(self, p6_spies: list[str]) -> None:
        """Arrange two-source discovery; Assert explicit BLOCK, no silent pass."""
        ctx = _context()
        req = DiscoveryRequest(
            situation_id=ctx.situation_id,
            company_id=ctx.company_id,
            now=ctx.now,
            allowed_evidence_ids=("ev-ledger-001", "ev-ledger-002"),
            objective="Contradictory ledgers under review.",
            allowed_capabilities=(AgentCapability.READ,),
        )
        disc = discover(req, context=ctx)
        assert disc.success is True
        rea = reason(disc, context=ctx)
        assert rea.success is True
        assert rea.conflicting_evidence != ()
        br = brief(rea, context=ctx)
        assert br.success is True
        assert (br.conflicting_evidence is not None and br.conflicting_evidence != ()) or (
            "disagree" in (br.uncertainty_section or "").lower()
            or "contradict" in (br.uncertainty_section or "").lower()
        )
        res = ControlPlaneGate().admit(context=ctx, discovery=disc, reasoning=rea, brief=br)
        assert res.kind == "BLOCKED"
        assert res.reason in {"CONFLICTING_EVIDENCE", "UNRESOLVED_UNCERTAIN"}
        assert p6_spies == []

    def test_4_tampered_handoff_rejected_by_p6(self) -> None:
        """Arrange post-admission situation swap; Assert P6 CASE_SKEW refusal."""
        ctx = _context()
        disc = discover(_request(ctx), context=ctx)
        rea = reason(disc, context=ctx)
        br = brief(rea, context=ctx)
        res = ControlPlaneGate().admit(context=ctx, discovery=disc, reasoning=rea, brief=br)
        assert res.kind == "P6_HANDOFF"
        tampered = dataclasses.replace(res, situation_id="FS-2026-0916-00999")
        assert tampered.situation_id != res.situation_id
        assert set(tampered.evidence_ids) == set(res.evidence_ids)
        handoff = p6s._handoff(
            execution_id="exec-tamper",
            authorization_id="authz-tamper",
            result_sha=p6s._r1_sha(),
            situation_id=tampered.situation_id,
        )
        with pytest.raises(VerificationRefused) as exc_info:
            p6s._verify(handoff, p6s._readers(), ReplayStore(), AuditLog())
        assert exc_info.value.code == VERIFY_CASE_SKEW

    def test_5_high_confidence_keeps_order(self) -> None:
        """Arrange 0.99 confidence; Assert evaluate precedes admit, kind stable."""
        order: list[str] = []
        ctx = _context()
        disc = discover(_request(ctx), context=ctx)
        assert disc.success is True
        rea = reason(disc, context=ctx)
        assert rea.success is True
        br = brief(rea, context=ctx)
        assert br.success is True
        low = rea.model_copy(update={"confidence": 0.10})
        high = rea.model_copy(update={"confidence": 0.99})
        gate = ControlPlaneGate()
        verdict = evaluate("E", "E1", context=ctx, discovery=disc, reasoning=rea, brief=br)
        order.append("evaluate")
        assert verdict == "CONTAINED"
        low_res = gate.admit(context=ctx, discovery=disc, reasoning=low, brief=br)
        order.append("admit-low")
        high_res = gate.admit(context=ctx, discovery=disc, reasoning=high, brief=br)
        order.append("admit-high")
        assert low_res.kind == high_res.kind == "P6_HANDOFF"
        assert order == ["evaluate", "admit-low", "admit-high"]

    def test_6_wrong_tenant_situation_blocked(self, p6_spies: list[str]) -> None:
        """Arrange cross-situation bundle; Assert BLOCKED before any P6 call."""
        ctx = _context()
        other_ctx = _context(situation_id="sit-other-999")
        cross = discover(_request(other_ctx), context=other_ctx)
        assert cross.success is True
        res = ControlPlaneGate().admit(
            context=ctx,
            discovery=cross,
            reasoning=reason(discover(_request(ctx), context=ctx), context=ctx),
            brief=brief(
                reason(discover(_request(ctx), context=ctx), context=ctx),
                context=ctx,
            ),
        )
        assert res.kind == "BLOCKED"
        assert res.reason == "SCOPE_MISMATCH"
        with pytest.raises(ValueError, match="company_id"):
            DiscoveryRequest(
                situation_id=ctx.situation_id,
                company_id="otherco",
                now=ctx.now,
                allowed_evidence_ids=("ev-ledger-001",),
                objective="Cross-tenant attempt.",
                allowed_capabilities=(AgentCapability.READ,),
            )
        assert p6_spies == []
