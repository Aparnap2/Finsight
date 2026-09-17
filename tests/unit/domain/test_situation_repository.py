"""Unit tests for the P6-02 FinancialSituation repository.

Covers ``finance/domain/situation_repository.py`` against the frozen
P6-01 aggregate: round-trip equality, company isolation (fail-closed),
optimistic-concurrency conflicts, scoped listing, atomic
aggregate-plus-audit writes, and byte determinism. Zero network, no LLM.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from finance.domain.financial_situation import FinancialSituation, SituationStatus
from finance.domain.situation_repository import (
    ConcurrencyError,
    SituationRepository,
    canonical_payload_bytes,
)

SID_1 = "FS-2026-0916-00231"
"""Golden FS-231 case id."""

SID_2 = "FS-2026-0916-00232"
"""Second case id for listing tests."""

SID_3 = "FS-2026-0916-00233"
"""Third case id for listing tests."""

AT_1 = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
"""Caller-supplied audit timestamp (repo never mints time)."""

AT_2 = datetime(2026, 9, 16, 11, 30, tzinfo=UTC)
"""Second caller-supplied audit timestamp."""


def _situation(
    situation_id: str = SID_1,
    status: SituationStatus = SituationStatus.DETECTED,
) -> FinancialSituation:
    """Build the golden FS-231 aggregate with an overridable status."""
    return FinancialSituation(
        situation_id=situation_id,
        company_id="meridian",
        expected=Decimal("1000000"),
        razorpay_net=Decimal("972500"),
        quickbooks=Decimal("982500"),
        legacy=Decimal("982500"),
        status=status,
    )


def _audit(
    event_id: str,
    *,
    situation_id: str = SID_1,
    company_id: str = "meridian",
    from_status: object = SituationStatus.DETECTED,
    to_status: object = SituationStatus.TRIAGED,
    at: datetime = AT_1,
    actor: str = "case-worker",
) -> dict[str, object]:
    """Build one caller-side audit dict in the repository-owned shape."""
    return {
        "event_id": event_id,
        "situation_id": situation_id,
        "company_id": company_id,
        "from_status": from_status,
        "to_status": to_status,
        "at": at,
        "actor": actor,
    }


def _bad_audits() -> list[dict[str, object]]:
    """Audit dicts that must abort the whole save transaction."""
    missing_key = _audit("EVT-BAD-1")
    del missing_key["event_id"]
    naive_time = _audit("EVT-BAD-2", at=datetime(2026, 9, 16, 10, 0))
    case_mismatch = _audit("EVT-BAD-3", situation_id=SID_2)
    company_mismatch = _audit("EVT-BAD-4", company_id="acme")
    return [missing_key, naive_time, case_mismatch, company_mismatch]


@pytest.fixture(params=["memory", "sqlite"])
def make_repo(request: pytest.FixtureRequest) -> Callable[[], SituationRepository]:
    """Return a factory for fresh repositories on the parametrized backend."""
    backend = request.param

    def _make() -> SituationRepository:
        if backend == "memory":
            return SituationRepository()
        return SituationRepository(create_engine("sqlite:///:memory:"))

    return _make


@pytest.fixture
def repo(make_repo: Callable[[], SituationRepository]) -> SituationRepository:
    """Return one fresh repository on the parametrized backend."""
    return make_repo()


@pytest.fixture
def sqlite_repo() -> SituationRepository:
    """Return one fresh SQLAlchemy-backed repository (fault-injection)."""
    return SituationRepository(create_engine("sqlite:///:memory:"))


def test_round_trip_equality(repo: SituationRepository) -> None:
    """Saved aggregate rehydrates equal: model equality plus dump equality."""
    original = _situation()
    repo.save(original)
    stored = repo.get_for_company("meridian", SID_1)
    assert stored is not None
    assert stored == original
    assert stored.model_dump() == original.model_dump()


def test_get_missing_returns_none(repo: SituationRepository) -> None:
    """Unknown case id reads as None (no exception, no leak)."""
    assert repo.get_for_company("meridian", "FS-2026-0916-00999") is None
    assert repo.stored_payload("meridian", "FS-2026-0916-00999") is None
    assert repo.audit_trail("meridian", "FS-2026-0916-00999") == []


def test_cross_company_read_returns_none_without_leak(
    repo: SituationRepository,
) -> None:
    """Wrong-company reads return None uniformly; blanks fail closed too."""
    repo.save(_situation())
    assert repo.get_for_company("acme", SID_1) is None
    assert repo.stored_payload("acme", SID_1) is None
    assert repo.audit_trail("acme", SID_1) == []
    assert repo.get_for_company("", SID_1) is None
    assert repo.get_for_company("meridian", "") is None
    assert repo.get_for_company("   ", "   ") is None
    assert repo.get_for_company("meridian", SID_1) == _situation()


def test_version_bumps_on_each_save(repo: SituationRepository) -> None:
    """First save yields version 1; each later save bumps the counter."""
    assert repo.save(_situation()) == 1
    assert repo.save(_situation(status=SituationStatus.TRIAGED), expected_version=1) == 2
    assert repo.save(_situation(status=SituationStatus.TRIAGED)) == 3


def test_create_with_nonzero_expected_version_conflicts(
    repo: SituationRepository,
) -> None:
    """Claiming a version for a nonexistent row conflicts against actual 0."""
    with pytest.raises(ConcurrencyError) as excinfo:
        repo.save(_situation(), expected_version=5)
    assert excinfo.value.expected_version == 5
    assert excinfo.value.actual_version == 0
    assert repo.get_for_company("meridian", SID_1) is None


def test_stale_version_raises_and_preserves_winner(
    repo: SituationRepository,
) -> None:
    """Stale save raises; the winning row content and version are kept."""
    version_1 = repo.save(_situation())
    version_2 = repo.save(
        _situation(status=SituationStatus.TRIAGED), expected_version=version_1
    )
    assert (version_1, version_2) == (1, 2)
    with pytest.raises(ConcurrencyError) as excinfo:
        repo.save(
            _situation(status=SituationStatus.INVESTIGATING),
            expected_version=version_1,
        )
    assert excinfo.value.expected_version == version_1
    assert excinfo.value.actual_version == version_2
    stored = repo.get_for_company("meridian", SID_1)
    assert stored is not None and stored.status is SituationStatus.TRIAGED


def test_scoped_listing_and_status_filter(repo: SituationRepository) -> None:
    """Listing is company-scoped, id-ordered, and status-filterable."""
    repo.save(_situation(SID_1, SituationStatus.DETECTED))
    repo.save(_situation(SID_2, SituationStatus.TRIAGED))
    repo.save(_situation(SID_3, SituationStatus.TRIAGED))
    assert [s.situation_id for s in repo.list_for_company("meridian")] == [
        SID_1,
        SID_2,
        SID_3,
    ]
    triaged = repo.list_for_company("meridian", status=SituationStatus.TRIAGED)
    assert [s.situation_id for s in triaged] == [SID_2, SID_3]
    by_name = repo.list_for_company("meridian", status="TRIAGED")
    assert [s.situation_id for s in by_name] == [SID_2, SID_3]
    assert repo.list_for_company("acme") == []
    assert repo.list_for_company("") == []


def test_atomic_audit_batch_commits_together(
    repo: SituationRepository,
) -> None:
    """Aggregate plus audit events commit in one transaction, ordered."""
    version = repo.save(
        _situation(status=SituationStatus.TRIAGED),
        audit_events=[_audit("EVT-001", at=AT_1), _audit("EVT-002", at=AT_2)],
    )
    assert version == 1
    trail = repo.audit_trail("meridian", SID_1)
    assert [event.event_id for event in trail] == ["EVT-001", "EVT-002"]
    assert trail[0].at == AT_1
    assert trail[1].at == AT_2
    assert trail[0].from_status == "DETECTED"
    assert trail[0].to_status == "TRIAGED"
    assert trail[0].actor == "case-worker"


@pytest.mark.parametrize("bad", _bad_audits(), ids=["missing-key", "naive-at", "case", "co"])
def test_invalid_audit_rolls_back_aggregate(
    repo: SituationRepository, bad: dict[str, object]
) -> None:
    """One bad audit dict aborts the save: aggregate version and audit log kept."""
    version_1 = repo.save(_situation())
    with pytest.raises(ValueError):
        repo.save(
            _situation(status=SituationStatus.TRIAGED),
            expected_version=version_1,
            audit_events=[bad],
        )
    stored = repo.get_for_company("meridian", SID_1)
    assert stored is not None and stored.status is SituationStatus.DETECTED
    assert repo.audit_trail("meridian", SID_1) == []


def test_commit_failure_rolls_back_both(
    sqlite_repo: SituationRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mid-commit crash persists neither the aggregate nor the audit batch."""
    version_1 = sqlite_repo.save(_situation())

    def _boom(self: Session) -> None:
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(Session, "commit", _boom)
    with pytest.raises(RuntimeError, match="simulated commit failure"):
        sqlite_repo.save(
            _situation(status=SituationStatus.TRIAGED),
            expected_version=version_1,
            audit_events=[_audit("EVT- comm")],
        )
    monkeypatch.undo()
    stored = sqlite_repo.get_for_company("meridian", SID_1)
    assert stored is not None and stored.status is SituationStatus.DETECTED
    assert sqlite_repo.audit_trail("meridian", SID_1) == []


def test_identical_sequences_produce_identical_bytes(
    make_repo: Callable[[], SituationRepository],
) -> None:
    """Same save sequence on two fresh repos yields identical stored bytes."""

    def _run(target: SituationRepository) -> None:
        target.save(_situation(SID_1))
        target.save(
            _situation(SID_1, SituationStatus.TRIAGED),
            expected_version=1,
            audit_events=[_audit("EVT-001", at=AT_1)],
        )
        target.save(_situation(SID_2))

    first, second = make_repo(), make_repo()
    _run(first)
    _run(second)
    assert first.stored_payload("meridian", SID_1) == second.stored_payload(
        "meridian", SID_1
    )
    assert first.stored_payload("meridian", SID_2) == second.stored_payload(
        "meridian", SID_2
    )
    assert first.audit_trail("meridian", SID_1) == second.audit_trail(
        "meridian", SID_1
    )


def test_canonical_payload_bytes_sorted_and_decimal_fixed() -> None:
    """Canonical bytes use sorted keys, compact separators, fixed Decimals."""
    raw = canonical_payload_bytes(_situation())
    assert raw == canonical_payload_bytes(_situation())
    text = raw.decode("utf-8")
    assert text == json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"))
    assert '"expected":"1000000"' in text
    assert '"status":"DETECTED"' in text
    exponent_form = FinancialSituation(
        situation_id=SID_1,
        company_id="meridian",
        expected=Decimal("1E+6"),
        razorpay_net=Decimal("972500"),
        quickbooks=Decimal("982500"),
        legacy=Decimal("982500"),
        status=SituationStatus.DETECTED,
    )
    assert canonical_payload_bytes(exponent_form) == raw
    data = json.loads(text)
    reparsed = FinancialSituation(
        situation_id=data["situation_id"],
        company_id=data["company_id"],
        expected=Decimal(data["expected"]),
        razorpay_net=Decimal(data["razorpay_net"]),
        quickbooks=Decimal(data["quickbooks"]),
        legacy=Decimal(data["legacy"]),
        status=SituationStatus(data["status"]),
    )
    assert reparsed == _situation()


def test_audit_at_round_trips_across_timezone(
    repo: SituationRepository,
) -> None:
    """Non-UTC caller time rehydrates as the same instant, still tz-aware."""
    at_ist = datetime(2026, 9, 16, 15, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    repo.save(
        _situation(status=SituationStatus.TRIAGED),
        audit_events=[_audit("EVT-TZ", at=at_ist)],
    )
    trail = repo.audit_trail("meridian", SID_1)
    assert len(trail) == 1
    event = trail[0]
    assert event.at.tzinfo is not None
    assert event.at.timestamp() == pytest.approx(at_ist.timestamp())


def test_extended_lifecycle_fields_round_trip(
    repo: SituationRepository,
) -> None:
    """P6-02 optional fields survive save/rehydrate without loss."""
    at_close = datetime(2026, 9, 17, 9, 0, tzinfo=UTC)
    full = FinancialSituation(
        situation_id=SID_1,
        company_id="meridian",
        expected=Decimal("1000000"),
        razorpay_net=Decimal("972500"),
        quickbooks=Decimal("982500"),
        legacy=Decimal("982500"),
        status=SituationStatus.VERIFYING,
        proposal_ref="PROP-231-v1",
        verified_total=Decimal("992500"),
        closed_at=at_close,
        rejection_reason=None,
    )
    repo.save(full)
    loaded = repo.get_for_company("meridian", SID_1)
    assert loaded is not None
    assert loaded == full
    assert loaded.proposal_ref == "PROP-231-v1"
    assert loaded.verified_total == Decimal("992500")
    assert loaded.closed_at is not None
    assert loaded.closed_at.timestamp() == pytest.approx(at_close.timestamp())
    assert loaded.rejection_reason is None


def test_db_duplicate_audit_event_translates_to_valueerror(
    repo: SituationRepository,
) -> None:
    """A stored audit event_id re-saved surfaces ValueError on every backend."""
    repo.save(_situation(), audit_events=[_audit("EVT-DUP")])
    with pytest.raises(ValueError, match="already stored"):
        repo.save(_situation(), audit_events=[_audit("EVT-DUP")])


def test_non_audit_integrity_error_propagates(
    sqlite_repo: SituationRepository,
) -> None:
    """A non-audit IntegrityError is re-raised, never mistranslated."""

    def _boom(self: Session) -> None:
        raise IntegrityError(
            "INSERT INTO situations",
            {},
            Exception("UNIQUE constraint failed: situations.pk"),
        )

    with (
        patch.object(Session, "commit", autospec=True, side_effect=_boom),
        pytest.raises(IntegrityError),
    ):
        sqlite_repo.save(_situation())


def test_race_loser_raises_concurrency_error() -> None:
    """Zero-row conditional UPDATE surfaces as ConcurrencyError."""
    import finance.domain.situation_repository as repo_module

    row = MagicMock(version=1)
    query = MagicMock()
    query.filter.return_value = query
    query.one_or_none.return_value = row
    query.update.return_value = 0
    session = MagicMock()
    session.query.return_value = query
    with patch.object(repo_module, "Session", return_value=session):
        repo = SituationRepository(create_engine("sqlite:///:memory:"))
        with pytest.raises(ConcurrencyError):
            repo.save(_situation())


def test_concurrent_handles_no_lost_update(tmp_path: Path) -> None:
    """Two handles on one file DB: stale writer loses loudly, winner persists."""
    url = f"sqlite:///{tmp_path}/race.db"
    first = SituationRepository(create_engine(url))
    second = SituationRepository(create_engine(url))
    first.save(_situation())
    second.save(_situation(status=SituationStatus.TRIAGED))
    with pytest.raises(ConcurrencyError):
        first.save(
            _situation(status=SituationStatus.CORRELATED), expected_version=1
        )
    loaded = first.get_for_company("meridian", SID_1)
    assert loaded is not None
    assert loaded.status is SituationStatus.TRIAGED
