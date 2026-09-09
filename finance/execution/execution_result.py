"""Frozen execution outcome value objects (execution phase only).

``ExecutionResult`` is the immutable fact of one ``Executor.run`` call:
a stable ``execution_id`` derived from the idempotency key, a terminal
``result`` (``SUCCEEDED``/``FAILED``/``REJECTED``), the adapter's
``external_reference`` when a write booked, and the independent
``post_verify`` verdict (``MATCHED``/``MISMATCH``). ``CLOSED`` is
reachable only with ``SUCCEEDED`` + ``MATCHED``; adapter success alone
never closes.

Only the Python standard library is used. This module imports nothing
from ``apps/``, ``agents/``, ``shared/``, or any other ``finance.*``
package.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ExecutionResultStatus(StrEnum):
    """Terminal verdicts of one executor run; no other value is a result."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


class PostVerifyVerdict(StrEnum):
    """Independent post-execution verifier verdict; never implied by writes."""

    MATCHED = "MATCHED"
    MISMATCH = "MISMATCH"


def _coerce_result(value: object) -> ExecutionResultStatus:
    """Coerce a raw string to ``ExecutionResultStatus``, rejecting unknowns."""
    if isinstance(value, ExecutionResultStatus):
        return value
    if isinstance(value, str):
        try:
            return ExecutionResultStatus(value.strip().upper())
        except ValueError as exc:
            raise ValueError(f"Unknown execution result {value!r}.") from exc
    raise TypeError(
        "Field 'result' must be an ExecutionResultStatus or result name, "
        f"got {type(value).__name__}."
    )


def _coerce_verdict(value: object) -> PostVerifyVerdict:
    """Coerce a raw string to ``PostVerifyVerdict``, rejecting unknowns."""
    if isinstance(value, PostVerifyVerdict):
        return value
    if isinstance(value, str):
        try:
            return PostVerifyVerdict(value.strip().upper())
        except ValueError as exc:
            raise ValueError(f"Unknown post-verify verdict {value!r}.") from exc
    raise TypeError(
        "Field 'post_verify' must be a PostVerifyVerdict or verdict name, "
        f"got {type(value).__name__}."
    )


def _require_id(field_name: str, value: object) -> str:
    """Validate a non-empty identifier and return it stripped."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Field '{field_name}' must be a non-empty string.")
    return value.strip()


@dataclass(frozen=True)
class ExecutionResult:
    """Immutable fact of one executor run.

    ``execution_id`` is deterministic over the idempotency key, so crash
    replays address the same record instead of minting duplicates.
    ``external_reference`` is the adapter entry id when a write booked
    (None when rejected before any side effect). ``post_verify`` is
    ``MISMATCH`` whenever no independent verification passed — including
    every ``REJECTED`` outcome, which never reaches verification.
    """

    execution_id: str
    result: ExecutionResultStatus
    external_reference: str | None = None
    post_verify: PostVerifyVerdict = PostVerifyVerdict.MISMATCH
    idempotency_key: str = ""
    exception_id: str = ""

    def __post_init__(self) -> None:
        """Enforce identifiers, vocabularies, and the reference coupling."""
        object.__setattr__(self, "execution_id", _require_id("execution_id", self.execution_id))
        object.__setattr__(self, "result", _coerce_result(self.result))
        object.__setattr__(self, "post_verify", _coerce_verdict(self.post_verify))
        reference: Any = self.external_reference
        if reference is not None:
            object.__setattr__(
                self, "external_reference", _require_id("external_reference", reference)
            )
        for field_name in ("idempotency_key", "exception_id"):
            raw: Any = getattr(self, field_name)
            if raw:
                object.__setattr__(self, field_name, _require_id(field_name, raw))
