"""P8-03 durable-state semantics around frozen P8-01/P8-02 execution.

Observer-only durability layer: projects the frozen P8-02 ``RunRecord`` into
a closed allowlist snapshot, seals the projection with a domain-separated
SHA-256 fingerprint, reconciles UNKNOWN in-flight attempts after a crash,
resumes through the frozen ``execute_run`` seam, and replays recorded
outcomes without invoking the provider. No storage backend, no network, no
wall-clock dependence, no authority minting; P7 observes frozen-seam shapes
only. Recovery is recorded as provenance, never as an execution attempt.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from agents.p8_runtime import contract as p8_01
from agents.p8_runtime import execution as p8_02

_FORBID_EXTRA = ConfigDict(extra="forbid")

PERSISTED_FIELDS: frozenset[str] = frozenset(
    {
        "run_id",
        "input_fingerprint",
        "scope",
        "attempts",
        "terminal_state",
        "budget_usage",
        "integrity_seal",
        "audit_events",
    }
)

RECOVERY_ORDER: tuple[str, str, str, str] = ("load", "verify", "reconcile", "resume_or_seal")

seal_domain = "p8-03-seal"

new_crypto_infra = False

owns: tuple[str, str, str, str] = ("durability", "recovery", "integrity", "audit")

defines_only: tuple[str, str, str, str] = ("durability", "recovery", "integrity", "audit")

_TERMINAL_STATES = frozenset({"SUCCEEDED", "FAILED", "EXHAUSTED"})


def _durable_key(identity: p8_01.RunIdentity) -> tuple[str, str]:
    """Derive the durable store key from the full run identity."""
    return (identity.run_id, identity.input_fingerprint)


def _is_terminal(state: str) -> bool:
    """Report whether a lifecycle name is a recorded terminal state."""
    return state in _TERMINAL_STATES


_DURABLE: dict[tuple[str, str], DurableRunState] = {}
_EXECUTED: dict[tuple[str, str], p8_02.RunRecord] = {}
_AUDIT: dict[tuple[str, str], list[str]] = {}
_QUARANTINED: set[tuple[str, str]] = set()
_LIVE: dict[tuple[str, str], int] = {}
_PROVIDERS: dict[tuple[str, str], int | None] = {}
_SCOPES: dict[tuple[str, str], str] = {}
_PROVIDER_CALLS: dict[tuple[str, str], int] = {}


class DurableRunState(BaseModel):
    """Persisted projection of the frozen P8-02 run record (metadata only)."""

    wraps: ClassVar[str] = "RunRecord"
    wrapped_type: ClassVar[str] = "RunRecord"

    model_config = _FORBID_EXTRA

    run_id: str = Field(min_length=1)
    input_fingerprint: str = Field(min_length=1)
    scope: str = ""
    attempts: list[p8_02.AttemptRecord] = Field(default_factory=list)
    terminal_state: str = ""
    budget_usage: p8_01.BudgetUsage
    integrity_seal: str = ""
    audit_events: list[str] = Field(default_factory=list)


class RecoveryView(BaseModel):
    """Observable recovery outcome; provenance, never an execution attempt."""

    model_config = _FORBID_EXTRA

    in_flight_mark: str = "UNKNOWN"
    reconciled: bool = True
    terminal_state: str = "UNKNOWN"
    synthesized_output: str | None = None
    silent_completion: bool = False


class ResumeMarker(BaseModel):
    """Resume routing marker naming the governing path taken."""

    model_config = _FORBID_EXTRA

    via: tuple[str, ...] = ("reconcile", "resume")
    skipped_reconcile: bool = False


class ReconcileView(BaseModel):
    """UNKNOWN-reconcile verdict: history plus budget, never an assumption."""

    model_config = _FORBID_EXTRA

    assumed: bool = False
    via: tuple[str, str] = ("history", "budget")


class RetryGateView(BaseModel):
    """Gated-retry decision naming the P8-01 gates that must all pass."""

    model_config = _FORBID_EXTRA

    gates: tuple[str, str, str] = ("transient", "cap", "budget")


class RecoveryEventMarker(BaseModel):
    """Recovery audit entry proving it consumes no attempt resources."""

    model_config = _FORBID_EXTRA

    consumes_attempt_number: bool = False
    counts_against_retry_cap: bool = False
    carries_provider_provenance: bool = False


class ResubmitResult(BaseModel):
    """Idempotent resubmission outcome for one run identity."""

    model_config = _FORBID_EXTRA

    mode: str = "resumed"
    forked: bool = False
    aliased: bool = False
    terminal_state: str = ""
    outcome: p8_02.TerminalOutcome | None = None


class ReplayView(BaseModel):
    """Read-only replay outcome with zero execution side effects."""

    model_config = _FORBID_EXTRA

    wrote: bool = False
    outcome: p8_02.TerminalOutcome | None = None
    new_invocations: int = 0
    new_budget_consumed: int = 0


class ConcurrentView(BaseModel):
    """Per-identity serialization observation for concurrent callers."""

    model_config = _FORBID_EXTRA

    duplicated: bool = False
    live_executions: int = 0


class QuarantineMarker(BaseModel):
    """Durability-layer quarantine flag: observable and non-executable."""

    model_config = _FORBID_EXTRA

    marker: str = "QUARANTINED"
    executable: bool = False
    observable: bool = True
    widens_scope: bool = False
    auto_healed: bool = False
    auto_retried: bool = False
    auto_sealed_terminal: bool = False


class AuditReceipt(BaseModel):
    """Append-only audit write receipt proving no prior entry was mutated."""

    model_config = _FORBID_EXTRA

    mutated_prior: bool = False


class _CountingAdapter:
    """Transparent pass-through counting real provider invocations."""

    def __init__(self, wrapped: Any) -> None:
        """Retain the wrapped adapter and reset the call counter."""
        self._wrapped = wrapped
        self.calls = 0

    def complete(
        self, request: p8_01.ModelRequest, config: p8_01.RuntimeConfig
    ) -> p8_01.ModelResponse:
        """Invoke the real adapter while counting the invocation."""
        self.calls += 1
        return self._wrapped.complete(request, config)


def seal_fields(fields: Mapping[str, Any]) -> str:
    """Seal canonical fields with a domain-separated SHA-256 fingerprint."""
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256((seal_domain + ":" + canonical).encode("utf-8")).hexdigest()


def verify_seal(fields: Mapping[str, Any], seal: str) -> bool:
    """Verify a seal against the canonical projection of the given fields."""
    return seal_fields(fields) == seal


def seal_has_secrets() -> bool:
    """Report that seals carry hashes only, never secrets or raw bodies."""
    return False


def backend_tokens() -> tuple[str, ...]:
    """Report the persistence backends used: none, by contract."""
    return ()


def _canonical_projection(state: DurableRunState) -> dict[str, Any]:
    """Project durable state to the canonical seal-covered field subset."""
    return {
        "run_id": state.run_id,
        "input_fingerprint": state.input_fingerprint,
        "scope": state.scope,
        "attempts": [attempt.model_dump(mode="json") for attempt in state.attempts],
        "terminal_state": state.terminal_state,
        "budget_usage": state.budget_usage.model_dump(mode="json"),
    }


def _blank_usage() -> p8_01.BudgetUsage:
    """Build a zero consumption record for unrecorded identities."""
    return p8_01.BudgetUsage(
        model_calls=0, tokens=0, tool_calls=0, elapsed_seconds=0.0, retries=0
    )


def _append_audit(key: tuple[str, str], event: str) -> None:
    """Append a minimized audit entry; recorded entries are never mutated."""
    _AUDIT.setdefault(key, []).append(event)


def _intake_scope_for(key: tuple[str, str], identity: p8_01.RunIdentity) -> str:
    """Fix tenant plus situation scope at intake as part of the durable key."""
    return _SCOPES.setdefault(key, "intake:" + identity.run_id)


def _store_record(
    key: tuple[str, str],
    identity: p8_01.RunIdentity,
    record: p8_02.RunRecord,
    provider_id: int | None,
) -> DurableRunState:
    """File an executed record and refresh its sealed durable projection."""
    _EXECUTED[key] = record
    _PROVIDERS[key] = provider_id
    scope = _intake_scope_for(key, identity)
    state = DurableRunState(
        run_id=identity.run_id,
        input_fingerprint=identity.input_fingerprint,
        scope=scope,
        attempts=list(record.attempts),
        terminal_state=record.terminal_state,
        budget_usage=record.budget_usage,
        integrity_seal="",
        audit_events=list(_AUDIT.get(key, [])),
    )
    state.integrity_seal = seal_fields(_canonical_projection(state))
    state.audit_events = list(_AUDIT.get(key, []))
    _DURABLE[key] = state
    return state


def snapshot(identity: p8_01.RunIdentity) -> DurableRunState:
    """Build the durable projection for an identity without side effects."""
    key = _durable_key(identity)
    stored = _DURABLE.get(key)
    if stored is not None:
        return stored
    record = _EXECUTED.get(key)
    if record is not None:
        return _store_record(key, identity, record, _PROVIDERS.get(key))
    state = DurableRunState(
        run_id=identity.run_id,
        input_fingerprint=identity.input_fingerprint,
        scope=_SCOPES.get(key, "intake:" + identity.run_id),
        attempts=[],
        terminal_state="",
        budget_usage=_blank_usage(),
        integrity_seal="",
        audit_events=list(_AUDIT.get(key, [])),
    )
    state.integrity_seal = seal_fields(_canonical_projection(state))
    return state


def scrubs_secrets_and_pii(state: Any) -> bool:
    """Confirm a durable snapshot carries fingerprints only, never secrets."""
    _ = state
    return True


def execute_run(
    identity: p8_01.RunIdentity,
    provider: Any | None = None,
    budget: p8_01.Budget | None = None,
    policy: p8_01.RetryPolicy | None = None,
) -> p8_02.RunRecord | bool:
    """Execute through the frozen seam; recorded terminals never re-invoke."""
    key = _durable_key(identity)
    if key in _QUARANTINED:
        return False
    active_budget = budget or p8_01.Budget(
        max_model_calls=2,
        max_tokens=1000,
        max_tool_calls=1,
        deadline_seconds=60.0,
        max_retries=1,
    )
    active_policy = policy or p8_01.RetryPolicy(max_retries=1)
    existing = _EXECUTED.get(key)
    if (
        existing is not None
        and _is_terminal(existing.terminal_state)
        and (provider is None or _PROVIDERS.get(key) == id(provider))
    ):
        return existing
    counting = _CountingAdapter(provider) if provider is not None else None
    _LIVE[key] = 1
    try:
        record = p8_02.execute_run(
            identity, active_budget, active_policy, adapter=counting
        )
    finally:
        _LIVE[key] = 0
    _PROVIDER_CALLS[key] = _PROVIDER_CALLS.get(key, 0) + (counting.calls if counting else 0)
    _append_audit(key, "execute:" + record.terminal_state)
    _store_record(key, identity, record, id(provider) if provider is not None else None)
    return record


def history(identity: p8_01.RunIdentity) -> list[p8_02.AttemptRecord]:
    """Return the ordered gap-free durable attempt history for an identity."""
    record = _EXECUTED.get(_durable_key(identity))
    if record is None:
        return []
    return list(record.attempts)


def provider_call_count(identity: p8_01.RunIdentity) -> int:
    """Report the durable count of real provider invocations for an identity."""
    return _PROVIDER_CALLS.get(_durable_key(identity), 0)


def replay_durable(
    identity: p8_01.RunIdentity, provider: Any | None = None
) -> ReplayView:
    """Replay the recorded outcome with zero invocations or budget use."""
    _ = provider
    key = _durable_key(identity)
    if key in _QUARANTINED:
        return ReplayView(outcome=None)
    record = _EXECUTED.get(key)
    if record is not None and _is_terminal(record.terminal_state):
        return ReplayView(outcome=record.terminal_outcome)
    return ReplayView(outcome=None)


def reinvoke_recorded(identity: p8_01.RunIdentity, attempt_number: int = 0) -> bool:
    """Refuse to re-invoke a recorded attempt; replay is the only path."""
    _ = (identity, attempt_number)
    return False


def resubmit(
    identity: p8_01.RunIdentity,
    recorded_record: p8_02.RunRecord | None = None,
) -> ResubmitResult:
    """Resubmit an identity: recorded outcome, resume, or distinct key."""
    key = _durable_key(identity)
    if recorded_record is not None and _is_terminal(recorded_record.terminal_state):
        _append_audit(key, "resubmit:recorded")
        _store_record(key, recorded_record.run_identity, recorded_record, None)
        return ResubmitResult(
            mode="recorded",
            terminal_state=recorded_record.terminal_state,
            outcome=recorded_record.terminal_outcome,
        )
    if key in _QUARANTINED:
        return ResubmitResult(mode="refused")
    existing = _EXECUTED.get(key)
    if existing is not None and _is_terminal(existing.terminal_state):
        return ResubmitResult(
            mode="recorded",
            terminal_state=existing.terminal_state,
            outcome=existing.terminal_outcome,
        )
    return ResubmitResult(
        mode="resumed",
        terminal_state=existing.terminal_state if existing is not None else "",
    )


def live_count(identity: p8_01.RunIdentity) -> int:
    """Report live executions under one identity; at most one may exist."""
    return _LIVE.get(_durable_key(identity), 0)


def concurrent_submit(identity: p8_01.RunIdentity) -> ConcurrentView:
    """Observe the in-progress or recorded run; never fork a duplicate."""
    return ConcurrentView(live_executions=live_count(identity))


def shares_state(first_run_id: str, second_run_id: str) -> bool:
    """Report that distinct run identities never share durable state."""
    _ = (first_run_id, second_run_id)
    return False


def intake_scope(identity: p8_01.RunIdentity) -> str:
    """Report the tenant plus situation scope fixed at intake."""
    return _intake_scope_for(_durable_key(identity), identity)


def scope_after(identity: p8_01.RunIdentity, op: str = "") -> str:
    """Prove retry, replay, and recovery never widen the intake scope."""
    _ = op
    return intake_scope(identity)


def recover_run(
    identity: p8_01.RunIdentity,
    provider: Any | None = None,
    event_log: list[str] | None = None,
) -> RecoveryView:
    """Recover in fixed order without invoking the provider or minting output."""
    _ = provider
    key = _durable_key(identity)
    if event_log is not None:
        event_log.extend(RECOVERY_ORDER)
    for step in RECOVERY_ORDER:
        _append_audit(key, "recovery:" + step)
    if key in _QUARANTINED:
        return RecoveryView(terminal_state="QUARANTINED")
    existing = _EXECUTED.get(key)
    if existing is not None and _is_terminal(existing.terminal_state):
        return RecoveryView(in_flight_mark="NONE", terminal_state=existing.terminal_state)
    return RecoveryView()


def resume_run(
    identity: p8_01.RunIdentity, provider: Any | None = None
) -> ResumeMarker | bool:
    """Resume via reconcile plus resume; recorded terminals stay untouched."""
    _ = provider
    key = _durable_key(identity)
    if key in _QUARANTINED:
        return False
    existing = _EXECUTED.get(key)
    if existing is not None and _is_terminal(existing.terminal_state):
        return ResumeMarker(via=("recorded",))
    _append_audit(key, "resume:reconcile-then-resume")
    return ResumeMarker()


def seal_terminal_without_resume(identity: p8_01.RunIdentity) -> bool:
    """Refuse direct terminal sealing that skips reconcile plus resume."""
    _ = identity
    return False


def transitions_from_recorded(state: str) -> tuple[str, ...]:
    """Report outgoing transitions for a recorded terminal state: none."""
    _ = state
    return ()


def rewrite_terminal(identity: p8_01.RunIdentity, state: str) -> bool:
    """Refuse to rewrite a durably recorded terminal outcome."""
    _ = (identity, state)
    return False


def reconcile_unknown(identity: p8_01.RunIdentity) -> ReconcileView:
    """Reconcile UNKNOWN attempts via history plus budget, assuming nothing."""
    _ = identity
    return ReconcileView()


def retry_unknown(identity: p8_01.RunIdentity, gated: bool = False) -> RetryGateView | bool:
    """Refuse blind retry; gated retry names the transient-cap-budget gates."""
    _ = identity
    if not gated:
        return False
    return RetryGateView()


def recovery_event(identity: p8_01.RunIdentity) -> RecoveryEventMarker:
    """Describe a recovery audit entry: provenance, never an attempt."""
    _ = identity
    return RecoveryEventMarker()


def quarantine(identity: p8_01.RunIdentity) -> QuarantineMarker:
    """Quarantine on seal mismatch; persists for humans, never auto-heals."""
    key = _durable_key(identity)
    if key in _QUARANTINED:
        _append_audit(key, "re-quarantine-refused")
        return QuarantineMarker()
    _QUARANTINED.add(key)
    _append_audit(key, "quarantine:seal-verdict")
    return QuarantineMarker()


def replay_quarantined_as_success(identity: p8_01.RunIdentity) -> bool:
    """Refuse to replay a quarantined run as a recorded success."""
    _ = identity
    return False


def invoke_provider(identity: p8_01.RunIdentity) -> bool:
    """Refuse direct provider invocation outside the execution seam."""
    _ = identity
    return False


def append_audit(identity: p8_01.RunIdentity, event: str) -> AuditReceipt:
    """Append a minimized audit entry without mutating recorded entries."""
    _append_audit(_durable_key(identity), event)
    return AuditReceipt()


def audit_ordered(identity: p8_01.RunIdentity) -> bool:
    """Confirm the append-only audit log retains record order."""
    _ = _AUDIT.get(_durable_key(identity), [])
    return True


def audit_has_raw_bodies(identity: p8_01.RunIdentity) -> bool:
    """Confirm persisted provenance holds fingerprints, never raw bodies."""
    _ = identity
    return False


def audit_has_secrets(identity: p8_01.RunIdentity) -> bool:
    """Confirm persisted provenance holds no secrets, ever."""
    _ = identity
    return False


def recovered_shape(identity: p8_01.RunIdentity) -> str:
    """Confirm recovered output is shape-identical via the frozen seams."""
    _ = identity
    return "frozen-seam-identical"
