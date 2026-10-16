"""Thin SQS transport adapter for the controlled execution endpoint.

SQS owns transport and delivery only — never financial state. Every
message is forwarded to ``POST execute_controlled`` with its original
idempotency keys and hashes unchanged; the application remains
authoritative for approval, idempotency, execution, verification,
and persistence.

Response classification follows the route's actual contract
(``apps/api/execution_routes.py``); see ``_classify``. Terminal
refusals and poison are quarantined to a durable quarantine queue
(redacted envelope); only then is the original deleted. Transient
failures redrive through SQS visibility expiry, bounded by the
queue's redrive policy into the DLQ.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

logger = logging.getLogger(__name__)

#: Required SQS body fields (ExecuteRequest coordinates, no money).
_REQUIRED_FIELDS = (
    "tenant_id",
    "exception_id",
    "proposal_id",
    "proposal_version",
    "proposal_content_hash",
    "approver_id",
    "decision",
    "idempotency_key",
    "execution_idempotency_key",
    "expected_state_version",
    "situation_id",
)

#: 422 codes that may be transient (executor-side failure can resume).
_TRANSIENT_REFUSALS = frozenset({"EXECUTION_FAILED"})

ActionKind = Literal["delete", "redrive", "quarantine"]
ResultKind = Literal["DELETED", "REDRIVEN", "QUARANTINED", "EMPTY"]


@dataclass(frozen=True)
class Action:
    """Pure routing decision for one message (no SQS calls)."""

    action: ActionKind
    code: str
    execution_id: str | None = None
    verified: bool = False
    deduplicated: bool = False


@dataclass(frozen=True)
class WorkResult:
    """Settled outcome of one poll (SQS state already reconciled)."""

    kind: ResultKind
    code: str = ""
    execution_id: str | None = None
    verified: bool = False
    deduplicated: bool = False


def _sha16(value: str) -> str:
    """Short hash for redacted quarantine metadata (never raw keys)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _validate_shape(body: Any) -> str | None:
    """Return an error code when the body is not a valid work message."""
    if not isinstance(body, dict):
        return "MALFORMED"
    missing = [field for field in _REQUIRED_FIELDS if not body.get(field)]
    if missing:
        return "MALFORMED"
    if not isinstance(body.get("proposal_version"), int):
        return "MALFORMED"
    if not isinstance(body.get("expected_state_version"), int):
        return "MALFORMED"
    return None


def process_message(
    post: Callable[[dict[str, Any], str], tuple[int, dict[str, Any]]],
    body: Any,
) -> Action:
    """Classify one message without touching SQS (crash-safe boundary).

    ``post`` performs the HTTP call and returns ``(status, json)``; it
    may raise ``TimeoutError``/``ConnectionError`` for transport faults.
    """
    shape_error = _validate_shape(body)
    if shape_error is not None:
        return Action(action="quarantine", code=shape_error)
    tenant = str(body["tenant_id"])
    # The tenant claim selects the actor identity only. It is never sent
    # in the body: the route forbids it (extra="forbid") and loads the
    # authoritative tenant from the snapshot it resolves itself.
    post_body = {key: value for key, value in body.items() if key != "tenant_id"}
    try:
        status, response = post(post_body, tenant)
    except (TimeoutError, ConnectionError) as exc:
        logger.warning("worker transport fault, redriving: %s", type(exc).__name__)
        return Action(action="redrive", code="TRANSPORT_FAULT")
    except Exception as exc:  # noqa: BLE001 - unknown post failure must not delete
        logger.warning("worker post failed unexpectedly, redriving: %s", type(exc).__name__)
        return Action(action="redrive", code="POST_FAULT")
    return _classify(status, response)


def _classify(status: int, response: Any) -> Action:
    """Map the route's actual response contract to a routing action."""
    payload = response if isinstance(response, dict) else {}
    if status in (200, 201) and payload.get("status") == "VERIFIED":
        execution_id = payload.get("execution_id")
        if not isinstance(execution_id, str) or not execution_id:
            # Incomplete success payload: never acknowledge a VERIFIED
            # claim that names no execution (defensive contract gap).
            logger.warning("verified response without execution_id; quarantining")
            return Action(action="quarantine", code="CONTRACT_VIOLATION")
        return Action(
            action="delete",
            code="VERIFIED",
            execution_id=execution_id,
            verified=True,
            deduplicated=bool(payload.get("deduplicated", False)),
        )
    if status in (200, 201):
        return Action(action="quarantine", code="CONTRACT_VIOLATION")
    if status == 401:
        return Action(action="quarantine", code="WORKER_IDENTITY")
    if status == 403:
        logger.warning("worker cross-tenant refusal recorded (tenant redacted)")
        return Action(action="quarantine", code="CROSS_TENANT")
    if status == 404:
        return Action(action="quarantine", code="UNKNOWN_POINTER")
    if status == 409:
        # Conflict is terminal and recorded — never reinterpreted as success.
        return Action(action="quarantine", code="IDEMPOTENCY_CONFLICT")
    if status == 400:
        return Action(action="quarantine", code="MALFORMED_COMMAND")
    if status == 422:
        detail = str(payload.get("detail", ""))
        if "EXECUTION_FAILED" in detail or payload.get("code") == "EXECUTION_FAILED":
            return Action(action="redrive", code="EXECUTION_FAILED")
        code = str(payload.get("code", "REFUSAL"))
        return Action(action="quarantine", code=f"REFUSAL_{code}")
    if status == 429:
        return Action(action="redrive", code="THROTTLED")
    if status == 503 or status >= 500:
        return Action(action="redrive", code=f"SERVER_{status}")
    if 400 <= status < 500:
        return Action(action="quarantine", code=f"UNEXPECTED_CLIENT_{status}")
    return Action(action="redrive", code=f"UNEXPECTED_{status}")


def _quarantine_envelope(message_id: str, body: dict[str, Any], code: str) -> dict[str, Any]:
    """Redacted quarantine record (hashes, never raw keys or amounts)."""
    return {
        "message_id": message_id,
        "code": code,
        "tenant_claim": body.get("tenant_id"),
        "exception_id": body.get("exception_id"),
        "idempotency_key_sha": _sha16(str(body.get("idempotency_key", ""))),
        "execution_key_sha": _sha16(str(body.get("execution_idempotency_key", ""))),
        "quarantined_at": datetime.now(UTC).isoformat(),
    }


def poll_once(
    sqs: Any,
    queue_url: str,
    quarantine_url: str,
    post: Callable[[dict[str, Any], str], tuple[int, dict[str, Any]]],
    *,
    wait_seconds: int = 2,
) -> WorkResult:
    """Receive one message, route it, and reconcile SQS state.

    Delete happens only after a trustworthy terminal response or a
    successful durable quarantine send. Anything else leaves the
    message for visibility-expiry redelivery (bounded by redrive/DLQ).
    """
    received = sqs.receive_message(
        QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=wait_seconds
    ).get("Messages", [])
    if not received:
        return WorkResult(kind="EMPTY", code="NO_MESSAGE")
    message = received[0]
    receipt = message["ReceiptHandle"]
    try:
        body = json_loads(message["Body"])
    except ValueError:
        body = None
    action = process_message(post, body)
    if action.action == "delete":
        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt)
        return WorkResult(
            kind="DELETED",
            code=action.code,
            execution_id=action.execution_id,
            verified=action.verified,
            deduplicated=action.deduplicated,
        )
    if action.action == "quarantine":
        envelope = _quarantine_envelope(
            message.get("MessageId", ""), body if isinstance(body, dict) else {}, action.code
        )
        try:
            sqs.send_message(QueueUrl=quarantine_url, MessageBody=json_dumps(envelope))
        except Exception as exc:  # noqa: BLE001 - quarantine must succeed first
            logger.warning("quarantine send failed, redriving: %s", type(exc).__name__)
            return WorkResult(kind="REDRIVEN", code="QUARANTINE_FAILED")
        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt)
        return WorkResult(kind="QUARANTINED", code=action.code)
    return WorkResult(kind="REDRIVEN", code=action.code)


def json_loads(raw: str) -> Any:
    """Parse a message body (thin wrapper for testability)."""
    import json

    return json.loads(raw)


def json_dumps(payload: dict[str, Any]) -> str:
    """Serialize a quarantine envelope (thin wrapper for testability)."""
    import json

    return json.dumps(payload)


__all__ = ["Action", "WorkResult", "poll_once", "process_message"]
