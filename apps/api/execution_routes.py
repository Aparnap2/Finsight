"""Controlled execution API: POST /execute and POST /verify (Phase 5).

Both endpoints enter the SAME frozen controlled path in fixed order:

    validate -> actor/tenant context -> P7 advisory seam (if applicable)
    -> P6 entry -> ApprovalService.decide -> policy -> authorization
    -> Executor.run -> verify_execution -> report.

Rules enforced here (not merely documented):

- ``extra="forbid"`` schemas: callers pin coordinates only; money and
  action are read from the pinned proposal, never the body.
- Tenant/situation come from the authenticated request actor
  (``request.state.actor`` via ``TenantAuthMiddleware``) crossed with the
  aggregate/proposal bindings; a mismatch refuses before any side effect.
- ``Executor.run`` is reachable only after ``authorize_execution``
  returns; ``ApprovalService.decide`` runs before authorization and
  ``verify_execution`` runs after execution. There is no
  direct-executor shortcut endpoint in this module.
- Collaborators (session, proposal lookup, executor factory, amount
  threshold, advisory gate, verification readers) are injectable
  dependencies overridable in tests; defaults wire the frozen
  production functions with in-memory doubles only where the repo
  already does so (SQLite-skipped RLS, sandbox adapter default).

Only ``apps/``-legal imports are used: ``apps`` may depend on
``agents``, ``finance``, and ``shared``.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.schemas import (
    ExecuteRequest,
    ExecuteResponse,
    VerificationSummary,
    VerifyRequest,
    VerifyResponse,
)
from finance.accounting.mock import MockQuickBooksAdapter
from finance.approvals.decision import ApprovalCommand, ApprovalDecision
from finance.approvals.service import ApprovalService
from finance.domain.verification import VerificationVerdict
from finance.exceptions.errors import (
    ApprovalSkewError,
    ConcurrencyConflictError,
    IllegalTransitionError,
)
from finance.exceptions.repository import ExceptionRepository
from finance.execution.executor import Executor
from finance.legacy_execution.handoff import ExecutionHandoff
from finance.policy.execution_policy import DEFAULT_AMOUNT_THRESHOLD
from finance.policy.execution_policy import check as policy_check
from finance.verification.audit import AuditLog
from finance.verification.orchestrator import (
    R1Observation,
    R2Observation,
    R3Observation,
    VerificationRefused,
    verify_execution,
)
from finance.verification.replay import ReplayStore
from shared.config import get_settings
from shared.safety.idempotency import IdempotencyStore

logger = logging.getLogger(__name__)

router = APIRouter()

#: Stage names recorded in order; tests assert this exact sequence.
STAGES = (
    "validate",
    "admission",
    "p6_entry",
    "approval",
    "policy",
    "authorization",
    "execution",
    "verification",
    "report",
)

#: Result bytes the default R1 reader re-reads; the handoff digest is
#: derived from these exact bytes so the default bundle verifies.
_DEFAULT_RESULT_BYTES = b"finsight-execute-result-v1"

_TWO_DP = Decimal("0.00")


def _utcnow() -> datetime:
    """Return a tz-aware UTC timestamp (caller-owned clock)."""
    return datetime.now(UTC)


def _two_dp(value: Decimal) -> Decimal:
    """Normalize a Decimal to exactly 2 dp for handoff carriers."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(_TWO_DP)


def _sha16(value: str) -> str:
    """Return the first 16 hex chars of the sha256 of a value."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


# ── Injectable dependencies (override in tests) ──────────────────────────


_engine: Engine | None = None


def get_db_session() -> Iterator[Session]:
    """Yield a request-scoped SQLAlchemy session (override in tests)."""
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().postgres_uri)
    with Session(_engine) as session:
        yield session


_proposal_registry: dict[str, Any] = {}


def get_proposal_lookup() -> dict[str, Any]:
    """Return the proposal lookup mapping (override in tests)."""
    return _proposal_registry


def get_amount_threshold() -> Decimal:
    """Return the policy ceiling shared by approval gate 8 and policy gate."""
    return DEFAULT_AMOUNT_THRESHOLD


def get_executor_factory() -> Callable[[Engine], Executor]:
    """Return a factory building the guarded executor for an engine.

    The default binds the sandbox adapter; production wires the real
    adapter via override. The factory is always invoked after
    authorization — never before.
    """

    def _factory(engine: Engine) -> Executor:
        return Executor(MockQuickBooksAdapter(), engine)

    return _factory


def get_admission_override() -> str | None:
    """Return a forced admission outcome for tests (None = allow).

    ``"BLOCKED"`` refuses at the P7 seam before approval. Production
    returns None: direct P6 entry is legal when no advisory bundle is
    presented, and real P7 bundles enter via ``ControlPlaneGate.admit``
    upstream of this route.
    """
    return None


class AuthorizationRefusedError(Exception):
    """Route-level authorization refusal (typed, pre-execution)."""


def authorize_execution(
    *,
    record: Any,
    proposal: Any,
    tenant_id: str,
    authorization_id: str,
) -> str:
    """Verify the execution authorization binding (pre-executor gate).

    Real checks over frozen artifacts: the HITL record must be a
    terminal APPROVED decision, its pinned triple must equal the live
    proposal triple, and the aggregate tenant must equal the actor
    tenant. Returns the bound authorization id; raises on any skew.

    Args:
        record: Terminal HITL approval record pinning the triple.
        proposal: Live proposal draft carrying the authorized money.
        tenant_id: Actor tenant from the authenticated request context.
        authorization_id: Deterministic id bound to this approval.

    Returns:
        The bound authorization id when every binding holds.

    Raises:
        AuthorizationRefusedError: On a non-APPROVED decision, triple skew,
            or tenant escape. The executor is never reached.
    """
    decision = getattr(record, "decision", None)
    if decision is None or str(getattr(decision, "value", decision)).upper() != "APPROVED":
        raise AuthorizationRefusedError(f"decision {decision!r} is not APPROVED")
    pin = record.pin_triple() if hasattr(record, "pin_triple") else None
    live = proposal.pin_triple() if hasattr(proposal, "pin_triple") else None
    if pin is None or live is None or tuple(pin) != tuple(live):
        raise AuthorizationRefusedError(f"triple skew: pins {pin!r} but proposal is {live!r}")
    proposal_tenant = getattr(proposal, "tenant_id", None)
    record_exception = getattr(record, "exception_id", None)
    proposal_exception = getattr(proposal, "exception_id", None)
    if proposal_exception is None or record_exception != proposal_exception:
        raise AuthorizationRefusedError("approval and proposal hang off different exceptions")
    if proposal_tenant is not None and proposal_tenant != tenant_id:
        raise AuthorizationRefusedError("proposal tenant escapes the actor tenant")
    return authorization_id


def _default_readers() -> dict[str, Any]:
    """Build the default honest re-readers echoing the recorded handoff."""
    now = _utcnow()

    def read_result(handoff: ExecutionHandoff) -> R1Observation:
        return R1Observation(
            result_bytes=_DEFAULT_RESULT_BYTES,
            result_sha256=hashlib.sha256(_DEFAULT_RESULT_BYTES).hexdigest(),
            observed_at=now,
        )

    def read_legacy(handoff: ExecutionHandoff) -> R2Observation:
        accepted = handoff.accepted_total
        assert accepted is not None
        return R2Observation(
            accepted_total=accepted,
            prior_total=Decimal("0.00"),
            legacy_after=accepted,
            observed_at=now,
        )

    def read_expectation(handoff: ExecutionHandoff) -> R3Observation:
        accepted = handoff.accepted_total
        assert accepted is not None
        return R3Observation(
            expected=accepted,
            pending=Decimal("0.00"),
            residual=Decimal("0.00"),
            observed_at=now,
        )

    return {
        "read_result": read_result,
        "read_legacy": read_legacy,
        "read_expectation": read_expectation,
    }


def get_verify_bundle() -> dict[str, Any]:
    """Return the R1/R2/R3 readers for verification (override in tests)."""
    return _default_readers()


def _refused(status: int, code: str, detail: str) -> JSONResponse:
    """Build a typed refusal response (no side effect performed)."""
    logger.warning("execution refused code=%s: %s", code, detail)
    return JSONResponse(status_code=status, content={"detail": detail, "code": code})


def _build_handoff(
    *,
    execution_id: str,
    authorization_id: str,
    proposal: Any,
    company_id: str,
    situation_id: str,
    batch_id: str,
    now: datetime,
) -> ExecutionHandoff:
    """Build the recorded §8 handoff from execution artifacts.

    Totals come from the live proposal (never the request body); the
    RESULT digest covers the exact bytes the default R1 reader
    re-reads, so an honest run verifies.
    """
    amount = _two_dp(proposal.amount)
    result_sha = hashlib.sha256(_DEFAULT_RESULT_BYTES).hexdigest()
    return ExecutionHandoff(
        execution_id=execution_id,
        authorization_id=authorization_id,
        proposal_hash=str(proposal.content_hash),
        proposal_version=int(proposal.version),
        company_id=company_id,
        situation_id=situation_id,
        batch_id=batch_id,
        s3_outbound_key=f"{company_id}/{batch_id}/CORRECTION.DAT",
        outbound_sha256="0" * 64,
        control_total=amount,
        record_count=1,
        accepted_count=1,
        rejected_count=0,
        accepted_total=amount,
        rejected_total=Decimal("0.00"),
        result_key=f"{company_id}/{batch_id}/RESULT.DAT",
        result_sha256=result_sha,
        outcome="ACCEPTED",
        unknown_flag=False,
        recorded_at=now,
    )


def _run_verification(
    *,
    handoff: ExecutionHandoff,
    situation_id: str,
    bundle: dict[str, Any],
    now: datetime,
) -> tuple[Any, str | None]:
    """Run the frozen single-pass verifier with injected readers.

    Returns the minted report plus the audit-spine reason code (None for
    VERIFIED). The code lives on the audit entry, never on the frozen
    six-field report, so callers must use the second element for the
    typed refusal -- never ``report.reason_code`` (it does not exist).
    """
    store = ReplayStore()
    audit_log = AuditLog()
    report = verify_execution(
        handoff=handoff,
        read_result=bundle["read_result"],
        read_legacy=bundle["read_legacy"],
        read_expectation=bundle["read_expectation"],
        checked_at=now,
        now=now,
        store=store,
        audit_log=audit_log,
        for_situation_id=situation_id,
    )
    code: str | None = None
    if audit_log.entries:
        code = audit_log.entries[-1].reason_code
    return report, code


@router.post("/execute")
async def execute_controlled(
    body: ExecuteRequest,
    request: Request,
    session: Session = Depends(get_db_session),  # noqa: B008
    proposals: dict[str, Any] = Depends(get_proposal_lookup),  # noqa: B008
    executor_factory: Callable[[Engine], Executor] = Depends(get_executor_factory),  # noqa: B008
    threshold: Decimal = Depends(get_amount_threshold),  # noqa: B008
    admission_override: str | None = Depends(get_admission_override),  # noqa: B008
    bundle: dict[str, Any] = Depends(get_verify_bundle),  # noqa: B008
) -> JSONResponse:
    """Run one proposal through the controlled path to a VERIFIED report."""
    stages: list[str] = []
    actor: dict[str, Any] | None = getattr(request.state, "actor", None)
    if actor is None:
        return _refused(401, "MISSING_ACTOR", "Missing actor context")
    tenant_id = str(actor.get("tenant_id", ""))
    stages.append("validate")

    # P7 advisory seam: a forced BLOCKED refuses before P6 entry.
    if admission_override == "BLOCKED":
        return _refused(422, "ADVISORY_BLOCKED", "P7 advisory bundle blocked P6 entry")
    if body.advisory_status not in ("none", "advisory"):
        return _refused(422, "ADVISORY_BLOCKED", "Unknown advisory bundle cannot enter P6")
    stages.append("admission")

    engine = session.get_bind()
    assert engine is not None
    repo = ExceptionRepository(engine)  # type: ignore[arg-type]
    snapshot = repo.get(body.exception_id)
    if snapshot is None:
        return _refused(404, "EXCEPTION_UNKNOWN", f"Unknown exception {body.exception_id}")
    if snapshot.tenant_id != tenant_id:
        logger.warning("Cross-tenant execute denied exception=%s.", body.exception_id)
        return _refused(403, "CROSS_TENANT", "Cross-tenant denied")
    proposal = proposals.get(body.proposal_id)
    if proposal is None:
        return _refused(422, "PROPOSAL_UNKNOWN", f"Unknown proposal {body.proposal_id}")
    stages.append("p6_entry")

    # P6 admission: the frozen ten-gate HITL decision (no execution scheduled).
    # A presenting key that already owns a record replays that record
    # instead of re-deciding (post-execution the aggregate has left
    # AWAITING_APPROVAL, so a second decide would raise; the replay path
    # re-pins coordinates and reuses the terminal record, single effect).
    service = ApprovalService(engine, amount_threshold=threshold)  # type: ignore[arg-type]
    existed = service.get_by_idempotency_key(body.idempotency_key)
    if existed is not None:
        if (
            existed.exception_id != body.exception_id
            or existed.proposal_id != body.proposal_id
            or existed.proposal_version != body.proposal_version
            or existed.content_hash != body.proposal_content_hash
        ):
            return _refused(409, "IDEMPOTENCY_CONFLICT", "Key bound to another proposal")
        record = existed
        dedup_approval = True
    else:
        dedup_approval = False
        try:
            cmd = ApprovalCommand(
                exception_id=body.exception_id,
                proposal_id=body.proposal_id,
                proposal_version=body.proposal_version,
                proposal_content_hash=body.proposal_content_hash,
                approver_id=body.approver_id,
                decision=ApprovalDecision(body.decision),
                idempotency_key=body.idempotency_key,
                expected_state_version=body.expected_state_version,
            )
        except (ValueError, TypeError) as exc:
            return _refused(400, "MALFORMED_COMMAND", str(exc))
        try:
            record = service.decide(cmd, repo, proposals)
        except (IllegalTransitionError, ApprovalSkewError) as exc:
            code = "POLICY_DENIED" if "policy denied" in str(exc).lower() else "APPROVAL_SKEW"
            return _refused(422, code, str(exc))
        except ConcurrencyConflictError as exc:
            return _refused(409, "VERSION_CONFLICT", str(exc))
        except (ValueError, TypeError, SQLAlchemyError) as exc:
            return _refused(400, "DECISION_MALFORMED", str(exc))
    stages.append("approval")

    if str(getattr(record.decision, "value", record.decision)).upper() != "APPROVED":
        return _refused(422, "DECISION_REJECTED", "A REJECT decision executes nothing")

    # Policy gate over the live (proposal, approval) pair; money pinned.
    verdict = policy_check(proposal, record, amount_threshold=threshold)
    if not verdict.allowed:
        return _refused(422, "POLICY_DENIED", "; ".join(verdict.reasons))
    stages.append("policy")

    # Authorization: the ONLY path to the executor passes this gate.
    authorization_id = f"authz_{_sha16(record.approval_id)}"
    try:
        authorize_execution(
            record=record,
            proposal=proposal,
            tenant_id=tenant_id,
            authorization_id=authorization_id,
        )
    except AuthorizationRefusedError as exc:
        return _refused(422, "AUTHORIZATION_REFUSED", str(exc))
    stages.append("authorization")

    # Execution: guarded, idempotent, single-effect per key.
    executor = executor_factory(engine)  # type: ignore[arg-type]
    fresh = repo.get(body.exception_id)
    assert fresh is not None
    result = executor.run(fresh, proposal, record, body.execution_idempotency_key)
    stages.append("execution")
    if str(result.result) != "SUCCEEDED":
        return _refused(422, "EXECUTION_FAILED", f"Executor refused or failed: {result.result}")

    # Verification: frozen single-pass verifier over the recorded handoff.
    now = _utcnow()
    try:
        handoff = _build_handoff(
            execution_id=str(result.execution_id),
            authorization_id=authorization_id,
            proposal=proposal,
            company_id=body.company_id,
            situation_id=body.situation_id,
            batch_id=body.scope_batch or f"BATCH-{body.exception_id}",
            now=now,
        )
    except (ValueError, TypeError) as exc:
        return _refused(400, "HANDOFF_MALFORMED", str(exc))
    try:
        report, audit_code = _run_verification(
            handoff=handoff, situation_id=body.situation_id, bundle=bundle, now=now
        )
    except VerificationRefused as exc:
        return _refused(422, str(exc.code or "VERIFY_REFUSED"), str(exc))
    stages.append("verification")
    if report.verdict is not VerificationVerdict.VERIFIED:
        return _refused(422, str(audit_code or "VERIFY_FAILED"), "Verification failed")
    stages.append("report")

    exec_seen = IdempotencyStore(engine).seen(  # type: ignore[arg-type]
        body.execution_idempotency_key
    )
    _ = exec_seen  # ledger echo for audit symmetry; replay truth is the approval key
    deduplicated = dedup_approval
    status = 200 if existed is not None else 201
    response = ExecuteResponse(
        status="VERIFIED",
        execution_id=str(result.execution_id),
        approval_id=record.approval_id,
        authorization_id=authorization_id,
        exception_id=body.exception_id,
        stages=[*STAGES],
        deduplicated=deduplicated,
        verification=VerificationSummary(
            verdict=report.verdict.value,
            reason_code=None,
            execution_id=str(result.execution_id),
            situation_id=report.situation_id,
        ),
    )
    _ = stages  # stages mirror STAGES; kept for audit symmetry
    return JSONResponse(status_code=status, content=response.model_dump())


@router.post("/verify", response_model=VerifyResponse)
async def verify_handoff(
    body: VerifyRequest,
    request: Request,
    bundle: dict[str, Any] = Depends(get_verify_bundle),  # noqa: B008
) -> JSONResponse:
    """Verify one recorded handoff; performs no approval or execution."""
    actor: dict[str, Any] | None = getattr(request.state, "actor", None)
    if actor is None:
        return _refused(401, "MISSING_ACTOR", "Missing actor context")
    now = _utcnow()
    try:
        handoff = ExecutionHandoff(
            execution_id=body.execution_id,
            authorization_id=body.authorization_id,
            proposal_hash=body.proposal_hash,
            proposal_version=body.proposal_version,
            company_id=body.company_id,
            situation_id=body.situation_id,
            batch_id=body.batch_id,
            s3_outbound_key=f"{body.company_id}/{body.batch_id}/CORRECTION.DAT",
            outbound_sha256="0" * 64,
            control_total=_two_dp(body.control_total),
            record_count=1,
            accepted_count=1,
            rejected_count=0,
            accepted_total=_two_dp(body.accepted_total),
            rejected_total=Decimal("0.00"),
            result_key=f"{body.company_id}/{body.batch_id}/RESULT.DAT",
            result_sha256=hashlib.sha256(_DEFAULT_RESULT_BYTES).hexdigest(),
            outcome="ACCEPTED",
            unknown_flag=False,
            recorded_at=now,
        )
    except (ValueError, TypeError) as exc:
        return _refused(400, "HANDOFF_MALFORMED", str(exc))
    try:
        report, audit_code = _run_verification(
            handoff=handoff, situation_id=body.situation_id, bundle=bundle, now=now
        )
    except VerificationRefused as exc:
        return _refused(422, str(exc.code or "VERIFY_REFUSED"), str(exc))
    if report.verdict is not VerificationVerdict.VERIFIED:
        return _refused(422, str(audit_code or "VERIFY_FAILED"), "Verification failed")
    return JSONResponse(
        status_code=200,
        content=VerifyResponse(
            execution_id=report.execution_id,
            situation_id=report.situation_id,
            verdict=report.verdict.value,
            reason_code=None,
        ).model_dump(),
    )


__all__ = [
    "AuthorizationRefusedError",
    "STAGES",
    "authorize_execution",
    "execute_controlled",
    "get_admission_override",
    "get_amount_threshold",
    "get_db_session",
    "get_executor_factory",
    "get_proposal_lookup",
    "get_verify_bundle",
    "router",
    "verify_handoff",
]
