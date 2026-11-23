"""P3 — Exception lifecycle: state machine and transition validation.

Tests the legal state transitions for reconciliation exceptions, the
validate_transition function, and the allowed_targets/is_terminal helpers.
"""

from __future__ import annotations

import pytest

from finance.exceptions.errors import IllegalTransitionError
from finance.reconciliation.exception_lifecycle import (
    ALLOWED_TRANSITIONS,
    allowed_targets,
    is_terminal,
    validate_transition,
)
from finance.reconciliation.models import ExceptionStatus


class TestValidateTransition:
    def test_open_to_investigating_via_assign(self) -> None:
        validate_transition(ExceptionStatus.OPEN, ExceptionStatus.INVESTIGATING, "ASSIGN")

    def test_investigating_to_resolved_via_approve(self) -> None:
        validate_transition(ExceptionStatus.INVESTIGATING, ExceptionStatus.RESOLVED, "APPROVE")

    def test_investigating_to_reopened_via_reject(self) -> None:
        validate_transition(ExceptionStatus.INVESTIGATING, ExceptionStatus.REOPENED, "REJECT")

    def test_resolved_to_reopened_via_reopen(self) -> None:
        validate_transition(ExceptionStatus.RESOLVED, ExceptionStatus.REOPENED, "REOPEN")

    def test_reopened_to_investigating_via_assign(self) -> None:
        validate_transition(ExceptionStatus.REOPENED, ExceptionStatus.INVESTIGATING, "ASSIGN")

    def test_no_op_transition_is_illegal(self) -> None:
        with pytest.raises(IllegalTransitionError):
            validate_transition(ExceptionStatus.OPEN, ExceptionStatus.OPEN, "ASSIGN")

    def test_unlisted_transition_is_illegal(self) -> None:
        with pytest.raises(IllegalTransitionError):
            validate_transition(ExceptionStatus.OPEN, ExceptionStatus.RESOLVED, "APPROVE")

    def test_wrong_decision_type_is_illegal(self) -> None:
        with pytest.raises(IllegalTransitionError):
            validate_transition(ExceptionStatus.OPEN, ExceptionStatus.INVESTIGATING, "APPROVE")

    def test_banned_transition_reopened_to_resolved_is_illegal(self) -> None:
        with pytest.raises(IllegalTransitionError):
            validate_transition(ExceptionStatus.REOPENED, ExceptionStatus.RESOLVED, "APPROVE")

    def test_unknown_status_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            validate_transition("NOT_A_STATUS", ExceptionStatus.OPEN, "ASSIGN")

    def test_string_inputs_are_accepted(self) -> None:
        validate_transition("OPEN", "INVESTIGATING", "ASSIGN")


class TestAllowedTargets:
    def test_open_has_two_targets(self) -> None:
        targets = allowed_targets(ExceptionStatus.OPEN)
        assert targets == {ExceptionStatus.INVESTIGATING, ExceptionStatus.UNDER_REVIEW}

    def test_resolved_can_be_reopened(self) -> None:
        assert allowed_targets(ExceptionStatus.RESOLVED) == {ExceptionStatus.REOPENED}

    def test_unknown_status_returns_empty(self) -> None:
        assert allowed_targets("NOT_A_STATUS") == frozenset()


class TestIsTerminal:
    def test_resolved_is_terminal(self) -> None:
        assert is_terminal(ExceptionStatus.RESOLVED) is True

    def test_open_is_not_terminal(self) -> None:
        assert is_terminal(ExceptionStatus.OPEN) is False

    def test_unknown_is_not_terminal(self) -> None:
        assert is_terminal("NOT_A_STATUS") is False


class TestTransitionCoverage:
    def test_every_allowed_transition_has_at_least_one_decision(self) -> None:
        for (src, tgt), decisions in ALLOWED_TRANSITIONS.items():
            assert len(decisions) >= 1, f"{src} -> {tgt} has no decisions"

    def test_transition_count_is_reasonable(self) -> None:
        assert len(ALLOWED_TRANSITIONS) >= 10
