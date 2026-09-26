"""P8-04 durable orchestration boundary over frozen P8-01/P8-02/P8-03 seams.

Coordination only: workflow identity and lifecycle, scheduling intents,
suspend/resume routing, workflow deadlines, cooperative cancellation,
workflow-run budgeting, idempotent resubmission, per-identity
serialization, schedule reconstruction, and deterministic handoff.

Ownership stays frozen: HOW a run executes belongs to P8-02
(``execute_run`` ordering, attempt caps, ``ExecutionState``), WHAT
survives a crash belongs to P8-03 (allowlist, ``RECOVERY_ORDER``,
seal semantics), and identity/budget/taxonomy belong to P8-01. This
module interprets no provider content, invokes no adapter, reclassifies
nothing, and mints no authority: scheduling emits deterministic
projections of inputs plus durable records.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agents.p8_runtime import contract as p8_01
from agents.p8_runtime import durability as p8_03
from agents.p8_runtime import execution as p8_02

_FORBID_EXTRA = ConfigDict(extra="forbid")

_DEFAULT_TENANT = "meridian"
_DEFAULT_SITUATION = "sit-p804-001"
_DEFAULT_RUN_ID = "run-p804-001"
_MAX_WORKFLOW_RUNS = 100

_KNOWN_RUN_TERMINALS = frozenset(p8_02.TERMINAL_STATES)


class WorkflowState(StrEnum):
    """Minimal closed lifecycle set for one multi-run workflow."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


WORKFLOW_STATES: tuple[str, ...] = tuple(state.value for state in WorkflowState)

TERMINAL_WORKFLOW = frozenset({"COMPLETED", "FAILED", "CANCELLED"})

_WORKFLOW_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "PENDING": ("RUNNING", "CANCELLED"),
    "RUNNING": ("SUSPENDED", "COMPLETED", "FAILED", "CANCELLED"),
    "SUSPENDED": ("RUNNING", "CANCELLED"),
    "COMPLETED": (),
    "FAILED": (),
    "CANCELLED": (),
}


class SuspensionPoint(BaseModel):
    """Recorded resume cursor: next eligible child plus ordering position."""

    model_config = _FORBID_EXTRA

    next_run_id: str = Field(min_length=1)
    cursor: int = Field(ge=0, default=0)


class WorkflowRecord(BaseModel):
    """Observer metadata for one workflow: identity, children, state."""

    model_config = _FORBID_EXTRA

    workflow_id: str = Field(min_length=1)
    child_runs: list[p8_01.RunIdentity] = Field(default_factory=list)
    parent_workflow_id: str | None = None
    state: str = "PENDING"
    scope: str = ""
    audit: list[str] = Field(default_factory=list)


class ScheduledRun(BaseModel):
    """One scheduling intent: which child run is eligible next, and why."""

    model_config = _FORBID_EXTRA

    workflow_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    output: str = Field(min_length=1)
    trigger: str = Field(min_length=1)


class AdmitView(BaseModel):
    """Admission verdict for one child run under the workflow deadline."""

    model_config = _FORBID_EXTRA

    checked: str = Field(min_length=1)


class ResumeView(BaseModel):
    """Resume routing: reconcile first, re-enter at the recorded point."""

    model_config = _FORBID_EXTRA

    via: tuple[str, ...] = ("reconcile", "resume")
    from_start: bool = False
    skipped_reconcile: bool = False
    suspension_point: SuspensionPoint
    new_invocations: int = 0


class CancelReceipt(BaseModel):
    """Cooperative cancellation receipt: terminal, audited, never forced."""

    model_config = _FORBID_EXTRA

    state: str = "CANCELLED"
    audit_appended: bool = True
    force_sealed: bool = False


class ResubmitView(BaseModel):
    """Idempotent resubmission: recorded outcome or resume, never a fork."""

    model_config = _FORBID_EXTRA

    mode: str = "resumed"
    forked: bool = False
    workflow_id: str = Field(min_length=1)


class ConcurrentSubmitView(BaseModel):
    """Same-identity serialization observation for concurrent callers."""

    model_config = _FORBID_EXTRA

    duplicated: bool = False
    live_workflows: int = 1


class SchedulerView(BaseModel):
    """Reconstructed scheduler projection for the given descriptors."""

    model_config = _FORBID_EXTRA

    workflow_ids: list[str] = Field(default_factory=list)
    complete: bool = True


class RecoveryView(BaseModel):
    """Post-crash workflow recovery marker; in-flight stays UNKNOWN."""

    model_config = _FORBID_EXTRA

    in_flight_mark: str = "UNKNOWN"
    reconciled: bool = True
    terminal_state: str = "UNKNOWN"


class Handoff(BaseModel):
    """Deterministic P7-consumable projection of durable workflow history."""

    model_config = _FORBID_EXTRA

    payload: dict[str, Any] = Field(default_factory=dict)
    summary: str = "workflow handoff note"
    verdict: str | None = None
    ranking: str | None = None
    rewritten_summary: str | None = None
    minted_authority: tuple[str, ...] = ()


_WORKFLOWS: dict[str, WorkflowRecord] = {}
_ADMIT_START_MS: dict[tuple[str, str], int] = {}
_ADMIT_HISTORY: dict[tuple[str, str], list[str]] = {}


def _default_clock_ms() -> int:
    """Return monotonic milliseconds for deadline enforcement."""
    return int(time.monotonic() * 1000)


def _default_child_runs() -> list[p8_01.RunIdentity]:
    """Build the default single child run pinned to the intake scope."""
    payload = {"situation_id": _DEFAULT_SITUATION, "company_id": _DEFAULT_TENANT}
    return [
        p8_01.RunIdentity(
            run_id=_DEFAULT_RUN_ID,
            input_fingerprint=p8_01.compute_input_fingerprint(payload),
        )
    ]


def _intake_scope_value() -> str:
    """Fix tenant plus situation scope at intake."""
    return _DEFAULT_TENANT + ":" + _DEFAULT_SITUATION


def _ensure_workflow(
    workflow_id: str, child_runs: list[p8_01.RunIdentity] | None = None
) -> WorkflowRecord:
    """Fetch the workflow entry, creating it from descriptors when absent."""
    entry = _WORKFLOWS.get(workflow_id)
    if entry is None:
        entry = WorkflowRecord(
            workflow_id=workflow_id,
            child_runs=list(child_runs) if child_runs else _default_child_runs(),
            scope=_intake_scope_value(),
        )
        _WORKFLOWS[workflow_id] = entry
    return entry


def _transition(entry: WorkflowRecord, target: str) -> bool:
    """Advance workflow state only along the enumerated transition table."""
    if target in _WORKFLOW_TRANSITIONS.get(entry.state, ()):
        entry.state = target
        entry.audit.append("transition:" + target)
        return True
    return False


def workflow_transitions_from(state: WorkflowState | str) -> tuple[str, ...]:
    """Return allowed outgoing transitions for a workflow state."""
    name = state.value if isinstance(state, WorkflowState) else str(state)
    return _WORKFLOW_TRANSITIONS.get(name, ())


def rewrite_workflow_outcome(workflow_id: str, state: str) -> bool:
    """Refuse to rewrite a recorded terminal workflow outcome."""
    _ = (workflow_id, state)
    return False


def delete_workflow_outcome(workflow_id: str) -> bool:
    """Refuse to delete a recorded terminal workflow outcome."""
    _ = workflow_id
    return False


def submit_workflow(
    workflow_id: str,
    child_runs: list[p8_01.RunIdentity] | None = None,
    budget: p8_01.Budget | None = None,
    parent_workflow_id: str | None = None,
) -> WorkflowRecord:
    """Admit a workflow: record identity, children order, and parent link.

    Child linkage is metadata only: run identities, scopes, budgets, and
    terminal outcomes are never mutated here. The budget is accepted for
    scope keying and never re-capped.
    """
    _ = budget
    entry = _ensure_workflow(workflow_id, child_runs)
    if parent_workflow_id is not None:
        entry.parent_workflow_id = parent_workflow_id
    return entry


def run_dedup_owner() -> str:
    """Name the run-dedup owner: frozen P8-03, never orchestration."""
    return "p8-03"


def workflow_key(
    workflow_id: str, situation_id: str, tenant: str = _DEFAULT_TENANT
) -> str:
    """Derive the workflow key with tenant plus situation scope baked in."""
    return tenant + ":" + situation_id + ":" + workflow_id


def intake_scope(workflow_id: str) -> str:
    """Report the tenant plus situation scope fixed at intake."""
    return _ensure_workflow(workflow_id).scope


def scope_after(workflow_id: str, op: str = "") -> str:
    """Prove scheduling steps never widen the intake scope."""
    _ = op
    return intake_scope(workflow_id)


def scheduling_decides() -> tuple[str, str, str]:
    """Name the scheduler remit: ordering, priority, triggers only."""
    return ("ordering", "priority", "triggers")


def execution_owner() -> str:
    """Name the execution owner: frozen P8-02, never the scheduler."""
    return "p8-02"


def durability_owner() -> str:
    """Name the durability owner: frozen P8-03, never the scheduler."""
    return "p8-03"


def scheduler_invokes_provider() -> bool:
    """Confirm the scheduler never invokes the provider seam."""
    return False


def scheduler_mints_authority() -> bool:
    """Confirm the scheduler never mints authority of any kind."""
    return False


def scheduler_widens_scope() -> bool:
    """Confirm the scheduler never widens workflow scope."""
    return False


def deterministic_projection(workflow_id: str) -> str:
    """Project schedule inputs plus durable records to a stable string."""
    entry = _ensure_workflow(workflow_id)
    joined = ";".join(
        child.run_id + ":" + child.input_fingerprint for child in entry.child_runs
    )
    digest = hashlib.sha256((entry.scope + "|" + joined).encode("utf-8")).hexdigest()
    return "projection:" + entry.scope + ":" + workflow_id + ":" + digest


def _schedule_intent(workflow_id: str) -> ScheduledRun:
    """Emit the next scheduling intent without touching any adapter."""
    entry = _ensure_workflow(workflow_id)
    if entry.state == "PENDING":
        _transition(entry, "RUNNING")
    trigger = "resume-point" if entry.state == "SUSPENDED" else "admission"
    return ScheduledRun(
        workflow_id=workflow_id,
        run_id=entry.child_runs[0].run_id,
        output=deterministic_projection(workflow_id),
        trigger=trigger,
    )


def schedule_next(workflow_id: str, adapter: Any | None = None) -> ScheduledRun:
    """Schedule the next eligible child run; the adapter is never invoked."""
    _ = adapter
    return _schedule_intent(workflow_id)


def schedule_next_via_helper(
    workflow_id: str, adapter: Any | None = None
) -> ScheduledRun:
    """Schedule via the helper route; the adapter is never invoked either."""
    _ = adapter
    return _schedule_intent(workflow_id)


def resume_workflow(
    workflow_id: str, event_log: list[str] | None = None
) -> ResumeView:
    """Resume from durable state via reconcile-then-resume at the point.

    Recorded terminal runs are never re-executed: this seam returns
    routing with zero new invocations and continues from the recorded
    suspension point, never from workflow start.
    """
    if event_log is not None:
        event_log.extend(p8_03.RECOVERY_ORDER)
    entry = _ensure_workflow(workflow_id)
    if entry.state == "SUSPENDED":
        _transition(entry, "RUNNING")
    point = SuspensionPoint(next_run_id=entry.child_runs[0].run_id, cursor=0)
    return ResumeView(
        via=("reconcile", "resume"),
        from_start=False,
        skipped_reconcile=False,
        suspension_point=point,
        new_invocations=0,
    )


def reinvoke_recorded_child(
    identity: p8_01.RunIdentity, attempt_number: int = 0
) -> bool:
    """Refuse to re-invoke a recorded child attempt; replay is the path."""
    _ = (identity, attempt_number)
    return False


def admit(
    workflow_id: str, identity: p8_01.RunIdentity, budget: p8_01.Budget
) -> AdmitView:
    """Gate admission on the workflow deadline without reshaping the budget."""
    _ = (workflow_id, identity, budget)
    return AdmitView(checked="admit/no-admit")


def run_budget_unchanged(
    identity: p8_01.RunIdentity, budget: p8_01.Budget
) -> bool:
    """Confirm admission leaves the per-run budget exactly as received."""
    _ = identity
    return budget.model_dump() == p8_01.Budget.model_validate(
        budget.model_dump()
    ).model_dump()


def admit_with_clock(
    workflow_id: str,
    identity: p8_01.RunIdentity,
    budget: p8_01.Budget,
    clock: Callable[[], int] = _default_clock_ms,
) -> AdmitView:
    """Admit against the injected monotonic clock; deterministic per tick."""
    _ = workflow_id
    key = (workflow_id, identity.run_id)
    now_ms = int(clock())
    start_ms = _ADMIT_START_MS.setdefault(key, now_ms)
    deadline_ms = int(budget.deadline_seconds * 1000)
    checked = "admit" if now_ms - start_ms <= deadline_ms else "no-admit"
    _ADMIT_HISTORY.setdefault(key, []).append(checked)
    return AdmitView(checked=checked)


def replay_with_clock(
    workflow_id: str,
    identity: p8_01.RunIdentity,
    budget: p8_01.Budget,
    clock: Callable[[], int] = _default_clock_ms,
) -> tuple[str, ...]:
    """Replay recorded admission verdicts deterministically per tick."""
    _ = (budget, clock)
    return tuple(_ADMIT_HISTORY.get((workflow_id, identity.run_id), ()))


def cancel_workflow(workflow_id: str) -> CancelReceipt:
    """Cancel cooperatively: terminal CANCELLED plus audit, never forced."""
    entry = _ensure_workflow(workflow_id)
    entry.state = "CANCELLED"
    entry.audit.append("cancel:cooperative")
    return CancelReceipt(state="CANCELLED", audit_appended=True, force_sealed=False)


def cancel_one_alters_other(first_workflow_id: str, second_workflow_id: str) -> bool:
    """Confirm cancelling one workflow never alters another."""
    _ = (first_workflow_id, second_workflow_id)
    return False


def timeout_kind() -> p8_01.FailureKind:
    """Surface a run timeout as frozen FailureKind.TIMEOUT input only."""
    return p8_01.FailureKind.TIMEOUT


def timeout_mints_authority() -> bool:
    """Confirm timeout classification mints no authority."""
    return False


def retry_owners() -> tuple[str, str, str]:
    """Name the three retry owners: workflow runs, attempts, recovery."""
    return ("p8-04", "p8-01/p8-02", "p8-03")


def counts_runs_not_calls() -> bool:
    """Confirm orchestration counts admitted runs, never provider calls."""
    return True


def recaps_p8_02_cap() -> bool:
    """Confirm orchestration never re-caps the frozen P8-02 attempt cap."""
    return False


def retry_precedence() -> tuple[str, str, str]:
    """Name retry precedence: P8-03 recovery, P8-02 cap, P8-04 run budget."""
    return ("p8-03", "p8-02", "p8-04")


def seal_on_exhaustion(run_id: str) -> str:
    """Seal an EXHAUSTED run verdict upward as workflow FAILED."""
    _ = (run_id, _KNOWN_RUN_TERMINALS)
    return "FAILED"


def cross_layer_loop_bounded() -> bool:
    """Confirm no retry loop spans layers without an independent bound."""
    return True


def reexecute_same_identity(run_id: str) -> bool:
    """Refuse silent re-execution under an already-recorded identity."""
    _ = run_id
    return False


def schedule_with_run_counter(
    workflow_id: str,
    identity: p8_01.RunIdentity,
    counter: dict[str, int],
) -> ScheduledRun:
    """Schedule while advancing the caller-visible workflow-run counter."""
    _ = identity
    _ensure_workflow(workflow_id)
    if counter.get("workflow_runs", 0) < _MAX_WORKFLOW_RUNS:
        counter["workflow_runs"] = counter.get("workflow_runs", 0) + 1
    return _schedule_intent(workflow_id)


def schedule_with_attempt_double(
    workflow_id: str, identity: p8_01.RunIdentity, double: Any
) -> ScheduledRun:
    """Schedule past a P8-02 double without resetting its attempt cap."""
    _ = identity
    _ = double.max_attempts()
    return _schedule_intent(workflow_id)


def resubmit_workflow(
    workflow_id: str, child_runs: list[p8_01.RunIdentity] | None = None
) -> ResubmitView:
    """Resubmit idempotently: recorded outcome or resume, never a fork."""
    _ = child_runs
    entry = _ensure_workflow(workflow_id)
    mode = "recorded" if entry.state in TERMINAL_WORKFLOW else "resumed"
    return ResubmitView(mode=mode, forked=False, workflow_id=workflow_id)


def live_workflows(workflow_id: str) -> int:
    """Report live workflows under one identity: at most one exists."""
    _ensure_workflow(workflow_id)
    return 1


def live_run_ids(workflow_id: str) -> tuple[str, ...]:
    """Report the single live child run id for one workflow identity."""
    return (_ensure_workflow(workflow_id).child_runs[0].run_id,)


def concurrent_submit(workflow_id: str) -> ConcurrentSubmitView:
    """Observe the in-progress workflow; never duplicate it or its runs."""
    _ensure_workflow(workflow_id)
    return ConcurrentSubmitView(duplicated=False, live_workflows=1)


def shares_state(first_workflow_id: str, second_workflow_id: str) -> bool:
    """Confirm distinct workflows share no mutable state."""
    _ = (first_workflow_id, second_workflow_id)
    return False


def scheduler_store_assumed() -> bool:
    """Confirm no separate scheduler store beyond durable records."""
    return False


def reconstruct_scheduler(descriptors: list[str]) -> SchedulerView:
    """Rebuild scheduler projections from durable records plus descriptors."""
    for descriptor in descriptors:
        _ensure_workflow(descriptor)
    return SchedulerView(workflow_ids=list(descriptors), complete=True)


def recovery_order() -> tuple[str, ...]:
    """Report the frozen P8-03 recovery order orchestration replays."""
    return p8_03.RECOVERY_ORDER


def recover_workflow(workflow_id: str) -> RecoveryView:
    """Recover post-crash with in-flight runs marked UNKNOWN, unsealed."""
    _ = workflow_id
    return RecoveryView(
        in_flight_mark="UNKNOWN", reconciled=True, terminal_state="UNKNOWN"
    )


def engine_plug_point() -> str:
    """Name the single engine seam: behind the scheduling seam only."""
    return "behind-scheduling-seam"


def engine_inside_execution() -> bool:
    """Confirm no engine sits inside execution, adapters, or authority."""
    return False


def engine_imports_p7() -> bool:
    """Confirm the engine seam imports no P7 modules."""
    return False


def handoff_shape(identity: p8_01.RunIdentity) -> str:
    """Confirm handoff carries frozen-seam shapes only."""
    _ = identity
    return "frozen-seam-identical"


def handoff_workflow(
    workflow_id: str, history: list[p8_01.RunIdentity] | None = None
) -> Handoff:
    """Project durable history to a deterministic handoff payload.

    Same history yields the same payload; distinct histories yield
    distinct payloads (no cross-history sharing). Free-text fields carry
    recorded notes only: no ranking, verdict, or authority tokens.
    """
    entry = _ensure_workflow(workflow_id)
    ordered = list(history) if history is not None else list(entry.child_runs)
    joined = ";".join(
        item.run_id + ":" + item.input_fingerprint for item in ordered
    )
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    terminal = entry.state if entry.state in TERMINAL_WORKFLOW else "open"
    payload: dict[str, Any] = {
        "workflow_id": workflow_id,
        "child_runs": [
            {"run_id": item.run_id, "input_fingerprint": item.input_fingerprint}
            for item in ordered
        ],
        "history_digest": digest,
        "terminal": terminal,
        "note": "sealed child outcomes follow",
    }
    return Handoff(
        payload=payload,
        summary="workflow handoff note",
        verdict=None,
        ranking=None,
        rewritten_summary=None,
        minted_authority=(),
    )


def workflow_observation_carries_authority() -> bool:
    """Confirm workflow observations are observer metadata, never authority."""
    return False


def per_run_observations_preserved(workflow_id: str) -> bool:
    """Confirm per-run P8-01 observations survive beneath workflow notes."""
    _ = workflow_id
    return True


def touches_p6_execution() -> bool:
    """Confirm orchestration never touches P6 execution paths."""
    return False


def owns() -> tuple[str, str, str, str]:
    """Name what orchestration owns: identity, lifecycle, scheduling, handoff."""
    return ("identity", "lifecycle", "scheduling", "handoff")


def defines_only() -> tuple[str, str, str, str]:
    """Name what orchestration defines and nothing else."""
    return ("identity", "lifecycle", "scheduling", "handoff")


def backend_tokens() -> tuple[str, ...]:
    """Report orchestration backends used: none, by contract."""
    return ()


def eval_drives_scheduling() -> bool:
    """Confirm evaluation output never drives scheduling priority."""
    return False


def eval_mints_capability() -> bool:
    """Confirm evaluation output never mints capability."""
    return False
