"""Frozen typed contracts for the P4.3 deterministic capability executor.

:class:`CapabilityRequest` is the single-call input assembled in deterministic
code before any capability runs: a closed capability name, a string-only
bounded args mapping, the tenant scope, and the round index. It authorizes
nothing on its own; execution belongs exclusively to
:class:`agents.capabilities.executor.CapabilityExecutor`.

:class:`CapabilityOutcome` pairs the reused :class:`ToolResult` envelope
(:mod:`shared.utils.tools.tool_result`, imported exactly, never redefined)
with call provenance (capability, order index, tenant, fingerprint, dedupe
flag, audit note). Bounded per-call failures are represented as data
(``success=False`` with a zero-row ``ToolResult``), never as raised
exceptions, except for fatal whole-run rejections.

This module imports nothing from ``apps/``, ``finance`` execution paths,
or any LLM framework. Strict Pydantic applies throughout.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agents.investigation.plan import (
    FROZEN_CAPABILITY_ALLOWLIST,
    MAX_ARG_KEY_CHARS,
    MAX_ARG_VALUE_CHARS,
    MAX_ARGS_PER_CALL,
    CapabilityName,
)
from shared.utils.tools.tool_result import ToolResult

MAX_EXECUTOR_CALLS = 8
"""Hard ceiling on calls per run; mirrors ``MAX_CAPABILITY_CALLS`` (P4.2)."""

MIN_ROUND_INDEX = 0
MAX_ROUND_INDEX = 10
"""Bounds for the planner round index carried on each request."""

MAX_TENANT_ID_CHARS = 128
"""Bound for tenant identifiers on executor-facing contracts."""


class ExecutorRejectedError(ValueError):
    """Whole-run rejection: shape, allowlist, tenant, or forbidden-arg failure.

    Raised before any capability executes (zero partial execution). Callers
    degrade deterministically to the P3-template path.
    """


class CapabilityRequest(BaseModel):
    """One deterministic capability invocation request (selection + scope)."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    capability: CapabilityName
    args: dict[str, str] = Field(default_factory=dict)
    tenant_id: str = Field(min_length=1, max_length=MAX_TENANT_ID_CHARS)
    round_index: int = Field(default=0, ge=MIN_ROUND_INDEX, le=MAX_ROUND_INDEX)

    @field_validator("args")
    @classmethod
    def _check_args(cls, value: dict[str, str]) -> dict[str, str]:
        """Enforce a string-only bounded args mapping (mirrors P4.2)."""
        if len(value) > MAX_ARGS_PER_CALL:
            raise ValueError(f"args holds {len(value)} entries; max is {MAX_ARGS_PER_CALL}.")
        for key, item in value.items():
            if not isinstance(key, str) or not isinstance(item, str):
                raise ValueError("Every args key and value must be a string.")
            if not key.strip():
                raise ValueError("Every args key must be a non-empty string.")
            if len(key) > MAX_ARG_KEY_CHARS:
                raise ValueError(f"args key {key!r} exceeds {MAX_ARG_KEY_CHARS} chars.")
            if len(item) > MAX_ARG_VALUE_CHARS:
                raise ValueError(f"args[{key!r}] exceeds {MAX_ARG_VALUE_CHARS} chars.")
        return value

    @field_validator("tenant_id")
    @classmethod
    def _check_tenant(cls, value: str) -> str:
        """Reject blank tenant scopes."""
        if not value.strip():
            raise ValueError("tenant_id must be a non-blank string.")
        return value

    @classmethod
    def from_mapping(
        cls,
        capability: str,
        args: Mapping[str, str],
        tenant_id: str,
        round_index: int = 0,
    ) -> CapabilityRequest:
        """Build a request from a plain mapping (defensive copy of args).

        Args:
            capability: Closed capability name (validated by the schema).
            args: String-only bounded args (copied; non-string values fail).
            tenant_id: Tenant scope the lookup executes under.
            round_index: Planner round index for audit provenance.

        Returns:
            A validated frozen :class:`CapabilityRequest`.
        """
        return cls(
            capability=capability,  # type: ignore[arg-type]
            args=dict(args),
            tenant_id=tenant_id,
            round_index=round_index,
        )


class CapabilityOutcome(BaseModel):
    """One executed call: the ``ToolResult`` evidence plus call provenance."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    capability: CapabilityName
    order_index: int = Field(ge=0)
    tenant_id: str = Field(min_length=1, max_length=MAX_TENANT_ID_CHARS)
    result: ToolResult
    success: bool = True
    error_code: str | None = None
    deduped: bool = False
    audit_note: str = Field(default="", max_length=512)

    @field_validator("tenant_id")
    @classmethod
    def _check_tenant(cls, value: str) -> str:
        """Reject blank tenant scopes."""
        if not value.strip():
            raise ValueError("tenant_id must be a non-blank string.")
        return value


CapabilityLiteral = Literal[
    "get_stripe_payment",
    "get_stripe_refunds",
    "get_qb_transaction",
    "get_expected_state",
    "search_gmail",
]
"""Closed capability vocabulary (mirrors the frozen allowlist)."""

_FROZEN_SET = frozenset(FROZEN_CAPABILITY_ALLOWLIST)


def is_allowlisted(name: object) -> bool:
    """Return True when ``name`` is a member of the frozen allowlist."""
    return isinstance(name, str) and name in _FROZEN_SET


def args_fingerprint(capability: str, args: Mapping[str, Any]) -> str:
    """Compute a deterministic fingerprint for dedupe of identical calls."""
    import hashlib

    ordered = ",".join(f"{key}={args[key]}" for key in sorted(args))
    raw = f"{capability}:{ordered}"
    return hashlib.sha256(raw.encode()).hexdigest()


__all__ = [
    "MAX_EXECUTOR_CALLS",
    "MAX_ROUND_INDEX",
    "MAX_TENANT_ID_CHARS",
    "MIN_ROUND_INDEX",
    "CapabilityLiteral",
    "CapabilityOutcome",
    "CapabilityRequest",
    "ExecutorRejectedError",
    "args_fingerprint",
    "is_allowlisted",
]
