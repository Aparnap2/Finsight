"""HITL approval decision endpoint: validate -> decide -> ack.

POST ``/approvals/decide`` accepts ONLY the decision coordinates
(``exception_id``, ``proposal_id``, ``proposal_version``,
``proposal_content_hash``, ``approver_id``, ``decision``,
``idempotency_key``, ``expected_state_version``): any unknown field such
as ``amount`` or ``action`` is rejected with 422 (``extra="forbid"``), so
callers can never smuggle money or actions past policy — the service
reads money from the pinned proposal only.

Tenant isolation mirrors ``apps.api.webhooks``: the actor comes from
``TenantAuthMiddleware`` (``request.state.actor``), the Postgres RLS
tenant context is set before the service runs, and the aggregate tenant
must match the actor tenant (else 403). The decision commits the
terminal state plus the immutable record with NO execution scheduling.
"""

import logging
from collections.abc import Iterator
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from finance.approvals.decision import ApprovalCommand
from finance.approvals.service import ApprovalService
from finance.exceptions.errors import (
    ApprovalSkewError,
    ConcurrencyConflictError,
    IllegalTransitionError,
)
from finance.exceptions.repository import ExceptionRepository
from shared.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()

DECISION_FORM = Literal["APPROVED", "REJECTED"]


class DecideRequest(BaseModel):
    """Decision coordinates only; unknown fields (amount/action) -> 422."""

    model_config = ConfigDict(extra="forbid")

    exception_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    proposal_version: int = Field(ge=1)
    proposal_content_hash: str = Field(min_length=1)
    approver_id: str = Field(min_length=1)
    decision: DECISION_FORM
    idempotency_key: str = Field(min_length=1)
    expected_state_version: int = Field(ge=1)


class DecideResponse(BaseModel):
    """Decision acknowledgement: terminal state plus record identity."""

    approval_id: str
    exception_id: str
    decision: DECISION_FORM
    state: str
    state_version: int
    idempotency_key: str
    deduplicated: bool


#: In-process proposal registry (override in tests via dependency).
_proposal_registry: dict[str, Any] = {}


def get_proposal_lookup() -> dict[str, Any]:
    """Return the proposal lookup mapping (override in tests)."""
    return _proposal_registry


_engine: Engine | None = None


def get_db_session() -> Iterator[Session]:
    """Yield a request-scoped SQLAlchemy session (override in tests)."""
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().postgres_uri)
    with Session(_engine) as session:
        yield session


def _set_tenant_context(session: Session, tenant_id: str) -> None:
    """Set the Postgres RLS tenant context; skip on non-Postgres dialects."""
    try:
        dialect = session.get_bind().dialect.name  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 - unbound session: nothing to set
        logger.debug("No bind dialect available; skipping RLS tenant context.")
        return
    if dialect != "postgresql":
        logger.debug("Skipping RLS tenant context on dialect %s.", dialect)
        return
    session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": tenant_id},
    )


@router.post("/approvals/decide", response_model=DecideResponse)
async def decide_approval(
    body: DecideRequest,
    request: Request,
    session: Session = Depends(get_db_session),  # noqa: B008
    proposals: dict[str, Any] = Depends(get_proposal_lookup),  # noqa: B008
) -> JSONResponse:
    """Validate one HITL decision and CAS it to terminal state."""
    actor: dict[str, Any] | None = getattr(request.state, "actor", None)
    if actor is None:
        return JSONResponse(status_code=401, content={"detail": "Missing actor context"})
    tenant_id = str(actor.get("tenant_id", ""))
    engine = session.get_bind()
    assert engine is not None  # bound session always carries an engine
    repo = ExceptionRepository(engine)  # type: ignore[arg-type]
    snapshot = repo.get(body.exception_id)
    if snapshot is not None and snapshot.tenant_id != tenant_id:
        logger.warning("Cross-tenant approval denied exception=%s.", body.exception_id)
        return JSONResponse(status_code=403, content={"detail": "Cross-tenant denied"})
    try:
        _set_tenant_context(session, tenant_id)
        service = ApprovalService(engine, amount_threshold=Decimal("10000"))  # type: ignore[arg-type]  # noqa: E501
        existed = service.get_by_idempotency_key(body.idempotency_key)
        cmd = ApprovalCommand(
            exception_id=body.exception_id,
            proposal_id=body.proposal_id,
            proposal_version=body.proposal_version,
            proposal_content_hash=body.proposal_content_hash,
            approver_id=body.approver_id,
            decision=body.decision,  # type: ignore[arg-type]
            idempotency_key=body.idempotency_key,
            expected_state_version=body.expected_state_version,
        )
        record = service.decide(cmd, repo, proposals)
    except (IllegalTransitionError, ApprovalSkewError) as exc:
        logger.warning("Approval rejected exception=%s: %s.", body.exception_id, exc)
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except ConcurrencyConflictError as exc:
        logger.warning("Approval conflict exception=%s: %s.", body.exception_id, exc)
        return JSONResponse(status_code=409, content={"detail": str(exc)})
    except (ValueError, TypeError, SQLAlchemyError) as exc:
        logger.exception("Approval failed exception=%s.", body.exception_id)
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    state = "APPROVED" if record.decision.value == "APPROVED" else "REJECTED"
    status = 200 if existed is not None else 201
    return JSONResponse(
        status_code=status,
        content={
            "approval_id": record.approval_id,
            "exception_id": record.exception_id,
            "decision": record.decision.value,
            "state": state,
            "state_version": record.state_version,
            "idempotency_key": record.idempotency_key,
            "deduplicated": existed is not None,
        },
    )


__all__ = [
    "DecideRequest",
    "DecideResponse",
    "decide_approval",
    "get_db_session",
    "get_proposal_lookup",
    "router",
]
