"""Read-only observation endpoints for the operator console (UI-0).

All routes are GET-only and tenant-scoped: the actor comes from
``TenantAuthMiddleware`` (``request.state.actor``); anonymous callers get
401. Rows are addressed by tenant-derived ids and filtered by the actor
tenant — a missing or foreign record returns 404 in both cases (no
existence oracle). No route here writes, schedules, or mutates anything;
the OpenAPI schema is asserted GET-only in tests.

Endpoints:
- ``GET /api/v1/observations/executions`` — execution ledger rows.
- ``GET /api/v1/observations/executions/{id}`` — one row projection.
- ``GET /api/v1/observations/executions/{id}/audit`` — stored audit facts.
- ``GET /api/v1/observations/executions/{id}/timeline`` — transition view.
- ``GET /api/v1/observations/health`` — DB probe + per-tenant counts.
- ``GET /api/v1/observations/metrics`` — per-tenant aggregates.
- ``GET /api/v1/observations/evaluations/runs`` — seeded report index.
- ``GET /api/v1/observations/evaluations/runs/{run_id}`` — one report.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from finance.exceptions.models import ExceptionAuditRow, ExceptionRow
from finance.exceptions.repository import ExceptionRepository
from finance.execution.models import ExecutionRow
from shared.config import get_settings
from shared.safety.errors import PersistenceError

logger = logging.getLogger(__name__)

router = APIRouter()

_RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")

_engine: Engine | None = None


def get_observation_session() -> Iterator[Session]:
    """Yield a request-scoped session (override in tests)."""
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().postgres_uri)
    with Session(_engine) as session:
        yield session


def get_runs_dir() -> Path:
    """Return the evaluation-report directory (override in tests)."""
    return Path("evals/runs")


def _actor_tenant(request: Request) -> str | None:
    """Return the actor tenant, or None for anonymous callers."""
    actor: dict[str, Any] | None = getattr(request.state, "actor", None)
    if actor is None:
        return None
    return str(actor.get("tenant_id", ""))


def _deny_anonymous(request: Request) -> JSONResponse | str:
    """401 for callers without actor context, else the tenant id."""
    tenant_id = _actor_tenant(request)
    if not tenant_id:
        return JSONResponse(status_code=401, content={"detail": "Missing actor context"})
    return tenant_id


def _set_tenant_context(session: Session, tenant_id: str) -> None:
    """Set the Postgres RLS tenant context; skip on other dialects."""
    try:
        dialect = session.get_bind().dialect.name  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 - unbound session: nothing to set
        return
    if dialect != "postgresql":
        return
    session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": tenant_id},
    )


def _row_projection(row: ExecutionRow) -> dict[str, Any]:
    """Project one execution row (stored columns only, no invention)."""
    return {
        "tenant_id": row.tenant_id,
        "idempotency_key": row.idempotency_key,
        "execution_id": row.execution_id,
        "exception_id": row.exception_id,
        "proposal_id": row.proposal_id,
        "payload_hash": row.payload_hash,
        "result": row.result,
        "post_verify": row.post_verify,
        "external_reference": row.external_reference,
    }


def _find_row(session: Session, tenant_id: str, execution_id: str) -> ExecutionRow | None:
    """Fetch one execution row scoped to (tenant, execution id)."""
    stmt = (
        select(ExecutionRow)
        .where(ExecutionRow.tenant_id == tenant_id)
        .where(ExecutionRow.execution_id == execution_id)
    )
    return session.execute(stmt).scalars().first()


@router.get("/api/v1/observations/executions")
async def list_executions(
    request: Request,
    session: Session = Depends(get_observation_session),  # noqa: B008
    result: str | None = None,
) -> JSONResponse:
    """List the actor tenant's execution rows, optionally filtered by result."""
    tenant_or_denied = _deny_anonymous(request)
    if isinstance(tenant_or_denied, JSONResponse):
        return tenant_or_denied
    tenant_id = tenant_or_denied
    try:
        _set_tenant_context(session, tenant_id)
        stmt = select(ExecutionRow).where(ExecutionRow.tenant_id == tenant_id)
        if result is not None:
            stmt = stmt.where(ExecutionRow.result == result)
        rows = session.execute(stmt).scalars().all()
    except (SQLAlchemyError, PersistenceError) as exc:
        logger.warning("observations list failed tenant=%s: %s", tenant_id, exc)
        return JSONResponse(status_code=503, content={"detail": "Storage unavailable"})
    return JSONResponse(
        status_code=200,
        content={"tenant_id": tenant_id, "executions": [_row_projection(r) for r in rows]},
    )


@router.get("/api/v1/observations/executions/{execution_id}")
async def get_execution(
    execution_id: str,
    request: Request,
    session: Session = Depends(get_observation_session),  # noqa: B008
) -> JSONResponse:
    """Return one execution row, or 404 when missing or foreign."""
    tenant_or_denied = _deny_anonymous(request)
    if isinstance(tenant_or_denied, JSONResponse):
        return tenant_or_denied
    try:
        row = _find_row(session, tenant_or_denied, execution_id)
    except (SQLAlchemyError, PersistenceError) as exc:
        logger.warning("observations get failed: %s", exc)
        return JSONResponse(status_code=503, content={"detail": "Storage unavailable"})
    if row is None:
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    return JSONResponse(status_code=200, content=_row_projection(row))


def _audit_entries(
    session: Session, tenant_id: str, exception_id: str
) -> list[ExceptionAuditRow] | None:
    """Return tenant-scoped audit facts ordered by id, or None when absent."""
    engine = session.get_bind()
    assert engine is not None
    repo = ExceptionRepository(engine)  # type: ignore[arg-type]
    trail = repo.audit_trail(exception_id)
    scoped = [a for a in trail if a.tenant_id == tenant_id]
    if not scoped and not trail:
        return None
    if not scoped:
        return None
    return sorted(scoped, key=lambda a: (a.id or 0,))


@router.get("/api/v1/observations/executions/{execution_id}/audit")
async def get_audit(
    execution_id: str,
    request: Request,
    session: Session = Depends(get_observation_session),  # noqa: B008
) -> JSONResponse:
    """Return stored audit facts for the linked exception (created order)."""
    tenant_or_denied = _deny_anonymous(request)
    if isinstance(tenant_or_denied, JSONResponse):
        return tenant_or_denied
    try:
        row = _find_row(session, tenant_or_denied, execution_id)
        if row is None:
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        entries = _audit_entries(session, tenant_or_denied, row.exception_id)
    except (SQLAlchemyError, PersistenceError) as exc:
        logger.warning("observations audit failed: %s", exc)
        return JSONResponse(status_code=503, content={"detail": "Storage unavailable"})
    if entries is None:
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    return JSONResponse(
        status_code=200,
        content=[
            {
                "timestamp": a.created_at.isoformat() if a.created_at else None,
                "actor": a.actor,
                "previous_state": a.from_state,
                "new_state": a.attempted_state,
                "operation": a.outcome,
                "reason": a.reason,
                "expected_version": a.expected_version,
                "actual_version": a.actual_version,
                "tenant_id": a.tenant_id,
            }
            for a in entries
        ],
    )


@router.get("/api/v1/observations/executions/{execution_id}/timeline")
async def get_timeline(
    execution_id: str,
    request: Request,
    session: Session = Depends(get_observation_session),  # noqa: B008
) -> JSONResponse:
    """Return the transition view derived from stored audit facts."""
    tenant_or_denied = _deny_anonymous(request)
    if isinstance(tenant_or_denied, JSONResponse):
        return tenant_or_denied
    try:
        row = _find_row(session, tenant_or_denied, execution_id)
        if row is None:
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        entries = _audit_entries(session, tenant_or_denied, row.exception_id)
    except (SQLAlchemyError, PersistenceError) as exc:
        logger.warning("observations timeline failed: %s", exc)
        return JSONResponse(status_code=503, content={"detail": "Storage unavailable"})
    if entries is None:
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    return JSONResponse(
        status_code=200,
        content=[
            {
                "timestamp": a.created_at.isoformat() if a.created_at else None,
                "previous_state": a.from_state,
                "new_state": a.attempted_state,
                "actor": a.actor,
                "operation": a.outcome,
                "reason": a.reason,
                "tenant_id": a.tenant_id,
            }
            for a in entries
        ],
    )


@router.get("/api/v1/observations/health")
async def get_health(
    request: Request,
    session: Session = Depends(get_observation_session),  # noqa: B008
) -> JSONResponse:
    """DB probe plus per-tenant counts (explicit ok:false, never an exception)."""
    tenant_or_denied = _deny_anonymous(request)
    if isinstance(tenant_or_denied, JSONResponse):
        return tenant_or_denied
    tenant_id = tenant_or_denied
    start = time.perf_counter()
    try:
        session.execute(text("SELECT 1"))
        latency_ms = round((time.perf_counter() - start) * 1000.0, 3)
        executions = (
            session.execute(select(ExecutionRow).where(ExecutionRow.tenant_id == tenant_id))
            .scalars()
            .all()
        )
        exceptions = (
            session.execute(select(ExceptionRow).where(ExceptionRow.tenant_id == tenant_id))
            .scalars()
            .all()
        )
        audits = (
            session.execute(
                select(ExceptionAuditRow).where(ExceptionAuditRow.tenant_id == tenant_id)
            )
            .scalars()
            .all()
        )
    except (SQLAlchemyError, PersistenceError) as exc:
        logger.warning("observations health probe failed: %s", exc)
        return JSONResponse(
            status_code=200,
            content={"tenant_id": tenant_id, "db": {"ok": False, "latency_ms": None}},
        )
    return JSONResponse(
        status_code=200,
        content={
            "tenant_id": tenant_id,
            "db": {"ok": True, "latency_ms": latency_ms},
            "counts": {
                "executions": len(executions),
                "exceptions": len(exceptions),
                "audits": len(audits),
            },
        },
    )


@router.get("/api/v1/observations/metrics")
async def get_metrics(
    request: Request,
    session: Session = Depends(get_observation_session),  # noqa: B008
) -> JSONResponse:
    """Per-tenant aggregates over executions, exceptions, and audits."""
    tenant_or_denied = _deny_anonymous(request)
    if isinstance(tenant_or_denied, JSONResponse):
        return tenant_or_denied
    tenant_id = tenant_or_denied
    try:
        _set_tenant_context(session, tenant_id)
        executions = (
            session.execute(select(ExecutionRow).where(ExecutionRow.tenant_id == tenant_id))
            .scalars()
            .all()
        )
        exceptions = (
            session.execute(select(ExceptionRow).where(ExceptionRow.tenant_id == tenant_id))
            .scalars()
            .all()
        )
        audits = (
            session.execute(
                select(ExceptionAuditRow).where(ExceptionAuditRow.tenant_id == tenant_id)
            )
            .scalars()
            .all()
        )
    except (SQLAlchemyError, PersistenceError) as exc:
        logger.warning("observations metrics failed: %s", exc)
        return JSONResponse(status_code=503, content={"detail": "Storage unavailable"})
    by_result = Counter(r.result if r.result is not None else "IN_PROGRESS" for r in executions)
    by_state = Counter(str(e.state) for e in exceptions)
    return JSONResponse(
        status_code=200,
        content={
            "tenant_id": tenant_id,
            "executions_by_result": dict(sorted(by_result.items())),
            "exceptions_by_state": dict(sorted(by_state.items())),
            "audits": len(audits),
        },
    )


def _read_report(runs_dir: Path, run_id: str) -> dict[str, Any] | None:
    """Read one report file, or None when absent/invalid/unresolvable."""
    if not _RUN_ID_RE.fullmatch(run_id):
        return None
    try:
        base = runs_dir.resolve()
        candidate = (base / f"{run_id}.json").resolve()
    except OSError:
        return None
    try:
        inside = candidate.is_relative_to(base)
    except ValueError:
        inside = False
    if not inside or not candidate.is_file():
        return None
    try:
        data = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        logger.warning("observations skipping unreadable report run=%s", run_id)
        return None
    if not isinstance(data, dict) or "model" not in data or "summary" not in data:
        return None
    return data


@router.get("/api/v1/observations/evaluations/runs")
async def list_eval_runs(
    request: Request,
    runs_dir: Path = Depends(get_runs_dir),  # noqa: B008
) -> JSONResponse:
    """Index seeded evaluation reports (workspace-level benchmark data)."""
    tenant_or_denied = _deny_anonymous(request)
    if isinstance(tenant_or_denied, JSONResponse):
        return tenant_or_denied
    runs: list[dict[str, Any]] = []
    try:
        files = sorted(runs_dir.glob("*.json")) if runs_dir.is_dir() else []
    except OSError as exc:
        logger.warning("observations runs dir unreadable: %s", exc)
        files = []
    for path in files:
        data = _read_report(runs_dir, path.stem)
        if data is None:
            continue
        summary = data["summary"] if isinstance(data.get("summary"), dict) else {}
        runs.append(
            {
                "run_id": path.stem,
                "model": data.get("model"),
                "provider": data.get("provider"),
                "total": summary.get("total"),
                "passed": summary.get("passed"),
                "failed": summary.get("failed"),
            }
        )
    return JSONResponse(status_code=200, content={"runs": runs})


@router.get("/api/v1/observations/evaluations/runs/{run_id}")
async def get_eval_run(
    run_id: str,
    request: Request,
    runs_dir: Path = Depends(get_runs_dir),  # noqa: B008
) -> JSONResponse:
    """Return one seeded evaluation report, or 404 when unknown."""
    tenant_or_denied = _deny_anonymous(request)
    if isinstance(tenant_or_denied, JSONResponse):
        return tenant_or_denied
    data = _read_report(runs_dir, run_id)
    if data is None:
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    return JSONResponse(status_code=200, content=data)


__all__ = [
    "get_observation_session",
    "get_runs_dir",
    "router",
]
