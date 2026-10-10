"""Unit tests: worker response classification (APA-77 review hardening).

Pure contract tests (no PG, no SQS): the worker must validate required
success-response fields before acknowledging, and must route every
known refusal without deleting.
"""

from __future__ import annotations

from typing import Any

from apps.workers.sqs_execute import Action, process_message


def _body(**over: Any) -> dict[str, Any]:
    """Minimal valid work message."""
    body: dict[str, Any] = {
        "tenant_id": "tenant-a",
        "exception_id": "exc-1",
        "proposal_id": "prop-1",
        "proposal_version": 1,
        "proposal_content_hash": "h" * 16,
        "approver_id": "approver-1",
        "decision": "APPROVED",
        "idempotency_key": "key-approval",
        "execution_idempotency_key": "key",
        "expected_state_version": 2,
        "situation_id": "SIT-1",
    }
    body.update(over)
    return body


def _post(status: int, payload: dict[str, Any]) -> Any:
    """Stub post callable returning a fixed response."""
    return lambda _body, _tenant: (status, payload)


class TestClassify:
    def test_verified_with_execution_id_deletes(self) -> None:
        action = process_message(
            _post(201, {"status": "VERIFIED", "execution_id": "exec-1"}),
            _body(),
        )
        assert action == Action(
            action="delete", code="VERIFIED", execution_id="exec-1", verified=True
        )

    def test_verified_without_execution_id_quarantines(self) -> None:
        action = process_message(
            _post(200, {"status": "VERIFIED"}),
            _body(),
        )
        assert action.action == "quarantine"
        assert action.code == "CONTRACT_VIOLATION"

    def test_verified_with_empty_execution_id_quarantines(self) -> None:
        action = process_message(
            _post(200, {"status": "VERIFIED", "execution_id": ""}),
            _body(),
        )
        assert action.action == "quarantine"

    def test_conflict_never_counts_as_success(self) -> None:
        action = process_message(
            _post(409, {"detail": "Key bound", "code": "IDEMPOTENCY_CONFLICT"}),
            _body(),
        )
        assert action.action == "quarantine"
        assert action.verified is False

    def test_execution_failed_redrives(self) -> None:
        action = process_message(
            _post(422, {"detail": "x", "code": "EXECUTION_FAILED"}),
            _body(),
        )
        assert action.action == "redrive"

    def test_transport_fault_redrives(self) -> None:
        def _flaky(_body: Any, _tenant: str) -> Any:
            raise TimeoutError("deadline")

        action = process_message(_flaky, _body())
        assert action.action == "redrive"
        assert action.code == "TRANSPORT_FAULT"

    def test_malformed_shape_quarantines_without_post(self) -> None:
        calls: list[Any] = []

        def _spy(_body: Any, _tenant: str) -> Any:
            calls.append(_body)
            return (200, {})

        action = process_message(_spy, {"nope": True})
        assert action.action == "quarantine"
        assert action.code == "MALFORMED"
        assert calls == []
