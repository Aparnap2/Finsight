"""PersistenceFailure contract: a DB failure never masquerades as a domain result.

A missing row is None/not-found; a dead database is PersistenceError. Both
``ExceptionRepository`` and ``IdempotencyStore`` must raise the typed error
instead of leaking a raw driver exception or (worse) returning a
legitimate-looking value.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from finance.exceptions.aggregate import ExceptionAggregate
from finance.exceptions.models import ExceptionAuditRow, ExceptionRow
from finance.exceptions.repository import ExceptionRepository
from finance.exceptions.states import ExceptionState
from finance.reconciliation.models import ExceptionCode

_AT = datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC)


def _engine() -> object:
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _seed(repo: ExceptionRepository, exc_id: str = "exc-pe-1") -> None:
    agg = ExceptionAggregate.create(
        exception_id=exc_id,
        tenant_id="tenant-acme",
        reconciliation_result_id=f"recon-{exc_id}",
        exception_type=ExceptionCode.FEE_MISMATCH,
        severity="HIGH",
        created_at=_AT,
    )
    repo.create(agg, actor="seeder")


class TestRepositoryPersistenceFailure:
    def test_get_on_broken_db_raises_typed_persistence_error(self) -> None:
        from shared.safety.errors import PersistenceError

        engine = _engine()
        repo = ExceptionRepository(engine)  # type: ignore[arg-type]
        _seed(repo)
        ExceptionRow.__table__.drop(engine)  # type: ignore[arg-type]
        with pytest.raises(PersistenceError):
            repo.get("exc-pe-1")

    def test_apply_rolls_back_row_when_audit_write_fails(self) -> None:
        from shared.safety.errors import PersistenceError

        engine = _engine()
        repo = ExceptionRepository(engine)  # type: ignore[arg-type]
        _seed(repo)
        snapshot = repo.get("exc-pe-1")
        assert snapshot is not None
        ExceptionAuditRow.__table__.drop(engine)  # type: ignore[arg-type]
        with pytest.raises(PersistenceError):
            repo.apply(snapshot, ExceptionState.PROPOSED, actor="tester")
        # The row UPDATE must have been rolled back, not partially committed.
        current = ExceptionRepository(engine).get("exc-pe-1")  # type: ignore[arg-type]
        assert current is not None
        assert current.state is ExceptionState.EXCEPTION
        assert current.state_version == 1

    def test_concurrent_apply_audit_failure_leaves_no_partial_state(self) -> None:
        from shared.safety.errors import PersistenceError

        engine = _engine()
        repo = ExceptionRepository(engine)  # type: ignore[arg-type]
        _seed(repo)
        snapshot = repo.get("exc-pe-1")
        assert snapshot is not None
        ExceptionAuditRow.__table__.drop(engine)  # type: ignore[arg-type]
        with pytest.raises(PersistenceError):
            repo.apply(snapshot, ExceptionState.PROPOSED, actor="tester")
        row = ExceptionRepository(engine).get("exc-pe-1")  # type: ignore[arg-type]
        assert row is not None
        assert row.state_version == 1


class TestIdempotencyStorePersistenceFailure:
    def test_seen_on_broken_db_raises_typed_persistence_error(self) -> None:
        from shared.safety.errors import PersistenceError
        from shared.safety.idempotency import IdempotencyRow, IdempotencyStore

        engine = _engine()
        store = IdempotencyStore(engine)  # type: ignore[arg-type]
        IdempotencyRow.__table__.drop(engine)  # type: ignore[arg-type]
        with pytest.raises(PersistenceError):
            store.seen("t-acme", "k")

    def test_payload_hash_for_on_broken_db_raises_typed_persistence_error(self) -> None:
        from shared.safety.errors import PersistenceError
        from shared.safety.idempotency import IdempotencyRow, IdempotencyStore

        engine = _engine()
        store = IdempotencyStore(engine)  # type: ignore[arg-type]
        IdempotencyRow.__table__.drop(engine)  # type: ignore[arg-type]
        with pytest.raises(PersistenceError):
            store.payload_hash_for("t-acme", "k")

    def test_claim_on_broken_db_raises_typed_persistence_error(self) -> None:
        from shared.safety.errors import PersistenceError
        from shared.safety.idempotency import IdempotencyRow, IdempotencyStore

        engine = _engine()
        store = IdempotencyStore(engine)  # type: ignore[arg-type]
        IdempotencyRow.__table__.drop(engine)  # type: ignore[arg-type]
        with pytest.raises(PersistenceError):
            store.claim("t-acme", "k", "h")
