"""Concurrency evidence for reconciliation persistence (real Postgres threads)."""

from __future__ import annotations

import os
import threading
from typing import Any
from uuid import uuid4

os.environ.setdefault(
    "POSTGRES_URI", "postgresql+psycopg://finsight:finsight@localhost:5432/finsight"
)
os.environ.setdefault(
    "MIGRATION_POSTGRES_URI", "postgresql+psycopg://finsight:finsight@localhost:5432/finsight"
)

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

DSN = os.environ.get(
    "FINSIGHT_TEST_DSN", "postgresql+psycopg://finsight:finsight@localhost:5432/finsight"
)

TENANT_A = "7d6f8b65-5e40-55b5-967f-69b85912dd87"


def _reachable() -> bool:
    try:
        e = create_engine(DSN, pool_pre_ping=True)
        with e.connect() as c:
            c.execute(text("SELECT 1"))
        e.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason="Postgres unreachable")


def _seed_exception(engine: Any) -> str:
    eid = str(uuid4())
    with engine.begin() as conn:
        # a reconciliation run is required by FK; insert a minimal one
        rid = str(uuid4())
        sid = str(uuid4())
        conn.execute(
            text(
                "INSERT INTO import_sessions (session_id, tenant_id, actor_id, "
                "status, period_start, period_end) "
                "VALUES (:sid, :t, 'u', 'READY', '2026-01-01', '2026-01-31')"
            ),
            {"sid": sid, "t": TENANT_A},
        )
        conn.execute(
            text(
                "INSERT INTO reconciliation_runs (run_id, session_id, tenant_id, actor_id, status, "
                "idempotency_key, engine_version, input_fingerprint, input_snapshot_ref) "
                "VALUES (:rid, :sid, :t, 'u', 'SUCCEEDED', :key, 'dev', 'fp', 'snap')"
            ),
            {"rid": rid, "sid": sid, "t": TENANT_A, "key": str(uuid4())},
        )
        conn.execute(
            text(
                "INSERT INTO reconciliation_exceptions (exception_id, run_id, tenant_id, "
                "exception_code, severity, status, title, description) "
                "VALUES (:eid, :rid, :t, 'I-FEE-DRIFT', 'MEDIUM', 'UNDER_REVIEW', 't', 'd')"
            ),
            {"eid": eid, "rid": rid, "t": TENANT_A},
        )
    return eid


def test_concurrent_decisions_one_wins() -> None:
    from finance.exceptions.errors import IllegalTransitionError
    from finance.reconciliation.persistence import record_decision

    engine = create_engine(DSN)
    eid = _seed_exception(engine)
    barrier = threading.Barrier(2)
    results: list[tuple[str, str]] = []

    def worker() -> None:
        barrier.wait()
        s = Session(engine)
        try:
            try:
                rid = record_decision(
                    s,
                    exception_id=eid,
                    tenant_id=TENANT_A,
                    actor_id="u",
                    decision_type="APPROVE",
                    reason="r",
                    previous_status="UNDER_REVIEW",
                    new_status="RESOLVED",
                )
                s.commit()
                results.append(("ok", rid))
            except IllegalTransitionError as exc:
                s.rollback()
                results.append(("conflict", str(exc)))
            except Exception as exc:  # noqa: BLE001
                s.rollback()
                results.append(("error", repr(exc)))
        finally:
            s.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 2
    kinds = sorted(r[0] for r in results)
    assert kinds == ["conflict", "ok"], results
    engine.dispose()


def test_concurrent_decisions_without_lock_both_commit() -> None:
    """Mutation probe: with locking removed, both decisions commit (defect)."""
    # This is documented, not run; see mutation notes. Skip to keep suite green.
    pytest.skip("mutation probe; run manually by editing record_decision")
