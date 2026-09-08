"""Aggregate unit tests: create-once, legal chain, bans, frozen writes, versions.

All boundaries are in-memory: no database, no network, no LLM. SQLite
CAS races live in ``test_repository_cas.py``.
"""

import dataclasses
from datetime import UTC, datetime

import pytest

from finance.exceptions.aggregate import ExceptionAggregate
from finance.exceptions.errors import ConcurrencyConflictError, IllegalTransitionError
from finance.exceptions.states import ExceptionState
from finance.reconciliation.models import ExceptionCode


def _make(**overrides: object) -> ExceptionAggregate:
    """Build a deterministic aggregate fixed at a known clock."""
    base: dict[str, object] = {
        "exception_id": "exc-001",
        "tenant_id": "tenant-acme",
        "reconciliation_result_id": "recon-001",
        "exception_type": ExceptionCode.FEE_MISMATCH,
        "severity": "HIGH",
        "evidence_ids": (),
        "created_at": datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return ExceptionAggregate.create(**base)  # type: ignore[arg-type]


class TestCreateOnce:
    """One aggregate per break: version 1, EXCEPTION, empty phase slots."""

    def test_create_initializes_version_and_empty_slots(self) -> None:
        agg = _make()
        assert agg.state is ExceptionState.EXCEPTION
        assert agg.state_version == 1
        assert agg.evidence_ids == ()
        assert agg.proposal_id is None
        assert agg.approval_id is None
        assert agg.execution_id is None

    def test_create_rejects_fourth_exception_code(self) -> None:
        with pytest.raises(ValueError, match="frozen P1 codes"):
            _make(exception_type="I-SOMETHING-ELSE")

    def test_create_rejects_unknown_state_vocab(self) -> None:
        with pytest.raises(ValueError):
            ExceptionAggregate(
                exception_id="exc-x",
                tenant_id="t",
                reconciliation_result_id="r",
                exception_type=ExceptionCode.FEE_MISMATCH,
                severity="HIGH",  # type: ignore[arg-type]
                state="NOT_A_STATE",  # type: ignore[arg-type]
                state_version=1,
                evidence_ids=(),
                proposal_id=None,
                approval_id=None,
                execution_id=None,
                created_at=datetime(2026, 9, 1, tzinfo=UTC),
                updated_at=datetime(2026, 9, 1, tzinfo=UTC),
            )


class TestLegalChain:
    """EXCEPTION -> ... -> AWAITING_APPROVAL bumps exactly one per step."""

    def test_full_p32_chain_to_awaiting_approval(self) -> None:
        agg = _make()
        agg = agg.open_investigation(1, actor="investigator")
        assert (agg.state, agg.state_version) == (ExceptionState.INVESTIGATING, 2)
        agg = agg.mark_evidence_ready(2, ["ev-1", "ev-2"], actor="investigator")
        assert (agg.state, agg.state_version) == (ExceptionState.EVIDENCE_READY, 3)
        assert agg.evidence_ids == ("ev-1", "ev-2")
        agg = agg.verify_evidence(3, actor="verifier")
        assert (agg.state, agg.state_version) == (ExceptionState.EVIDENCE_VERIFIED, 4)
        agg = agg.draft_proposal(4, "prop-001", actor="drafter")
        assert (agg.state, agg.state_version) == (ExceptionState.PROPOSED, 5)
        assert agg.proposal_id == "prop-001"
        agg = agg.submit_for_approval(5, actor="drafter")
        assert (agg.state, agg.state_version) == (ExceptionState.AWAITING_APPROVAL, 6)

    def test_proposed_requires_proposal_slot(self) -> None:
        agg = _make()
        agg = agg.open_investigation(1).mark_evidence_ready(2, ["ev-1"]).verify_evidence(3)
        with pytest.raises(IllegalTransitionError, match="proposal_id slot must be set"):
            agg.transition_to(ExceptionState.PROPOSED, 4)

    def test_beyond_p32_scope_rejected_without_mutation(self) -> None:
        agg = _make()
        agg = (
            agg.open_investigation(1)
            .mark_evidence_ready(2, ["ev-1"])
            .verify_evidence(3)
            .draft_proposal(4, "prop-001")
            .submit_for_approval(5)
        )
        with pytest.raises(IllegalTransitionError, match="beyond P3.2 scope"):
            agg.transition_to(ExceptionState.APPROVED, 6)
        assert agg.state is ExceptionState.AWAITING_APPROVAL
        assert agg.state_version == 6


class TestBannedTransitions:
    """SM-2 bans hold even though the pairs skip the whole pipeline."""

    def test_investigating_to_executing_rejected(self) -> None:
        agg = _make().open_investigation(1)
        with pytest.raises(IllegalTransitionError, match="banned by SM-2"):
            agg.transition_to(ExceptionState.EXECUTING, 2)
        assert (agg.state, agg.state_version) == (ExceptionState.INVESTIGATING, 2)

    def test_proposed_to_executing_rejected(self) -> None:
        agg = _make()
        agg = (
            agg.open_investigation(1)
            .mark_evidence_ready(2, ["ev-1"])
            .verify_evidence(3)
            .draft_proposal(4, "prop-001")
        )
        with pytest.raises(IllegalTransitionError, match="banned by SM-2"):
            agg.transition_to(ExceptionState.EXECUTING, 5)
        assert (agg.state, agg.state_version) == (ExceptionState.PROPOSED, 5)

    def test_skip_transition_rejected(self) -> None:
        agg = _make()
        with pytest.raises(IllegalTransitionError, match="not in SM-1"):
            agg.transition_to(ExceptionState.EVIDENCE_VERIFIED, 1)
        assert (agg.state, agg.state_version) == (ExceptionState.EXCEPTION, 1)


class TestFrozenWrites:
    """Direct field writes are impossible: the dataclass is frozen."""

    def test_direct_state_write_raises(self) -> None:
        agg = _make()
        with pytest.raises(dataclasses.FrozenInstanceError):
            agg.state = ExceptionState.CLOSED  # type: ignore[misc]

    def test_direct_version_write_raises(self) -> None:
        agg = _make()
        with pytest.raises(dataclasses.FrozenInstanceError):
            agg.state_version = 99  # type: ignore[misc]


class TestVersionMonotonicity:
    """Stale versions conflict; rejections never move the version."""

    def test_stale_second_writer_conflicts(self) -> None:
        agg = _make()
        winner = agg.open_investigation(1, actor="writer-a")
        assert winner.state_version == 2
        with pytest.raises(ConcurrencyConflictError, match="CONCURRENCY_CONFLICT"):
            winner.open_investigation(1, actor="writer-b")
        assert winner.state_version == 2
        assert agg.state_version == 1

    def test_version_never_moves_on_reject(self) -> None:
        agg = _make().open_investigation(1)
        before = agg.state_version
        with pytest.raises(IllegalTransitionError):
            agg.transition_to(ExceptionState.EXECUTING, before)
        with pytest.raises(ConcurrencyConflictError):
            agg.transition_to(ExceptionState.EVIDENCE_READY, before + 99)
        assert agg.state_version == before
        assert agg.state is ExceptionState.INVESTIGATING

    def test_severity_rederivation_keeps_version(self) -> None:
        agg = _make().open_investigation(1)
        reseved = agg.with_severity("CRITICAL")
        assert reseved.severity.value == "CRITICAL"
        assert reseved.state_version == agg.state_version
        assert reseved.state is agg.state

    def test_evidence_sealed_append_only(self) -> None:
        agg = _make()
        agg = (
            agg.open_investigation(1)
            .mark_evidence_ready(2, ["ev-1"])
            .verify_evidence(3)
            .draft_proposal(4, "prop-001")
        )
        grown = agg.transition_to(
            ExceptionState.AWAITING_APPROVAL, 5, evidence_ids=["ev-1", "ev-2"]
        )
        assert grown.evidence_ids == ("ev-1", "ev-2")
        with pytest.raises(IllegalTransitionError, match="append-only"):
            agg.transition_to(ExceptionState.AWAITING_APPROVAL, 5, evidence_ids=[])
