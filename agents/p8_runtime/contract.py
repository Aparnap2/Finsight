"""P8-01 provider-neutral model runtime contract.

Boundary types for invoking a model behind a single adapter seam:
untrusted raw text enters, explicit validation produces structure,
budgets bound the work, failures classify deterministically, retries
stay capped, and evaluation observes without authorizing.

This module performs no network, filesystem, or database I/O, mints
no financial facts or evidence, and references no P7 result types.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "Budget",
    "BudgetExhaustedError",
    "BudgetUsage",
    "EvaluationObservation",
    "FailureClass",
    "FailureKind",
    "InvalidStructuredOutputError",
    "ModelRequest",
    "ModelResponse",
    "Provenance",
    "ProviderAdapter",
    "RawModelOutput",
    "RetryExhaustedError",
    "RetryPolicy",
    "RunIdentity",
    "RuntimeConfig",
    "StructuredModelOutput",
    "call_with_retry",
    "check_budget",
    "classify_failure",
    "compute_input_fingerprint",
    "is_retryable",
    "replay_run",
    "validate_raw_output",
]

_FORBID_EXTRA = ConfigDict(extra="forbid")


class InvalidStructuredOutputError(Exception):
    """Raised when raw model text fails strict structural validation."""


class BudgetExhaustedError(Exception):
    """Raised when any budget dimension is exceeded before further work."""


class RetryExhaustedError(Exception):
    """Raised when bounded retries are consumed without success."""


class RuntimeConfig(BaseModel):
    """Neutral knobs for one model call (labels and limits only)."""

    model_config = _FORBID_EXTRA

    max_tokens: int = Field(ge=0)
    timeout_ms: int = Field(ge=0)


class ModelRequest(BaseModel):
    """Provider-neutral request: what to work on, never how to reach it."""

    model_config = _FORBID_EXTRA

    situation_id: str = Field(min_length=1)
    input_text: str = Field(min_length=1)
    prompt_context_id: str = Field(min_length=1)


class Provenance(BaseModel):
    """Observational metadata describing a response (never authority)."""

    model_config = _FORBID_EXTRA

    prompt_context_id: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    model: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    version: str = Field(min_length=1)
    runtime_config: RuntimeConfig
    started_at: datetime
    completed_at: datetime
    run_id: str = Field(min_length=1)


class ModelResponse(BaseModel):
    """Provider-neutral response carrying data plus provenance metadata."""

    model_config = _FORBID_EXTRA

    run_id: str = Field(min_length=1)
    output_text: str
    token_usage: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    provenance: Provenance


class RawModelOutput(BaseModel):
    """Untrusted raw model text; structure is NOT implied."""

    model_config = _FORBID_EXTRA

    run_id: str = Field(min_length=1)
    text: str
    received_at: datetime


class StructuredModelOutput(BaseModel):
    """Validated structure; reachable only via ``validate_raw_output``."""

    model_config = _FORBID_EXTRA

    summary: str = Field(min_length=1)
    findings: list[str] = Field(default_factory=list)


def validate_raw_output(raw: RawModelOutput) -> StructuredModelOutput:
    """Validate untrusted raw text into strict structure.

    Rejects malformed JSON, non-object payloads, missing or mistyped
    fields, and unknown keys. Injection text stays inert data: it
    either fails here or lands in plain string fields only.
    """
    try:
        parsed: Any = json.loads(raw.text)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidStructuredOutputError("raw output is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise InvalidStructuredOutputError("raw output must be a JSON object")
    allowed = {"summary", "findings"}
    unknown = set(parsed) - allowed
    if unknown:
        raise InvalidStructuredOutputError(f"unknown keys: {sorted(unknown)}")
    summary = parsed.get("summary")
    if not isinstance(summary, str) or not summary:
        raise InvalidStructuredOutputError("summary must be a non-empty string")
    findings = parsed.get("findings", [])
    if not isinstance(findings, list) or not all(isinstance(f, str) for f in findings):
        raise InvalidStructuredOutputError("findings must be a list of strings")
    return StructuredModelOutput(summary=summary, findings=findings)


def _reject_non_finite(value: float, name: str) -> float:
    """Reject NaN/infinity so no unlimited bound can slip through."""
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


class Budget(BaseModel):
    """All execution bounds; every dimension required and finite."""

    model_config = _FORBID_EXTRA

    max_model_calls: int = Field(ge=0)
    max_tokens: int = Field(ge=0)
    max_tool_calls: int = Field(ge=0)
    deadline_seconds: float = Field(ge=0)
    max_retries: int = Field(ge=0)

    @field_validator("max_model_calls", "max_tokens", "max_tool_calls", "max_retries",
                       mode="before")
    @classmethod
    def _reject_bool_bounds(cls, value: Any) -> Any:
        """Reject bools so True/False never pose as numeric bounds."""
        if isinstance(value, bool):
            raise ValueError("budget bound must be an int, not bool")
        return value

    @field_validator("deadline_seconds")
    @classmethod
    def _finite_deadline(cls, value: float) -> float:
        """Require a finite deadline (no unlimited wait)."""
        return _reject_non_finite(value, "deadline_seconds")


class BudgetUsage(BaseModel):
    """Observed consumption measured against a ``Budget``."""

    model_config = _FORBID_EXTRA

    model_calls: int = Field(ge=0)
    tokens: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    elapsed_seconds: float = Field(ge=0)
    retries: int = Field(ge=0)

    @field_validator("model_calls", "tokens", "tool_calls", "retries", mode="before")
    @classmethod
    def _reject_bool_usage(cls, value: Any) -> Any:
        """Reject bools so True/False never pose as observed counts."""
        if isinstance(value, bool):
            raise ValueError("usage count must be an int, not bool")
        return value

    @field_validator("elapsed_seconds")
    @classmethod
    def _finite_elapsed(cls, value: float) -> float:
        """Require a finite elapsed measurement."""
        return _reject_non_finite(value, "elapsed_seconds")


def check_budget(budget: Budget, usage: BudgetUsage) -> None:
    """Refuse further work when any dimension exceeds its bound.

    Pure check: passes silently in-budget, raises typed refusal over.
    """
    if (
        usage.model_calls > budget.max_model_calls
        or usage.tokens > budget.max_tokens
        or usage.tool_calls > budget.max_tool_calls
        or usage.elapsed_seconds > budget.deadline_seconds
        or usage.retries > budget.max_retries
    ):
        raise BudgetExhaustedError("budget exhausted")


class FailureKind(StrEnum):
    """Enumerated ways a model call can fail (fixed set)."""

    TIMEOUT = "timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    RATE_LIMITED = "rate_limited"
    MALFORMED_RESPONSE = "malformed_response"
    INVALID_STRUCTURED_OUTPUT = "invalid_structured_output"
    BUDGET_EXHAUSTED = "budget_exhausted"
    POLICY_REFUSAL = "policy_refusal"
    SAFETY_INJECTION_REJECTION = "safety_injection_rejection"


class FailureClass(StrEnum):
    """Deterministic class: retryable transient vs final terminal."""

    TRANSIENT = "transient"
    TERMINAL = "terminal"


_TRANSIENT_KINDS = frozenset(
    {
        FailureKind.TIMEOUT,
        FailureKind.PROVIDER_UNAVAILABLE,
        FailureKind.RATE_LIMITED,
    }
)


def classify_failure(kind: FailureKind) -> FailureClass:
    """Classify a failure kind deterministically (pure function)."""
    if kind in _TRANSIENT_KINDS:
        return FailureClass.TRANSIENT
    return FailureClass.TERMINAL


def is_retryable(kind: FailureKind) -> bool:
    """Report retry eligibility exactly from classification."""
    return classify_failure(kind) is FailureClass.TRANSIENT


class RetryPolicy(BaseModel):
    """Bounded retry allowance; required and finite."""

    model_config = _FORBID_EXTRA

    max_retries: int = Field(ge=0)

    @field_validator("max_retries", mode="before")
    @classmethod
    def _reject_bool_retries(cls, value: Any) -> Any:
        """Reject bools so True/False never pose as a retry bound."""
        if isinstance(value, bool):
            raise ValueError("max_retries must be an int, not bool")
        return value


def call_with_retry(
    policy: RetryPolicy,
    operation: Callable[[], ModelResponse],
    kind_of: Callable[[BaseException], FailureKind],
) -> ModelResponse:
    """Run an operation with bounded, classification-gated retries.

    Only transient failures retry, at most ``policy.max_retries`` times;
    terminal failures (budget, policy, safety, malformed) raise at once.
    Fallback repeats the same neutral call — authority-neutral by shape.
    """
    last_error: BaseException | None = None
    for _ in range(policy.max_retries + 1):
        try:
            return operation()
        except (BudgetExhaustedError, InvalidStructuredOutputError):
            raise
        except Exception as exc:  # noqa: BLE001 - classified below, never swallowed
            if not is_retryable(kind_of(exc)):
                raise
            last_error = exc
    raise RetryExhaustedError("bounded retries exhausted") from last_error


class RunIdentity(BaseModel):
    """Identifies one run: id plus deterministic input fingerprint."""

    model_config = _FORBID_EXTRA

    run_id: str = Field(min_length=1)
    input_fingerprint: str = Field(min_length=1)


def compute_input_fingerprint(payload: Mapping[str, Any]) -> str:
    """Fingerprint a payload deterministically (same input, same string).

    Canonical JSON (sorted keys, compact separators) hashed with
    SHA-256; Decimal values render via ``str`` to avoid float drift.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def replay_run(identity: RunIdentity) -> ModelResponse | None:
    """Replay a recorded run observationally (no financial effects).

    The stateless contract holds no store, so there is nothing to
    replay here: always returns ``None``. Concrete harnesses may
    override this seam with fixture-backed playback behind it.
    """
    _ = identity
    return None


class EvaluationObservation(BaseModel):
    """Structured observation for evaluation; carries no authority."""

    model_config = _FORBID_EXTRA

    run_id: str = Field(min_length=1)
    failure_kind: FailureKind | None = None
    latency_ms: int = Field(ge=0)
    token_usage: int = Field(ge=0)


class ProviderAdapter(Protocol):
    """Sole provider seam: map a neutral request to a neutral response."""

    def complete(self, request: ModelRequest, config: RuntimeConfig) -> ModelResponse:
        """Complete one model call under the given neutral config."""
        ...  # pragma: no cover


_DECIMAL_ZERO = Decimal(0)
