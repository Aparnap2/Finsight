"""Phase 1 first executable slice (P6): fixture to verified report, no new engines.

Chains ONLY frozen production paths through test-local doubles (in-memory
SQLite engine, repo spy, dict proposal lookup, deterministic mock adapter,
pure reader lambdas, in-memory replay store and audit log):

fixture -> build_proposal -> decide (G1-G6) -> mint/verify_authorization ->
ApprovalService.decide -> execution_policy.check -> Executor.run ->
verify_execution (R1/R2/R3, minter inside) -> VERIFIED report.

One happy-path test proves operation ORDER via a stage recorder plus
idempotency-ledger, re-read-evidence, and tenant/situation/evidence
preservation; eighteen failure tests prove typed refusal on every break.
"""

from __future__ import annotations

import dataclasses
import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool

from finance.accounting.mock import MockQuickBooksAdapter
from finance.approval.authorization import mint_authorization, verify_authorization
from finance.approval.decision import (
    DecisionOutcome,
    ProposalSnapshot,
    compute_proposal_hash,
    decide,
)
from finance.approval.refusals import ApprovalRefused, RefusalCode
from finance.approvals.decision import ApprovalCommand, ApprovalDecision, ApprovalRecord
from finance.approvals.service import ApprovalService
from finance.domain.verification import VerificationVerdict
from finance.exceptions.aggregate import ExceptionAggregate
from finance.exceptions.errors import ConcurrencyConflictError, IllegalTransitionError
from finance.exceptions.repository import ExceptionRepository
from finance.exceptions.states import ExceptionState
from finance.execution.executor import Executor
from finance.legacy_execution.handoff import ExecutionHandoff
from finance.policy.execution_policy import check as policy_check
from finance.proposals.builder import ProposalBuildError, build_proposal
from finance.proposals.proposal import Proposal, ProposalAction
from finance.reconciliation.models import ExceptionCode, PaymentRecord, PaymentStatus
from finance.verification.audit import AuditLog
from finance.verification.orchestrator import (
    R1Observation,
    R2Observation,
    R3Observation,
    VerificationRefused,
    verify_execution,
)
from finance.verification.reason_codes import (
    VERIFY_CASE_SKEW,
    VERIFY_CONTROL_SKEW,
    VERIFY_COUNT_SKEW,
    VERIFY_DIGEST_MISMATCH,
    VERIFY_PREFIX_ESCAPE,
    VERIFY_TOLERANCE_EXCEEDED,
    VERIFY_UNAUTHORIZED_EXECUTION,
)
from finance.verification.replay import ReplayStore
from shared.safety.idempotency import IdempotencyStore

_T = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
_TENANT = "tenant-acme"
_EXC = "exc-slice-1"
_EVIDENCE = ("ev-1", "ev-2")
_THRESHOLD = Decimal("20000.00")
_GROSS = Decimal("50000.00")
_REFUND = Decimal("15000.00")

_SITUATION = "FS-2026-0916-00301"
_BATCH = "LEGACY-20260916-0301"
_ACTION = "REPROCESS_LEGACY_RECORD"
_ACCOUNT = "4812"
_M_EVIDENCE = ("ev-1", "ev-2")
_HYPOTHESIS = "hyp-fs301-root-cause"
_PROPOSER = "anita"
_MANAGER = "meera"
_PROOF = "slack-sig-fs301-ok"
_DECIDED_AT = datetime(2026, 9, 16, 10, 0, 0, tzinfo=UTC)
_ISSUED_AT = datetime(2026, 9, 16, 11, 0, 0, tzinfo=UTC)
_EXPIRES_AT = datetime(2026, 9, 23, 11, 0, 0, tzinfo=UTC)
_SEAL = b"p6-slice-test-seal-key-301"

_PRIOR = Decimal("982500.00")
_ACCEPTED = Decimal("10000.00")
_LEGACY_AFTER = Decimal("992500.00")
_EXPECTED = Decimal("1000000.00")
_PENDING = Decimal("7500.00")
_ZERO_DP = Decimal("0.00")
_R1_BYTES = b"slice-r1-result-fs301"


def _engine() -> Engine:
    """Build a shared in-memory SQLite engine (the only store doubles use)."""
    return create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )


class _RepoSpy:
    """Test-local repo double: delegates to the real repository, logs gets."""

    def __init__(self, repo: ExceptionRepository, log: list[str]) -> None:
        """Bind the delegate repository and the shared stage log."""
        self._repo = repo
        self._log = log

    def get(self, exception_id: str) -> ExceptionAggregate | None:
        """Return the aggregate, recording the read for order evidence."""
        self._log.append(f"repo.get:{exception_id}")
        return self._repo.get(exception_id)


def _records() -> tuple[PaymentRecord, PaymentRecord]:
    """Processor net 35k vs stale ledger net 50k: a 15k refund-lag diff."""
    first = PaymentRecord(
        payment_id="pay-proc-301",
        provider="stripe",
        provider_event_id="evt-proc-301",
        idempotency_key="idem-proc-301",
        gross=_GROSS,
        fee=Decimal("0.00"),
        refund=_REFUND,
        net=Decimal("35000.00"),
        currency="USD",
        status=PaymentStatus.PARTIALLY_REFUNDED,
        occurred_at=_T,
        tenant_id=_TENANT,
    )
    second = PaymentRecord(
        payment_id="pay-ledger-301",
        provider="stripe",
        provider_event_id="evt-ledger-301",
        idempotency_key="idem-ledger-301",
        gross=_GROSS,
        fee=Decimal("0.00"),
        refund=Decimal("0.00"),
        net=_GROSS,
        currency="USD",
        status=PaymentStatus.SETTLED,
        occurred_at=_T,
        tenant_id=_TENANT,
    )
    return (first, second)


def _verified_snapshot(repo: ExceptionRepository, exc_id: str) -> ExceptionAggregate:
    """Drive one aggregate to EVIDENCE_VERIFIED with the sealed evidence set."""
    agg = ExceptionAggregate.create(
        exception_id=exc_id,
        tenant_id=_TENANT,
        reconciliation_result_id=f"recon-{exc_id}",
        exception_type=ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG,
        severity="HIGH",
        created_at=_T,
    )
    repo.create(agg, actor="seeder")
    snapshot = repo.get(exc_id)
    assert snapshot is not None
    snapshot = repo.apply(snapshot, ExceptionState.INVESTIGATING, actor="t")
    snapshot = repo.apply(
        snapshot, ExceptionState.EVIDENCE_READY, actor="t", evidence_ids=list(_EVIDENCE)
    )
    return repo.apply(snapshot, ExceptionState.EVIDENCE_VERIFIED, actor="t")


def _seed_awaiting(
    repo: ExceptionRepository, exc_id: str = _EXC
) -> tuple[ExceptionAggregate, Proposal]:
    """Drive one aggregate to AWAITING_APPROVAL and draft its 15k proposal."""
    snapshot = _verified_snapshot(repo, exc_id)
    proposal = build_proposal(snapshot, _records(), ("ev-1",))
    assert proposal.amount == Decimal("15000.00")
    snapshot = repo.apply(
        snapshot, ExceptionState.PROPOSED, actor="t", proposal_id=proposal.proposal_id
    )
    snapshot = repo.apply(snapshot, ExceptionState.AWAITING_APPROVAL, actor="t")
    return snapshot, proposal


def _cmd(
    snapshot: ExceptionAggregate,
    proposal: Proposal,
    *,
    key: str,
    decision: ApprovalDecision = ApprovalDecision.APPROVED,
) -> ApprovalCommand:
    """Build a well-formed approval command pinning the live proposal triple."""
    return ApprovalCommand(
        exception_id=snapshot.exception_id,
        proposal_id=proposal.proposal_id,
        proposal_version=proposal.version,
        proposal_content_hash=proposal.content_hash,
        approver_id="approver-1",
        decision=decision,
        idempotency_key=key,
        expected_state_version=snapshot.state_version,
    )


def _m_hash(amount: Decimal = Decimal("10000")) -> str:
    """Compute the canonical meridian proposal hash for the slice shape."""
    return compute_proposal_hash(
        situation_id=_SITUATION,
        action=_ACTION,
        amount=amount,
        account_code=_ACCOUNT,
        evidence_refs=_M_EVIDENCE,
        hypothesis_ref=_HYPOTHESIS,
        proposal_version=1,
    )


def _m_snapshot(amount: Decimal = Decimal("10000")) -> ProposalSnapshot:
    """Build a consistent meridian proposal snapshot (hash matches fields)."""
    return ProposalSnapshot(
        situation_id=_SITUATION,
        company_id="meridian",
        action=_ACTION,
        amount=amount,
        account_code=_ACCOUNT,
        evidence_refs=_M_EVIDENCE,
        hypothesis_ref=_HYPOTHESIS,
        proposal_hash=_m_hash(amount),
        proposal_version=1,
        proposer_id=_PROPOSER,
        is_legacy=True,
        period="2026-09",
    )


def _m_decide(snapshot: ProposalSnapshot) -> Any:
    """Run the frozen G1-G6 gate with manager authority on the slice case."""
    return decide(
        snapshot,
        decision_id="dec-fs301-v1",
        approver=_MANAGER,
        approver_role="manager",
        auth_proof=_PROOF,
        outcome=DecisionOutcome.APPROVE,
        decided_at=_DECIDED_AT,
        actor_situation_id=_SITUATION,
        closed_periods=("2026-08",),
    )


def _m_mint(decision: Any, snapshot: ProposalSnapshot) -> Any:
    """Mint the frozen G7 token bound to the slice execution identity."""
    return mint_authorization(
        decision,
        action=snapshot.action,
        amount_exact=snapshot.amount,
        account_code=snapshot.account_code,
        issued_at=_ISSUED_AT,
        expires_at=_EXPIRES_AT,
        seal_key=_SEAL,
        scope_batch=None,
        proposal=snapshot,
    )


def _handoff(
    *,
    execution_id: str,
    authorization_id: str,
    result_sha: str,
    company_id: str = "meridian",
    situation_id: str = _SITUATION,
) -> ExecutionHandoff:
    """Build a recorded §8 handoff claiming the 10k ACCEPTED execution."""
    return ExecutionHandoff(
        execution_id=execution_id,
        authorization_id=authorization_id,
        proposal_hash=_m_hash(),
        proposal_version=1,
        company_id=company_id,
        situation_id=situation_id,
        batch_id=_BATCH,
        s3_outbound_key=f"meridian/{_BATCH}/CORRECTION_20260916_301.DAT",
        outbound_sha256="0" * 64,
        control_total=_ACCEPTED,
        record_count=1,
        accepted_count=1,
        rejected_count=0,
        accepted_total=_ACCEPTED,
        rejected_total=_ZERO_DP,
        result_key=f"meridian/{_BATCH}/RESULT_20260916_301.DAT",
        result_sha256=result_sha,
        outcome="ACCEPTED",
        unknown_flag=False,
        recorded_at=_T,
    )


def _r1_sha() -> str:
    """Return the digest the honest R1 fake will report for its bytes."""
    return hashlib.sha256(_R1_BYTES).hexdigest()


def _readers(
    *,
    r1_bytes: bytes = _R1_BYTES,
    accepted: Decimal = _ACCEPTED,
    prior: Decimal = _PRIOR,
    legacy_after: Decimal = _LEGACY_AFTER,
    expected: Decimal = _EXPECTED,
    pending: Decimal = _PENDING,
    residual: Decimal = _ZERO_DP,
) -> tuple[Any, Any, Any, list[str]]:
    """Build deterministic R1/R2/R3 fakes plus their invocation log."""
    calls: list[str] = []

    def read_result(handoff: ExecutionHandoff) -> R1Observation:
        calls.append("R1")
        return R1Observation(
            result_bytes=r1_bytes,
            result_sha256=hashlib.sha256(r1_bytes).hexdigest(),
            observed_at=_T,
        )

    def read_legacy(handoff: ExecutionHandoff) -> R2Observation:
        calls.append("R2")
        return R2Observation(
            accepted_total=accepted,
            prior_total=prior,
            legacy_after=legacy_after,
            observed_at=_T,
        )

    def read_expectation(handoff: ExecutionHandoff) -> R3Observation:
        calls.append("R3")
        return R3Observation(expected=expected, pending=pending, residual=residual, observed_at=_T)

    return read_result, read_legacy, read_expectation, calls


def _verify(
    handoff: ExecutionHandoff,
    readers: tuple[Any, Any, Any, list[str]],
    store: ReplayStore,
    log: AuditLog,
) -> Any:
    """Run the frozen single-pass verifier against the slice doubles."""
    read_result, read_legacy, read_expectation = readers[0], readers[1], readers[2]
    return verify_execution(
        handoff=handoff,
        read_result=read_result,
        read_legacy=read_legacy,
        read_expectation=read_expectation,
        checked_at=_T,
        now=_T,
        store=store,
        audit_log=log,
        for_situation_id=_SITUATION,
    )


def _fresh_record(
    engine: Engine, repo: ExceptionRepository, exc_id: str, key: str
) -> ApprovalRecord:
    """Approve one awaiting aggregate on a side key for policy fixtures."""
    snapshot, proposal = _seed_awaiting(repo, exc_id)
    return ApprovalService(engine, amount_threshold=_THRESHOLD).decide(
        _cmd(snapshot, proposal, key=key), repo, {proposal.proposal_id: proposal}
    )


class TestExecutableSliceHappy:
    """Happy path: every stage in order, one VERIFIED report, nothing else."""

    def test_fixture_to_verified_report_in_order(self) -> None:
        """Arrange fixture; Act full chain; Assert order, ledger, evidence."""
        stages: list[str] = []
        engine = _engine()
        repo = ExceptionRepository(engine)
        spy = _RepoSpy(repo, stages)
        service = ApprovalService(engine, amount_threshold=_THRESHOLD)

        det_snap = _verified_snapshot(repo, "exc-det")
        first = build_proposal(det_snap, _records(), ("ev-1",))
        second = build_proposal(det_snap, _records(), ("ev-1",))
        assert first.content_hash == second.content_hash  # deterministic fixture

        snapshot, proposal = _seed_awaiting(repo)
        stages.append("builder")
        assert proposal.action is ProposalAction.CREATE_CORRECTING_ENTRY
        assert proposal.amount == Decimal("15000.00")
        assert proposal.requires_hitl is True

        m_snapshot = _m_snapshot()
        g6 = _m_decide(m_snapshot)
        stages.append("decide")
        assert g6.outcome is DecisionOutcome.APPROVE
        assert g6.situation_id == _SITUATION

        token = _m_mint(g6, m_snapshot)
        stages.append("mint_authorization")
        verify_authorization(
            token,
            company_id="meridian",
            situation_id=_SITUATION,
            proposal_hash=token.proposal_hash,
            proposal_version=token.proposal_version,
            action=_ACTION,
            amount_exact=Decimal("10000"),
            account_code=_ACCOUNT,
            scope_batch=None,
            at=_ISSUED_AT,
            seal_key=_SEAL,
        )
        stages.append("verify_authorization")

        record = service.decide(
            _cmd(snapshot, proposal, key="slice-appr-1"), spy, {proposal.proposal_id: proposal}
        )
        stages.append("approval_service")
        assert record.decision is ApprovalDecision.APPROVED
        approved = repo.get(_EXC)
        assert approved is not None
        assert approved.state is ExceptionState.APPROVED
        assert approved.execution_id is None

        verdict = policy_check(proposal, record)
        stages.append("policy")
        assert verdict.allowed is True

        adapter = MockQuickBooksAdapter()
        executor = Executor(adapter, engine)
        result = executor.run(approved, proposal, record, "slice-exec-1")
        stages.append("execution")
        assert str(result.result) == "SUCCEEDED"
        assert str(result.post_verify) == "MATCHED"
        assert adapter.entry_count == 1

        handoff = _handoff(
            execution_id=str(result.execution_id),
            authorization_id=token.authorization_id,
            result_sha=_r1_sha(),
        )
        readers = _readers()
        store, audit = ReplayStore(), AuditLog()
        report = _verify(handoff, readers, store, audit)
        stages.append("verification")
        assert report.verdict is VerificationVerdict.VERIFIED
        stages.append("mint_report")

        order = [s for s in stages if not s.startswith("repo.get")]
        assert order == [
            "builder",
            "decide",
            "mint_authorization",
            "verify_authorization",
            "approval_service",
            "policy",
            "execution",
            "verification",
            "mint_report",
        ]
        assert readers[3] == ["R1", "R2", "R3"]
        assert len(audit) == 1
        entry = audit.entries[0]
        assert entry.outcome == "VERIFIED"
        assert len(entry.reread_digests) == 3  # R1/R2/R3 re-read evidence present
        assert entry.report_hash is not None
        assert IdempotencyStore(engine).seen("slice-exec-1") is True
        assert approved.tenant_id == _TENANT  # tenant preserved into execution
        assert report.situation_id == _SITUATION  # situation preserved to report
        assert report.execution_id == str(result.execution_id)
        assert "ev-1" in proposal.evidence_ids  # evidence preserved builder side
        assert "ev-1" in m_snapshot.evidence_refs  # evidence preserved meridian side
        assert store.lookup(report.execution_id) is not None


class TestExecutableSliceFailures:
    """Failure breaks: each yields a typed refusal, never a plausible success."""

    def test_01_policy_rejection_over_threshold(self) -> None:
        """Arrange 15k proposal under a 1.00 ceiling; Assert DENY, no approval."""
        engine = _engine()
        repo = ExceptionRepository(engine)
        snapshot, proposal = _seed_awaiting(repo)
        record = _fresh_record(engine, repo, "exc-f01-side", "f01-side")
        verdict = policy_check(proposal, record, amount_threshold=Decimal("1.00"))
        assert verdict.allowed is False
        assert verdict.decision == "DENY"
        tiny = ApprovalService(engine, amount_threshold=Decimal("1.00"))
        with pytest.raises(IllegalTransitionError, match="policy denied"):
            tiny.decide(_cmd(snapshot, proposal, key="f01"), repo, {proposal.proposal_id: proposal})

    def test_02_approval_rejection_records_rejected(self) -> None:
        """Arrange REJECT command; Assert REJECTED record, nothing scheduled."""
        engine = _engine()
        repo = ExceptionRepository(engine)
        snapshot, proposal = _seed_awaiting(repo)
        record = ApprovalService(engine, amount_threshold=_THRESHOLD).decide(
            _cmd(snapshot, proposal, key="f02", decision=ApprovalDecision.REJECTED),
            repo,
            {proposal.proposal_id: proposal},
        )
        assert record.decision is ApprovalDecision.REJECTED
        current = repo.get(_EXC)
        assert current is not None
        assert current.state is ExceptionState.REJECTED
        assert current.execution_id is None

    def test_03_missing_authorization_forged_seal(self) -> None:
        """Arrange token verified under the wrong seal; Assert TOKEN_FORGED."""
        token = _m_mint(_m_decide(_m_snapshot()), _m_snapshot())
        with pytest.raises(ApprovalRefused) as exc_info:
            verify_authorization(
                token,
                company_id="meridian",
                situation_id=_SITUATION,
                proposal_hash=token.proposal_hash,
                proposal_version=token.proposal_version,
                action=_ACTION,
                amount_exact=Decimal("10000"),
                account_code=_ACCOUNT,
                scope_batch=None,
                at=_ISSUED_AT,
                seal_key=b"wrong-seal-key",
            )
        assert exc_info.value.code == RefusalCode.TOKEN_FORGED

    def test_04_execution_failure_unbookable_action(self) -> None:
        """Arrange duplicate (void) approval; Assert FAILED/MISMATCH, no write."""
        engine = _engine()
        repo = ExceptionRepository(engine)
        agg = ExceptionAggregate.create(
            exception_id="exc-f04",
            tenant_id=_TENANT,
            reconciliation_result_id="recon-exc-f04",
            exception_type=ExceptionCode.DUPLICATE_LEDGER_ENTRY,
            severity="HIGH",
            created_at=_T,
        )
        repo.create(agg, actor="seeder")
        snap = repo.get("exc-f04")
        assert snap is not None
        snap = repo.apply(snap, ExceptionState.INVESTIGATING, actor="t")
        snap = repo.apply(
            snap, ExceptionState.EVIDENCE_READY, actor="t", evidence_ids=list(_EVIDENCE)
        )
        snap = repo.apply(snap, ExceptionState.EVIDENCE_VERIFIED, actor="t")
        leg = PaymentRecord(
            payment_id="pay-dup-1",
            provider="stripe",
            provider_event_id="evt-dup-1",
            idempotency_key="idem-dup-1",
            gross=Decimal("10000.00"),
            fee=Decimal("2000.00"),
            refund=Decimal("0.00"),
            net=Decimal("8000.00"),
            currency="USD",
            status=PaymentStatus.SETTLED,
            occurred_at=_T,
            tenant_id=_TENANT,
        )
        dup = build_proposal(snap, (leg,), ("ev-1",))
        assert dup.action is ProposalAction.VOID_DUPLICATE
        snap = repo.apply(snap, ExceptionState.PROPOSED, actor="t", proposal_id=dup.proposal_id)
        snap = repo.apply(snap, ExceptionState.AWAITING_APPROVAL, actor="t")
        record = ApprovalService(engine, amount_threshold=_THRESHOLD).decide(
            _cmd(snap, dup, key="f04"), repo, {dup.proposal_id: dup}
        )
        approved = repo.get("exc-f04")
        assert approved is not None
        adapter = MockQuickBooksAdapter()
        result = Executor(adapter, engine).run(approved, dup, record, "f04-exec")
        assert str(result.result) == "FAILED"
        assert str(result.post_verify) == "MISMATCH"
        assert adapter.entry_count == 0
        closed = repo.get("exc-f04")
        assert closed is not None
        assert closed.state is ExceptionState.ESCALATED

    def test_05_verification_failure_tolerance_exceeded(self) -> None:
        """Arrange residual 600 over the 100 bound; Assert FAILED, code kept."""
        handoff = _handoff(
            execution_id="exec-f05", authorization_id="authz-f05", result_sha=_r1_sha()
        )
        readers = _readers(expected=Decimal("1000600.00"), residual=Decimal("600.00"))
        store, audit = ReplayStore(), AuditLog()
        report = _verify(handoff, readers, store, audit)
        assert report.verdict is VerificationVerdict.FAILED
        assert audit.entries[0].reason_code == VERIFY_TOLERANCE_EXCEEDED

    def test_06_insufficient_budget_over_tier(self) -> None:
        """Arrange manager decision on 60k non-legacy; Assert OVER_TIER_AMOUNT."""
        snapshot = _m_snapshot(Decimal("60000")).model_copy(update={"is_legacy": False})
        with pytest.raises(ApprovalRefused) as exc_info:
            _m_decide(snapshot)
        assert exc_info.value.code == RefusalCode.OVER_TIER_AMOUNT

    def test_07_duplicate_idempotent_single_effect(self) -> None:
        """Arrange same keys replayed; Assert one approval row, one booking."""
        engine = _engine()
        repo = ExceptionRepository(engine)
        snapshot, proposal = _seed_awaiting(repo)
        service = ApprovalService(engine, amount_threshold=_THRESHOLD)
        lookup = {proposal.proposal_id: proposal}
        first = service.decide(_cmd(snapshot, proposal, key="f07"), repo, lookup)
        current = repo.get(_EXC)
        assert current is not None
        replay = service.decide(_cmd(current, proposal, key="f07"), repo, lookup)
        assert replay.approval_id == first.approval_id
        assert len(service.get_for_exception(_EXC)) == 1
        adapter = MockQuickBooksAdapter()
        executor = Executor(adapter, engine)
        approved = repo.get(_EXC)
        assert approved is not None
        out1 = executor.run(approved, proposal, first, "f07-exec")
        out2 = executor.run(approved, proposal, first, "f07-exec")
        assert out1.execution_id == out2.execution_id
        assert adapter.entry_count == 1

    def test_08_r1_violation_digest_mismatch(self) -> None:
        """Arrange handoff digest disagreeing with fresh bytes; Assert FAILED."""
        handoff = _handoff(
            execution_id="exec-f08", authorization_id="authz-f08", result_sha="f" * 64
        )
        readers = _readers()
        store, audit = ReplayStore(), AuditLog()
        report = _verify(handoff, readers, store, audit)
        assert report.verdict is VerificationVerdict.FAILED
        assert audit.entries[0].reason_code == VERIFY_DIGEST_MISMATCH
        assert readers[3] == ["R1"]  # downstream readers never ran

    def test_09_r2_violation_count_skew(self) -> None:
        """Arrange reader accepted 9k vs handoff 10k; Assert COUNT_SKEW FAILED."""
        handoff = _handoff(
            execution_id="exec-f09", authorization_id="authz-f09", result_sha=_r1_sha()
        )
        readers = _readers(accepted=Decimal("9000.00"))
        store, audit = ReplayStore(), AuditLog()
        report = _verify(handoff, readers, store, audit)
        assert report.verdict is VerificationVerdict.FAILED
        assert audit.entries[0].reason_code == VERIFY_COUNT_SKEW

    def test_10_r3_violation_control_skew(self) -> None:
        """Arrange prior breaking the control equation; Assert CONTROL_SKEW."""
        handoff = _handoff(
            execution_id="exec-f10", authorization_id="authz-f10", result_sha=_r1_sha()
        )
        readers = _readers(prior=Decimal("900000.00"))
        store, audit = ReplayStore(), AuditLog()
        report = _verify(handoff, readers, store, audit)
        assert report.verdict is VerificationVerdict.FAILED
        assert audit.entries[0].reason_code == VERIFY_CONTROL_SKEW

    def test_11_malformed_input(self) -> None:
        """Arrange blank key and mistyped legs; Assert ValueError/BuildError."""
        engine = _engine()
        repo = ExceptionRepository(engine)
        snapshot, proposal = _seed_awaiting(repo)
        with pytest.raises(ValueError, match="idempotency_key"):
            _cmd(snapshot, proposal, key="   ")
        verified = _verified_snapshot(repo, "exc-f11")
        with pytest.raises(ProposalBuildError):
            build_proposal(verified, ("not-a-record",), ("ev-1",))  # type: ignore[arg-type]

    def test_12_missing_required_context(self) -> None:
        """Arrange decision with no auth proof; Assert UNAUTHENTICATED_ACTOR."""
        with pytest.raises(ApprovalRefused) as exc_info:
            decide(
                _m_snapshot(),
                decision_id="dec-f12",
                approver=_MANAGER,
                approver_role="manager",
                auth_proof=None,
                outcome=DecisionOutcome.APPROVE,
                decided_at=_DECIDED_AT,
                actor_situation_id=_SITUATION,
                closed_periods=("2026-08",),
            )
        assert exc_info.value.code == RefusalCode.UNAUTHENTICATED_ACTOR

    def test_13_wrong_tenant(self) -> None:
        """Arrange legs from another tenant; Assert cross-tenant refusal."""
        engine = _engine()
        repo = ExceptionRepository(engine)
        verified = _verified_snapshot(repo, "exc-f13")
        legs = _records()
        drifted = dataclasses.replace(legs[1], tenant_id="tenant-other")
        with pytest.raises(ProposalBuildError, match="[Tt]enant"):
            build_proposal(verified, (legs[0], drifted), ("ev-1",))

    def test_14_stale_context(self) -> None:
        """Arrange decision against a stale version; Assert version conflict."""
        engine = _engine()
        repo = ExceptionRepository(engine)
        snapshot, proposal = _seed_awaiting(repo)
        stale = ApprovalCommand(
            exception_id=snapshot.exception_id,
            proposal_id=proposal.proposal_id,
            proposal_version=proposal.version,
            proposal_content_hash=proposal.content_hash,
            approver_id="approver-1",
            decision=ApprovalDecision.APPROVED,
            idempotency_key="f14",
            expected_state_version=snapshot.state_version - 1,
        )
        with pytest.raises(ConcurrencyConflictError):
            ApprovalService(engine, amount_threshold=_THRESHOLD).decide(
                stale, repo, {proposal.proposal_id: proposal}
            )

    def test_15_retry_exhaustion(self) -> None:
        """Arrange endless transient 5xx; Assert 3 same-key writes, FAILED."""
        engine = _engine()
        repo = ExceptionRepository(engine)
        snapshot, proposal = _seed_awaiting(repo, "exc-f15")
        record = ApprovalService(engine, amount_threshold=_THRESHOLD).decide(
            _cmd(snapshot, proposal, key="f15-appr"), repo, {proposal.proposal_id: proposal}
        )
        approved = repo.get("exc-f15")
        assert approved is not None
        adapter = MockQuickBooksAdapter(transient_failures={"f15-exec": 99})
        result = Executor(adapter, engine).run(approved, proposal, record, "f15-exec")
        assert str(result.result) == "FAILED"
        assert str(result.post_verify) == "MISMATCH"
        writes = [c for c in adapter.calls if c.key == "f15-exec"]
        assert len(writes) == 3  # bounded retries, same key, then fail closed

    def test_16_missing_authorization_binding_refuses_mint(self) -> None:
        """Arrange handoff without authorization; Assert UNAUTHORIZED refusal."""
        valid = _handoff(
            execution_id="exec-f16", authorization_id="authz-f16", result_sha=_r1_sha()
        )
        handoff = ExecutionHandoff.model_construct(**{**valid.model_dump(), "authorization_id": ""})
        readers = _readers()
        with pytest.raises(VerificationRefused) as exc_info:
            _verify(handoff, readers, ReplayStore(), AuditLog())
        assert exc_info.value.code == VERIFY_UNAUTHORIZED_EXECUTION

    def test_17_wrong_company_prefix_escape(self) -> None:
        """Arrange non-meridian handoff; Assert PREFIX_ESCAPE, readers idle."""
        handoff = _handoff(
            execution_id="exec-f17",
            authorization_id="authz-f17",
            result_sha=_r1_sha(),
            company_id="acme",
        )
        readers = _readers()
        with pytest.raises(VerificationRefused) as exc_info:
            _verify(handoff, readers, ReplayStore(), AuditLog())
        assert exc_info.value.code == VERIFY_PREFIX_ESCAPE
        assert readers[3] == []

    def test_18_case_skew_refuses_cross_case_replay(self) -> None:
        """Arrange handoff bound to another case; Assert CASE_SKEW refusal."""
        handoff = _handoff(
            execution_id="exec-f18",
            authorization_id="authz-f18",
            result_sha=_r1_sha(),
            situation_id="FS-2026-0916-00999",
        )
        readers = _readers()
        with pytest.raises(VerificationRefused) as exc_info:
            _verify(handoff, readers, ReplayStore(), AuditLog())
        assert exc_info.value.code == VERIFY_CASE_SKEW
        assert readers[3] == []
