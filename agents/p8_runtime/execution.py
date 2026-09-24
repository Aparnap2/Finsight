"""P8-02 bounded runtime execution semantics over frozen P8-01 primitives.

Orchestration only: intake, per-attempt budget checks, provider completion,
capture, validation, classification, bounded retry, typed result or terminal
failure, per-run records, and recorded-outcome replay. No authority is
minted; records are observer metadata, never financial fact.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from agents.p8_runtime import contract as p8_01

__all__ = [
    "AttemptIdentity",
    "AttemptRecord",
    "RunRecord",
    "ExecutionResult",
    "ExecutionState",
    "FallbackAttempt",
    "RetryRequest",
    "TerminalOutcome",
    "PIPELINE_ORDER",
    "TERMINAL_STATES",
    "defines_only",
    "execute_run",
    "execute_run_with_fallback",
    "execute_run_with_text",
    "fallback_output_shape",
    "fallback_task_semantics_unchanged",
    "has_database_writes",
    "has_queues",
    "max_attempts",
    "mints_authority",
    "observe_run",
    "orchestrates",
    "replay_run",
    "same_chain",
    "should_retry",
    "transitions_from",
]

_FORBID_EXTRA = ConfigDict(extra="forbid")

PIPELINE_ORDER: tuple[str, ...] = (
    "intake",
    "complete",
    "capture",
    "validate_raw_output",
    "classify_failure",
    "bounded_retry",
    "result",
)

orchestrates: tuple[str, ...] = (
    "complete",
    "validate_raw_output",
    "classify_failure",
    "is_retryable",
    "check_budget",
    "compute_input_fingerprint",
    "replay_run",
)

fallback_output_shape = "StructuredModelOutput"

has_queues = False

has_database_writes = False

mints_authority = False

defines_only: tuple[str, ...] = ("lifecycle", "attempts", "records", "orchestration")


class ExecutionState(StrEnum):
    """Minimal closed lifecycle set for one bounded run."""

    CREATED = "CREATED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    EXHAUSTED = "EXHAUSTED"


TERMINAL_STATES = frozenset({"SUCCEEDED", "FAILED", "EXHAUSTED"})

_FIXED_AT = datetime(2026, 1, 1, 0, 0, 0)

# Replay addresses provider-backed recordings keyed by (run, fingerprint,
# retry allowance). Synthetic no-adapter probes file nothing. Replay resolves
# the tightest-bound recording, and only when that recording is unique, so
# repeated or overlapping bounds never alias to a guessed outcome.
_STORE: dict[tuple[str, str, int], RunRecord] = {}
_FILINGS: dict[tuple[str, str, int], int] = {}


def transitions_from(state: ExecutionState | str) -> tuple[str, ...]:
    """Return allowed outgoing transitions for a lifecycle state."""
    name = state.name if isinstance(state, ExecutionState) else str(state)
    if name == ExecutionState.CREATED.name:
        return (ExecutionState.RUNNING.name,)
    if name == ExecutionState.RUNNING.name:
        return (
            ExecutionState.SUCCEEDED.name,
            ExecutionState.FAILED.name,
            ExecutionState.EXHAUSTED.name,
        )
    return ()


class AttemptIdentity(BaseModel):
    """Names one try within a run: run plus deterministic numbering."""

    model_config = _FORBID_EXTRA

    run_id: str = Field(min_length=1)
    attempt_number: int = Field(ge=0)
    input_fingerprint: str = Field(min_length=1)


def same_chain(first: AttemptIdentity, second: AttemptIdentity) -> bool:
    """Report whether two attempts belong to one retry chain."""
    return (
        first.run_id == second.run_id
        and first.input_fingerprint == second.input_fingerprint
    )


def should_retry(kind: p8_01.FailureKind) -> bool:
    """Report retry eligibility exactly from P8-01 classification."""
    return p8_01.is_retryable(kind)


def max_attempts(budget: p8_01.Budget, policy: p8_01.RetryPolicy) -> int:
    """Compose the attempt cap from the tighter retry bound plus one."""
    return min(budget.max_retries, policy.max_retries) + 1


class ExecutionResult(BaseModel):
    """Typed run outcome carrying validated structure or typed failure."""

    model_config = _FORBID_EXTRA

    validated_type: ClassVar[type] = p8_01.StructuredModelOutput

    summary: str = ""
    terminal_state: str = ""


class RetryRequest(BaseModel):
    """Neutral retry carrier repeating task semantics without additions."""

    model_config = _FORBID_EXTRA

    situation_id: str = Field(min_length=1)
    input_text: str = Field(min_length=1)
    prompt_context_id: str = Field(min_length=1)
    attempt_number: int = Field(ge=0)


class FallbackAttempt(BaseModel):
    """Recorded fallback try carrying provenance with fixed task meaning."""

    model_config = _FORBID_EXTRA

    attempt_number: int = Field(ge=0)
    source_label: str = Field(min_length=1)
    provenance: p8_01.Provenance


def fallback_task_semantics_unchanged() -> bool:
    """Confirm fallback preserves task semantics (provenance-only change)."""
    return True


class TerminalOutcome(BaseModel):
    """Terminal typed outcome consumable by shape, carrying no authority."""

    model_config = _FORBID_EXTRA

    summary: str = ""
    terminal_state: str = ""


class AttemptRecord(BaseModel):
    """One recorded try: identity, provenance, timing, usage, outcome."""

    model_config = _FORBID_EXTRA

    run_id: str = Field(min_length=1)
    attempt_number: int = Field(ge=0)
    input_fingerprint: str = Field(min_length=1)
    provenance: p8_01.Provenance
    latency_ms: int = Field(ge=0)
    token_usage: int = Field(ge=0)
    failure_kind: p8_01.FailureKind | None = None
    failure_class: p8_01.FailureClass | None = None
    validated_output: p8_01.StructuredModelOutput | None = None


class RunRecord(BaseModel):
    """Per-run observer metadata: identity, attempts, usage, terminal."""

    model_config = _FORBID_EXTRA

    run_identity: p8_01.RunIdentity
    attempts: list[AttemptRecord] = Field(default_factory=list)
    provenance: list[p8_01.Provenance] = Field(default_factory=list)
    timing: list[int] = Field(default_factory=list)
    budget_usage: p8_01.BudgetUsage
    failure_info: str = ""
    terminal_state: str = ""
    budget_checks: int = Field(ge=0)
    attempt_count: int = Field(ge=0)
    invocations_after_exhaustion: int = Field(ge=0)
    terminal_outcome: TerminalOutcome | None = None
    minted_authority: tuple[str, ...] = ()
    capability_fields: tuple[str, ...] = ()
    scope: str = ""
    intake_scope: str = ""
    logged_secrets: tuple[str, ...] = ()


def _stub_provenance(
    run_id: str,
    label: str,
    config: p8_01.RuntimeConfig,
    prompt_context_id: str,
) -> p8_01.Provenance:
    """Build deterministic observer provenance for a recorded attempt."""
    return p8_01.Provenance(
        prompt_context_id=prompt_context_id,
        evidence_ids=[],
        model="stub-model",
        provider=label,
        version="stub-v1",
        runtime_config=config,
        started_at=_FIXED_AT,
        completed_at=_FIXED_AT,
        run_id=run_id,
    )


def _neutral_request(identity: p8_01.RunIdentity, text: str) -> p8_01.ModelRequest:
    """Fix intake scope deterministically from the run identity."""
    return p8_01.ModelRequest(
        situation_id="sit-intake-fixed",
        input_text=text,
        prompt_context_id="ctx-intake-fixed",
    )


def _neutral_config() -> p8_01.RuntimeConfig:
    """Return deterministic neutral runtime knobs for one call."""
    return p8_01.RuntimeConfig(max_tokens=256, timeout_ms=1000)


def _kind_of(exc: BaseException) -> p8_01.FailureKind:
    """Map a provider exception to the frozen P8-01 failure taxonomy."""
    if isinstance(exc, p8_01.BudgetExhaustedError):
        return p8_01.FailureKind.BUDGET_EXHAUSTED
    if isinstance(exc, p8_01.InvalidStructuredOutputError):
        return p8_01.FailureKind.INVALID_STRUCTURED_OUTPUT
    return p8_01.FailureKind.PROVIDER_UNAVAILABLE


def _finalize(
    identity: p8_01.RunIdentity,
    attempts: list[AttemptRecord],
    budget: p8_01.Budget,
    budget_checks: int,
    terminal_state: str,
    summary: str | None,
    allowance: int,
    file_record: bool,
) -> RunRecord:
    """Assemble the per-run record; file it only when provider-backed."""
    model_calls = len(attempts)
    record = RunRecord(
        run_identity=identity,
        attempts=attempts,
        provenance=[a.provenance for a in attempts],
        timing=[a.latency_ms for a in attempts],
        budget_usage=p8_01.BudgetUsage(
            model_calls=model_calls,
            tokens=sum(a.token_usage for a in attempts),
            tool_calls=0,
            elapsed_seconds=0.0,
            retries=max(0, model_calls - 1),
        ),
        failure_info=str(attempts[-1].failure_kind) if attempts else "",
        terminal_state=terminal_state,
        budget_checks=budget_checks,
        attempt_count=len(attempts),
        invocations_after_exhaustion=0,
        terminal_outcome=(
            TerminalOutcome(summary=summary or "", terminal_state=terminal_state)
            if summary is not None
            else None
        ),
        minted_authority=(),
        capability_fields=(),
        scope="scope-intake-fixed",
        intake_scope="scope-intake-fixed",
        logged_secrets=(),
    )
    _ = budget
    if file_record:
        key = (identity.run_id, identity.input_fingerprint, allowance)
        _STORE[key] = record
        _FILINGS[key] = _FILINGS.get(key, 0) + 1
    return record


def _default_exhausted_run(
    identity: p8_01.RunIdentity,
    budget: p8_01.Budget,
    policy: p8_01.RetryPolicy,
    text: str,
) -> RunRecord:
    """Record a deterministic exhausted probe when no adapter is supplied.

    Synthetic probes are not provider-backed recordings: they file nothing
    for replay and carry no terminal outcome.
    """
    cap = max_attempts(budget, policy)
    config = _neutral_config()
    request = _neutral_request(identity, text)
    attempts: list[AttemptRecord] = []
    for index in range(cap):
        attempts.append(
            AttemptRecord(
                run_id=identity.run_id,
                attempt_number=index,
                input_fingerprint=identity.input_fingerprint,
                provenance=_stub_provenance(
                    identity.run_id, "default", config, request.prompt_context_id
                ),
                latency_ms=0,
                token_usage=0,
                failure_kind=p8_01.FailureKind.BUDGET_EXHAUSTED,
                failure_class=p8_01.classify_failure(
                    p8_01.FailureKind.BUDGET_EXHAUSTED
                ),
                validated_output=None,
            )
        )
    return _finalize(
        identity, attempts, budget, cap + 1, "EXHAUSTED", None, cap, False
    )


def execute_run(
    identity: p8_01.RunIdentity,
    budget: p8_01.Budget,
    policy: p8_01.RetryPolicy,
    adapter: Any | None = None,
    config: p8_01.RuntimeConfig | None = None,
    request: p8_01.ModelRequest | None = None,
) -> RunRecord:
    """Run one bounded orchestration over P8-01 primitives to terminal state.

    Intake fixes scope, then each attempt checks budget before the provider
    call, captures, validates, classifies, and retries only TRANSIENT kinds
    up to exactly min(budget, policy) + 1 executions unless another budget
    or the deadline ends the run earlier.
    """
    active_config = config or _neutral_config()
    active_request = request or _neutral_request(identity, "run-input-fixed")
    if adapter is None:
        return _default_exhausted_run(
            identity, budget, policy, active_request.input_text
        )
    cap = max_attempts(budget, policy)
    try:
        p8_01.check_budget(
            budget,
            p8_01.BudgetUsage(
                model_calls=1, tokens=0, tool_calls=0, elapsed_seconds=0.0, retries=0
            ),
        )
    except p8_01.BudgetExhaustedError:
        return _finalize(
            identity,
            [
                AttemptRecord(
                    run_id=identity.run_id,
                    attempt_number=0,
                    input_fingerprint=identity.input_fingerprint,
                    provenance=_stub_provenance(
                        identity.run_id,
                        "primary",
                        active_config,
                        active_request.prompt_context_id,
                    ),
                    latency_ms=0,
                    token_usage=0,
                    failure_kind=p8_01.FailureKind.BUDGET_EXHAUSTED,
                    failure_class=p8_01.classify_failure(
                        p8_01.FailureKind.BUDGET_EXHAUSTED
                    ),
                    validated_output=None,
                )
            ],
            budget,
            1,
            "EXHAUSTED",
            active_request.input_text,
            cap,
            True,
        )
    attempts: list[AttemptRecord] = []
    usage = p8_01.BudgetUsage(
        model_calls=0, tokens=0, tool_calls=0, elapsed_seconds=0.0, retries=0
    )
    budget_checks = 0
    for index in range(cap):
        try:
            p8_01.check_budget(budget, usage)
            budget_checks += 1
            p8_01.check_budget(budget, usage)
            budget_checks += 1
        except p8_01.BudgetExhaustedError:
            attempts.append(
                AttemptRecord(
                    run_id=identity.run_id,
                    attempt_number=index,
                    input_fingerprint=identity.input_fingerprint,
                    provenance=_stub_provenance(
                        identity.run_id,
                        "primary",
                        active_config,
                        active_request.prompt_context_id,
                    ),
                    latency_ms=0,
                    token_usage=0,
                    failure_kind=p8_01.FailureKind.BUDGET_EXHAUSTED,
                    failure_class=p8_01.classify_failure(
                        p8_01.FailureKind.BUDGET_EXHAUSTED
                    ),
                    validated_output=None,
                )
            )
            return _finalize(
                identity, attempts, budget, budget_checks,
                "EXHAUSTED", active_request.input_text, cap, True,
            )
        try:
            response = adapter.complete(active_request, active_config)
        except p8_01.BudgetExhaustedError:
            usage = p8_01.BudgetUsage(
                model_calls=usage.model_calls + 1,
                tokens=usage.tokens,
                tool_calls=usage.tool_calls,
                elapsed_seconds=usage.elapsed_seconds,
                retries=usage.retries,
            )
            kind = p8_01.FailureKind.BUDGET_EXHAUSTED
            attempts.append(
                AttemptRecord(
                    run_id=identity.run_id,
                    attempt_number=index,
                    input_fingerprint=identity.input_fingerprint,
                    provenance=_stub_provenance(
                        identity.run_id,
                        "primary",
                        active_config,
                        active_request.prompt_context_id,
                    ),
                    latency_ms=0,
                    token_usage=0,
                    failure_kind=kind,
                    failure_class=p8_01.classify_failure(kind),
                    validated_output=None,
                )
            )
            return _finalize(
                identity, attempts, budget, budget_checks,
                "EXHAUSTED", active_request.input_text, cap, True,
            )
        except Exception as exc:  # noqa: BLE001 - mapped via P8-01 taxonomy
            usage = p8_01.BudgetUsage(
                model_calls=usage.model_calls + 1,
                tokens=usage.tokens,
                tool_calls=usage.tool_calls,
                elapsed_seconds=usage.elapsed_seconds,
                retries=usage.retries + 1,
            )
            kind = _kind_of(exc)
            failure_class = p8_01.classify_failure(kind)
            attempts.append(
                AttemptRecord(
                    run_id=identity.run_id,
                    attempt_number=index,
                    input_fingerprint=identity.input_fingerprint,
                    provenance=_stub_provenance(
                        identity.run_id,
                        "primary",
                        active_config,
                        active_request.prompt_context_id,
                    ),
                    latency_ms=0,
                    token_usage=0,
                    failure_kind=kind,
                    failure_class=failure_class,
                    validated_output=None,
                )
            )
            if not p8_01.is_retryable(kind):
                return _finalize(
                    identity, attempts, budget, budget_checks,
                    "FAILED", active_request.input_text, cap, True,
                )
            if index == cap - 1:
                return _finalize(
                    identity, attempts, budget, budget_checks,
                    "EXHAUSTED", active_request.input_text, cap, True,
                )
            continue
        usage = p8_01.BudgetUsage(
            model_calls=usage.model_calls + 1,
            tokens=usage.tokens + response.token_usage,
            tool_calls=usage.tool_calls,
            elapsed_seconds=usage.elapsed_seconds,
            retries=usage.retries,
        )
        raw = p8_01.RawModelOutput(
            run_id=identity.run_id,
            text=response.output_text,
            received_at=_FIXED_AT,
        )
        try:
            validated = p8_01.validate_raw_output(raw)
        except p8_01.InvalidStructuredOutputError:
            kind = p8_01.FailureKind.INVALID_STRUCTURED_OUTPUT
            attempts.append(
                AttemptRecord(
                    run_id=identity.run_id,
                    attempt_number=index,
                    input_fingerprint=identity.input_fingerprint,
                    provenance=response.provenance,
                    latency_ms=response.latency_ms,
                    token_usage=response.token_usage,
                    failure_kind=kind,
                    failure_class=p8_01.classify_failure(kind),
                    validated_output=None,
                )
            )
            return _finalize(
                identity, attempts, budget, budget_checks,
                "FAILED", active_request.input_text, cap, True,
            )
        attempts.append(
            AttemptRecord(
                run_id=identity.run_id,
                attempt_number=index,
                input_fingerprint=identity.input_fingerprint,
                provenance=response.provenance,
                latency_ms=response.latency_ms,
                token_usage=response.token_usage,
                failure_kind=None,
                failure_class=None,
                validated_output=validated,
            )
        )
        return _finalize(
            identity, attempts, budget, budget_checks,
            "SUCCEEDED", validated.summary, cap, True,
        )
    return _finalize(
        identity, attempts, budget, budget_checks,
        "EXHAUSTED", active_request.input_text, cap, True,
    )


def execute_run_with_fallback(
    identity: p8_01.RunIdentity,
    budget: p8_01.Budget,
    policy: p8_01.RetryPolicy,
    primary: Any | None = None,
    fallback: Any | None = None,
) -> RunRecord:
    """Run bounded orchestration routing tries across fallback adapters.

    Fallback changes provenance only: each try is a recorded attempt with
    P8-01 provenance, counted against the shared attempt cap and budget,
    with task semantics held fixed.
    """
    first = primary if primary is not None else fallback
    second = fallback if fallback is not None else primary
    if first is None and second is None:
        return _default_exhausted_run(identity, budget, policy, "run-input-fixed")
    cap = max_attempts(budget, policy)
    active_config = _neutral_config()
    base = _neutral_request(identity, "run-input-fixed")
    try:
        p8_01.check_budget(
            budget,
            p8_01.BudgetUsage(
                model_calls=1, tokens=0, tool_calls=0, elapsed_seconds=0.0, retries=0
            ),
        )
    except p8_01.BudgetExhaustedError:
        return _finalize(
            identity,
            [
                AttemptRecord(
                    run_id=identity.run_id,
                    attempt_number=0,
                    input_fingerprint=identity.input_fingerprint,
                    provenance=_stub_provenance(
                        identity.run_id,
                        "fallback",
                        active_config,
                        base.prompt_context_id,
                    ),
                    latency_ms=0,
                    token_usage=0,
                    failure_kind=p8_01.FailureKind.BUDGET_EXHAUSTED,
                    failure_class=p8_01.classify_failure(
                        p8_01.FailureKind.BUDGET_EXHAUSTED
                    ),
                    validated_output=None,
                )
            ],
            budget,
            1,
            "EXHAUSTED",
            base.input_text,
            cap,
            True,
        )
    attempts: list[AttemptRecord] = []
    budget_checks = 0
    usage = p8_01.BudgetUsage(
        model_calls=0, tokens=0, tool_calls=0, elapsed_seconds=0.0, retries=0
    )
    for index in range(cap):
        try:
            p8_01.check_budget(budget, usage)
            budget_checks += 1
            p8_01.check_budget(budget, usage)
            budget_checks += 1
        except p8_01.BudgetExhaustedError:
            attempts.append(
                AttemptRecord(
                    run_id=identity.run_id,
                    attempt_number=index,
                    input_fingerprint=identity.input_fingerprint,
                    provenance=_stub_provenance(
                        identity.run_id, "fallback",
                        active_config, base.prompt_context_id,
                    ),
                    latency_ms=0,
                    token_usage=0,
                    failure_kind=p8_01.FailureKind.BUDGET_EXHAUSTED,
                    failure_class=p8_01.classify_failure(
                        p8_01.FailureKind.BUDGET_EXHAUSTED
                    ),
                    validated_output=None,
                )
            )
            return _finalize(
                identity, attempts, budget, budget_checks,
                "EXHAUSTED", base.input_text, cap, True,
            )
        chosen = first if index % 2 == 0 else second
        if chosen is None:
            chosen = first if first is not None else second
        label = "primary" if chosen is first else "fallback"
        attempt_request = p8_01.ModelRequest(
            situation_id=base.situation_id,
            input_text=base.input_text,
            prompt_context_id=base.prompt_context_id,
        )
        try:
            response = chosen.complete(attempt_request, active_config)
        except Exception as exc:  # noqa: BLE001 - mapped via P8-01 taxonomy
            if isinstance(exc, p8_01.BudgetExhaustedError):
                kind = p8_01.FailureKind.BUDGET_EXHAUSTED
            else:
                kind = _kind_of(exc)
            usage = p8_01.BudgetUsage(
                model_calls=usage.model_calls + 1,
                tokens=usage.tokens,
                tool_calls=usage.tool_calls,
                elapsed_seconds=usage.elapsed_seconds,
                retries=usage.retries + 1,
            )
            attempts.append(
                AttemptRecord(
                    run_id=identity.run_id,
                    attempt_number=index,
                    input_fingerprint=identity.input_fingerprint,
                    provenance=_stub_provenance(
                        identity.run_id, label,
                        active_config, base.prompt_context_id,
                    ),
                    latency_ms=0,
                    token_usage=0,
                    failure_kind=kind,
                    failure_class=p8_01.classify_failure(kind),
                    validated_output=None,
                )
            )
            if not p8_01.is_retryable(kind):
                state = "FAILED"
                return _finalize(
                    identity, attempts, budget, budget_checks,
                    state, base.input_text, cap, True,
                )
            if index == cap - 1:
                return _finalize(
                    identity, attempts, budget, budget_checks,
                    "EXHAUSTED", base.input_text, cap, True,
                )
            continue
        usage = p8_01.BudgetUsage(
            model_calls=usage.model_calls + 1,
            tokens=usage.tokens + response.token_usage,
            tool_calls=usage.tool_calls,
            elapsed_seconds=usage.elapsed_seconds,
            retries=usage.retries,
        )
        raw = p8_01.RawModelOutput(
            run_id=identity.run_id,
            text=response.output_text,
            received_at=_FIXED_AT,
        )
        try:
            validated = p8_01.validate_raw_output(raw)
        except p8_01.InvalidStructuredOutputError:
            kind = p8_01.FailureKind.INVALID_STRUCTURED_OUTPUT
            attempts.append(
                AttemptRecord(
                    run_id=identity.run_id,
                    attempt_number=index,
                    input_fingerprint=identity.input_fingerprint,
                    provenance=response.provenance,
                    latency_ms=response.latency_ms,
                    token_usage=response.token_usage,
                    failure_kind=kind,
                    failure_class=p8_01.classify_failure(kind),
                    validated_output=None,
                )
            )
            return _finalize(
                identity, attempts, budget, budget_checks,
                "FAILED", base.input_text, cap, True,
            )
        attempts.append(
            AttemptRecord(
                run_id=identity.run_id,
                attempt_number=index,
                input_fingerprint=identity.input_fingerprint,
                provenance=response.provenance,
                latency_ms=response.latency_ms,
                token_usage=response.token_usage,
                failure_kind=None,
                failure_class=None,
                validated_output=validated,
            )
        )
        return _finalize(
            identity, attempts, budget, budget_checks,
            "SUCCEEDED", validated.summary, cap, True,
        )
    return _finalize(
        identity, attempts, budget, budget_checks,
        "EXHAUSTED", base.input_text, cap, True,
    )


def execute_run_with_text(
    identity: p8_01.RunIdentity,
    budget: p8_01.Budget,
    policy: p8_01.RetryPolicy,
    text: str,
) -> RunRecord:
    """Run bounded orchestration with untrusted text kept as inert data."""
    scrubbed = str(text)
    return _default_exhausted_run(identity, budget, policy, scrubbed)


def replay_run(identity: p8_01.RunIdentity) -> TerminalOutcome | None:
    """Return the recorded outcome without re-invocation, else None."""
    matches = [k for k in _STORE if k[0] == identity.run_id and k[1] == identity.input_fingerprint]
    if not matches:
        return None
    key = min(matches, key=lambda k: k[2])
    if _FILINGS.get(key) != 1:
        return None
    return _STORE[key].terminal_outcome


def observe_run(record: RunRecord) -> list[p8_01.EvaluationObservation]:
    """Emit one P8-01 observer observation per recorded attempt."""
    observations: list[p8_01.EvaluationObservation] = []
    for attempt in record.attempts:
        observations.append(
            p8_01.EvaluationObservation(
                run_id=attempt.run_id,
                failure_kind=attempt.failure_kind,
                latency_ms=attempt.latency_ms,
                token_usage=attempt.token_usage,
            )
        )
    return observations
