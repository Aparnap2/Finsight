"""Repository CAS tests over SQLite: one winner, audit on every attempt.

Two repository handles share one engine to simulate concurrent writers:
both read the same snapshot, both CAS-apply, exactly one wins and the
loser receives ``CONCURRENCY_CONFLICT`` with zero mutation. Every
attempt — applied or rejected — leaves an audit row.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from finance.exceptions.aggregate import ExceptionAggregate
from finance.exceptions.errors import ConcurrencyConflictError, IllegalTransitionError
from finance.exceptions.repository import ExceptionRepository
from finance.exceptions.states import ExceptionState
from finance.reconciliation.models import ExceptionCode

_AT = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)


def _engine() -> object:
    """Build a shared in-memory SQLite engine for CAS races."""
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _seed(repo: ExceptionRepository, exc_id: str = "exc-cas-1") -> ExceptionAggregate:
    """Create one aggregate and return its fresh snapshot."""
    agg = ExceptionAggregate.create(
        exception_id=exc_id,
        tenant_id="tenant-acme",
        reconciliation_result_id=f"recon-{exc_id}",
        exception_type=ExceptionCode.FEE_MISMATCH,
        severity="HIGH",
        created_at=_AT,
    )
    repo.create(agg, actor="seeder")
    snapshot = repo.get(exc_id)
    assert snapshot is not None
    return snapshot


class TestCreateAndRead:
    """Create-once persists; reads expose the version for retry."""

    def test_create_get_roundtrip(self) -> None:
        repo = ExceptionRepository(_engine())  # type: ignore[arg-type]
        snapshot = _seed(repo)
        assert snapshot.state is ExceptionState.EXCEPTION
        assert snapshot.state_version == 1
        assert snapshot.tenant_id == "tenant-acme"

    def test_duplicate_create_rejected(self) -> None:
        repo = ExceptionRepository(_engine())  # type: ignore[arg-type]
        snapshot = _seed(repo)
        with pytest.raises(IllegalTransitionError, match="duplicate create"):
            repo.create(snapshot, actor="seeder-again")


class TestAtomicCas:
    """Single UPDATE with version+state predicate: one CAS wins."""

    def test_applied_transition_bumps_and_audits(self) -> None:
        repo = ExceptionRepository(_engine())  # type: ignore[arg-type]
        snapshot = _seed(repo)
        applied = repo.apply(snapshot, ExceptionState.INVESTIGATING, actor="writer-a")
        assert applied.state is ExceptionState.INVESTIGATING
        assert applied.state_version == 2
        trail = repo.audit_trail(snapshot.exception_id)
        outcomes = [row.outcome for row in trail]
        assert outcomes == ["CREATED", "APPLIED"]

    def test_two_handles_race_one_wins(self) -> None:
        engine = _engine()
        repo_a = ExceptionRepository(engine)  # type: ignore[arg-type]
        repo_b = ExceptionRepository(engine)  # type: ignore[arg-type]
        snap_a = _seed(repo_a)
        snap_b = repo_b.get(snap_a.exception_id)
        assert snap_b is not None
        assert snap_a.state_version == snap_b.state_version == 1
        winner = repo_a.apply(snap_a, ExceptionState.INVESTIGATING, actor="writer-a")
        assert winner.state_version == 2
        with pytest.raises(ConcurrencyConflictError, match="CONCURRENCY_CONFLICT"):
            repo_b.apply(snap_b, ExceptionState.INVESTIGATING, actor="writer-b")
        current = repo_a.get(snap_a.exception_id)
        assert current is not None
        assert current.state is ExceptionState.INVESTIGATING
        assert current.state_version == 2
        trail = repo_a.audit_trail(snap_a.exception_id)
        assert [row.outcome for row in trail] == ["CREATED", "APPLIED", "REJECTED"]
        rejected = trail[-1]
        assert rejected.expected_version == 1
        assert rejected.actual_version == 2

    def test_stale_snapshot_never_mutates_slots(self) -> None:
        engine = _engine()
        repo = ExceptionRepository(engine)  # type: ignore[arg-type]
        snapshot = _seed(repo)
        repo.apply(snapshot, ExceptionState.INVESTIGATING, actor="writer-a")
        stale = snapshot
        with pytest.raises(ConcurrencyConflictError):
            repo.apply(
                stale,
                ExceptionState.INVESTIGATING,
                actor="writer-b",
            )
        current = repo.get(snapshot.exception_id)
        assert current is not None
        assert current.state_version == 2

    def test_illegal_move_rejected_and_audited_without_mutation(self) -> None:
        repo = ExceptionRepository(_engine())  # type: ignore[arg-type]
        snapshot = _seed(repo)
        opened = repo.apply(snapshot, ExceptionState.INVESTIGATING, actor="writer-a")
        with pytest.raises(IllegalTransitionError, match="banned by SM-2"):
            repo.apply(opened, ExceptionState.EXECUTING, actor="writer-b")
        current = repo.get(snapshot.exception_id)
        assert current is not None
        assert (current.state, current.state_version) == (
            ExceptionState.INVESTIGATING,
            2,
        )
        trail = repo.audit_trail(snapshot.exception_id)
        assert trail[-1].outcome == "REJECTED"

    def test_version_monotonic_across_chain(self) -> None:
        repo = ExceptionRepository(_engine())  # type: ignore[arg-type]
        snapshot = _seed(repo)
        versions = [snapshot.state_version]
        snapshot = repo.apply(snapshot, ExceptionState.INVESTIGATING, actor="t")
        versions.append(snapshot.state_version)
        snapshot = repo.apply(
            snapshot,
            ExceptionState.EVIDENCE_READY,
            actor="t",
            evidence_ids=["ev-1"],
        )
        versions.append(snapshot.state_version)
        snapshot = repo.apply(snapshot, ExceptionState.EVIDENCE_VERIFIED, actor="t")
        versions.append(snapshot.state_version)
        assert versions == [1, 2, 3, 4]
