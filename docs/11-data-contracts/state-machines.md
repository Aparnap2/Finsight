# State Machine Definitions for Workflow Entities

> **Layer:** Governance — enforces legal state transitions across all workflow entities
> **Audience:** Backend developers, agent pipeline engineers, reviewers
> **Status:** Design proposal for Phase 2

## 1. Design Principles

1. **Explicit states** — Every entity has a `status: SomeEnum` field. No stringly-typed status fields.
2. **Legal transitions only** — The state machine class defines `allowed_transitions`. A direct `model.status = "x"` is a bug. Use `model.transition_to(new_status)` instead.
3. **Transitions can have guard conditions** — `transition_to()` accepts optional context for conditional transitions.
4. **Every transition is auditable** — `transition_to()` returns an `AuditEvent` that must be persisted.
5. **PostgreSQL CHECK constraints mirror the state machine** — Declarative CHECK constraints enforce the same transitions at the database level.
6. **Integration with Dispatcher's job state machine** — The `JobStatus` state machine drives compute job lifecycle. Workflow states (pipeline, agent, action) nest within it.

---

## 2. State Machine Registry

```python
# finance/state_machines/registry.py (proposed)

from __future__ import annotations

from enum import Enum
from typing import Any


class TransitionError(Exception):
    """Raised when an illegal state transition is attempted."""

    def __init__(self, entity: str, from_status: str, to_status: str, reason: str = ""):
        self.entity = entity
        self.from_status = from_status
        self.to_status = to_status
        self.reason = reason
        super().__init__(
            f"Illegal transition: {entity} from {from_status} → {to_status}"
            + (f": {reason}" if reason else "")
        )


class StateMachine:
    """Base class for all state machines.
    
    Usage:
        class PipelineRunSM(StateMachine):
            STATES = ["pending", "running", "success", "failed"]
            TRANSITIONS = {
                "pending": ["running"],
                "running": ["success", "failed"],
            }
    """

    STATES: set[str] = set()
    TRANSITIONS: dict[str, list[str]] = {}

    @classmethod
    def is_legal(cls, from_status: str, to_status: str) -> bool:
        if from_status not in cls.TRANSITIONS:
            return False
        return to_status in cls.TRANSITIONS[from_status]

    @classmethod
    def assert_legal(cls, from_status: str, to_status: str, entity: str = "entity") -> None:
        if not cls.is_legal(from_status, to_status):
            raise TransitionError(entity, from_status, to_status)

    @classmethod
    def terminal_states(cls) -> set[str]:
        return {s for s in cls.STATES if s not in cls.TRANSITIONS.get(s, []) 
                and all(to not in cls.TRANSITIONS.get(s, []) for to in cls.STATES)}

    @classmethod
    def initial_states(cls) -> set[str]:
        all_targets = set()
        for targets in cls.TRANSITIONS.values():
            all_targets.update(targets)
        not_a_target = cls.STATES - all_targets
        return not_a_target - cls.terminal_states()
```

---

## 3. Entity State Machines

### 3.1 PipelineRun State Machine

Controls the end-to-end analysis pipeline lifecycle.

```
        ┌──────────┐
        │ PENDING  │
        └────┬─────┘
             │
        ┌────▼──────┐
        │ RUNNING   │
        └────┬──────┘
             │
     ┌───────┼───────────┐
     │       │           │
┌────▼───┐ ┌─▼─────┐ ┌──▼──────┐
│SUCCESS │ │FAILED │ │CANCELLED│
└────────┘ └───┬───┘ └─────────┘
               │
          ┌────▼─────┐
          │ RETRYING │────────► RUNNING
          └──────────┘
```

```python
class PipelineRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"

class PipelineRunSM(StateMachine):
    STATES = {"pending", "running", "success", "failed", "retrying", "cancelled"}
    TRANSITIONS = {
        "pending": ["running", "cancelled"],
        "running": ["success", "failed"],
        "failed": ["retrying"],        # Only if retryable
        "retrying": ["running", "failed"],  # failed = exhausted
    }
```

**Guard conditions:**
- `running → failed`: Always legal. Must carry a `RuntimeErrorInfo`.
- `failed → retrying`: Only legal if `error.retryable == True` AND `retry_count < max_retries`.
- `retrying → running`: Transition happens automatically after backoff delay.
- `retrying → failed`: Terminal — retries exhausted.

**Database CHECK constraint:**
```sql
ALTER TABLE pipeline_runs ADD CONSTRAINT chk_pipeline_run_status
CHECK (
    CASE
        WHEN status = 'pending'  THEN TRUE
        WHEN status = 'running'  THEN TRUE
        WHEN status = 'success'  THEN TRUE
        WHEN status = 'failed'   THEN TRUE
        WHEN status = 'retrying' THEN TRUE
        WHEN status = 'cancelled' THEN TRUE
        ELSE FALSE
    END
);
```

### 3.2 AgentRun State Machine

Controls individual agent node execution within a pipeline.

```
       ┌──────────┐
       │ PENDING  │
       └────┬─────┘
            │
       ┌────▼──────┐
       │ RUNNING   │
       └────┬──────┘
            │
     ┌──────┼──────────┐
     │      │          │
┌────▼───┐ ┌▼────┐  ┌──▼──────┐
│SUCCESS │ │FAILED│  │CANCELLED│
└────────┘ └──┬───┘  └─────────┘
              │
         ┌────▼─────┐
         │ RETRYING │──► RUNNING
         └──────────┘
```

```python
class AgentRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"

class AgentRunSM(StateMachine):
    STATES = {"pending", "running", "success", "failed", "retrying", "cancelled"}
    TRANSITIONS = {
        "pending": ["running", "cancelled"],
        "running": ["success", "failed"],
        "failed": ["retrying"],
        "retrying": ["running", "failed"],
    }
```

### 3.3 Job Status State Machine (Compute Runtime)

Controls compute job lifecycle (mirrors `python_runtime/models.py:JobStatus` with extended states from `compute-runtime.md`).

```
       ┌──────────┐
       │  QUEUED  │
       └────┬─────┘
            │
       ┌────▼──────┐
       │  RUNNING  │
       └────┬──────┘
            │
       ┌────▼─────────┐
       │  VALIDATING  │
       └────┬─────────┘
            │
       ┌────▼─────────┐
       │  EXECUTING   │
       └────┬─────────┘
            │
       ┌────▼─────────┐
       │  EXPORTING   │
       └────┬─────────┘
            │
       ┌────▼──────┐     ┌──────────┐     ┌──────────┐
       │  SUCCESS  │     │  FAILED  │────▶│ RETRYING │
       └───────────┘     └────┬─────┘     └────┬─────┘
                             │                 │
                             │           ┌─────▼──────┐
                             └──────────▶│   FAILED   │
                                         │ (exhausted)│
                                         └────────────┘
```

```python
class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    VALIDATING = "validating"
    EXECUTING = "executing"
    EXPORTING = "exporting"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"

class JobSM(StateMachine):
    STATES = {
        "queued", "running", "validating", "executing", "exporting",
        "success", "failed", "retrying", "cancelled",
    }
    TRANSITIONS = {
        "queued": ["running", "cancelled"],
        "running": ["validating", "failed"],
        "validating": ["executing", "failed"],
        "executing": ["exporting", "failed"],
        "exporting": ["success", "failed"],
        "failed": ["retrying"],
        "retrying": ["running", "failed"],
    }
```

**Integration with Dispatcher:** The `Dispatcher` in `python_runtime/dispatcher/router.py` uses `JobSM` to enforce transitions. Every `dispatch()` call checks `JobSM.assert_legal(current, next)` before transitioning.

### 3.4 ActionItem Status State Machine

Controls action item lifecycle (extends `shared/models/action.py:ActionStatus`).

```
       ┌───────────┐
       │ PROPOSED  │
       └─────┬─────┘
             │
       ┌─────▼───────┐
       │  APPROVED   │
       └─────┬───────┘
             │
       ┌─────▼──────────┐
       │  IN_PROGRESS   │
       └─────┬──────────┘
             │
       ┌─────▼────────┐
       │  COMPLETED   │
       └──────────────┘

       ┌───────────┐
       │  BLOCKED  │──► PROPOSED (unblock)
       └─────┬─────┘
             │
       ┌─────▼───────┐
       │  REJECTED   │
       └─────────────┘
```

```python
class ActionStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    REJECTED = "rejected"

class ActionItemSM(StateMachine):
    STATES = {"proposed", "approved", "in_progress", "completed", "blocked", "rejected"}
    TRANSITIONS = {
        "proposed": ["approved", "blocked", "rejected"],
        "approved": ["in_progress", "blocked", "rejected"],
        "in_progress": ["completed", "blocked"],
        "blocked": ["proposed", "rejected"],  # Unblocked or abandoned
    }
```

**Guard conditions:**
- `proposed → blocked`: Must carry `blocked_reason`.
- `blocked → proposed`: The `blocked_reason` must have been resolved. New `ActionItem` produced with updated `cited_assertion_ids` and `policy_permitted`.
- `proposed → approved`: Requires `policy_permitted == True` and `owner_identified == True`.

### 3.5 Recommendation Status State Machine

Controls recommendation lifecycle (extends `finance/domain/recommendation.py:RecommendationStatus`).

```
       ┌───────────┐
       │ PROPOSED  │
       └─────┬─────┘
             │
       ┌─────▼───────┐
       │  REVIEWED   │
       └─────┬───────┘
             │
       ┌─────▼────────┐     ┌──────────┐
       │  APPROVED    │     │ REJECTED │
       └─────┬────────┘     └──────────┘
             │
       ┌─────▼────────────┐
       │  IMPLEMENTED     │
       └──────────────────┘
```

```python
class RecommendationStatus(str, Enum):
    PROPOSED = "proposed"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    IMPLEMENTED = "implemented"
    REJECTED = "rejected"

class RecommendationSM(StateMachine):
    STATES = {"proposed", "reviewed", "approved", "implemented", "rejected"}
    TRANSITIONS = {
        "proposed": ["reviewed", "rejected"],
        "reviewed": ["approved", "rejected"],
        "approved": ["implemented", "rejected"],
    }
```

### 3.6 Commentary Version State Machine

Controls commentary draft version lifecycle.

```
       ┌───────────┐
       │   DRAFT   │
       └─────┬─────┘
             │
       ┌─────▼───────┐
       │  REVIEWING  │
       └─────┬───────┘
             │
       ┌─────▼───────┐     ┌──────────┐
       │  APPROVED   │     │ REJECTED │
       └─────┬───────┘     └──────────┘
             │
       ┌─────▼────────┐
       │  PUBLISHED   │
       └──────────────┘

       DRAFT ──► DRAFT (new version, version += 1)
```

```python
class CommentaryStatus(str, Enum):
    DRAFT = "draft"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"

class CommentarySM(StateMachine):
    STATES = {"draft", "reviewing", "approved", "rejected", "published"}
    TRANSITIONS = {
        "draft": ["draft", "reviewing"],      # draft → draft = new iteration
        "reviewing": ["approved", "rejected"],
        "approved": ["published", "draft"],    # approved → draft = revision requested
    }
```

### 3.7 Fiscal Period State Machine

Controls period lifecycle in the fiscal calendar.

```
       ┌────────────┐
       │  OPEN      │
       └─────┬──────┘
             │
       ┌─────▼────────┐
       │  CLOSING     │  (running closing checks)
       └─────┬────────┘
             │
       ┌─────▼────────┐     ┌───────────┐
       │  CLOSED      │     │ REOPENED  │──► OPEN
       └─────┬────────┘     └───────────┘
             │
       ┌─────▼────────┐
       │  ARCHIVED    │
       └──────────────┘
```

```python
class PeriodStatus(str, Enum):
    OPEN = "open"
    CLOSING = "closing"    # Transitional — closing checks in progress
    CLOSED = "closed"      # No new postings allowed
    REOPENED = "reopened"  # Exceptionally reopened for adjustments
    ARCHIVED = "archived"  # Read-only, never reopened

class FiscalPeriodSM(StateMachine):
    STATES = {"open", "closing", "closed", "reopened", "archived"}
    TRANSITIONS = {
        "open": ["closing"],
        "closing": ["closed"],
        "closed": ["reopened", "archived"],
        "reopened": ["open", "archived"],  # reopen → must go back to open
    }
```

**Guard conditions:**
- `closed → reopened`: Requires CFO approval (audit trail entry).
- `reopened → open`: Auto-transition when adjustment posting is complete.
- Any → `archived`: Only after all downstream processes are confirmed complete.

### 3.8 Assertion Support Level (not a state machine, but a constrained lattice)

The `SupportLevel` enum in `shared/models/assertions.py` represents a confidence lattice, not a state machine. Downgrades are one-directional:

```
                 VERIFIED
                    │
              ┌─────┴─────┐
              │           │
          PROBABLE     (cannot upgrade)
              │
              │
            WEAK
              │
              │
        INSUFFICIENT
```

This is enforced by `assertion_validator.py` — an assertion can only move DOWN the lattice, never UP (without re-running the full validation pipeline).

---

## 4. PostgreSQL CHECK Constraint Equivalents

Every state machine has a corresponding CHECK constraint at the database layer. This provides defence-in-depth — the application enforces transitions, but the database prevents corruption even if application logic has a bug.

```sql
-- State machine CHECK constraints (proposed migrations)

-- Action Items
ALTER TABLE action_items ADD CONSTRAINT chk_action_status
CHECK (status IN ('proposed', 'approved', 'in_progress', 'completed', 'blocked', 'rejected'));

-- Agent Runs
ALTER TABLE agent_runs ADD CONSTRAINT chk_agent_run_status
CHECK (status IN ('pending', 'running', 'success', 'failed', 'retrying', 'cancelled'));

-- Commentary Versions
ALTER TABLE commentary_versions ADD CONSTRAINT chk_commentary_status
CHECK (status IN ('draft', 'reviewing', 'approved', 'rejected', 'published'));

-- Pipeline Runs
ALTER TABLE pipeline_runs ADD CONSTRAINT chk_pipeline_status
CHECK (status IN ('pending', 'running', 'success', 'failed', 'retrying', 'cancelled'));

-- Review Decisions
ALTER TABLE review_decisions ADD CONSTRAINT chk_review_decision
CHECK (decision IN ('approved', 'rejected', 'escalated'));

-- Fiscal Periods (if stored in DB)
ALTER TABLE fiscal_periods ADD CONSTRAINT chk_period_status
CHECK (status IN ('open', 'closing', 'closed', 'reopened', 'archived'));
```

---

## 5. Integration with the Dispatcher's Job State Machine

The Compute Runtime's `JobStatus` state machine (`python_runtime/models.py`) is the outermost state machine. Workflow entities that run WITHIN a job nest their state machines underneath:

```
Job (JobStatus: QUEUED → RUNNING → VALIDATING → EXECUTING → EXPORTING → SUCCESS)
 │
 ├── PipelineRun (PipelineRunStatus: PENDING → RUNNING → SUCCESS/FAILED)
 │    │
 │    ├── AgentRun 1 (AgentRunStatus: PENDING → RUNNING → SUCCESS)
 │    ├── AgentRun 2 (AgentRunStatus: PENDING → RUNNING → FAILED → RETRYING → RUNNING → SUCCESS)
 │    │    │
 │    │    ├── ActionItem PROPOSED → APPROVED → IN_PROGRESS → COMPLETED
 │    │    └── Commentary DRAFT → REVIEWING → APPROVED → PUBLISHED
 │    │
 │    └── AgentRun N (AgentRunStatus: PENDING → RUNNING → SUCCESS)
 │
 └── JobStatus: EXPORTING → SUCCESS
```

**Rules for nesting:**
1. A parent machine cannot transition to a terminal state while a child machine is still in a non-terminal state.
2. If a child machine enters `FAILED`, the parent may choose to retry (transition child to `RETRYING`) or propagate failure upward.
3. If a parent enters `CANCELLED`, all children MUST transition to `CANCELLED` (graceful shutdown).

---

## 6. Transition Audit Events

Every state transition produces an audit event:

```python
class StateTransitionEvent(BaseModel):
    """Recorded for every state machine transition."""
    entity_type: str          # "pipeline_run", "agent_run", "action_item", ...
    entity_id: str
    from_status: str
    to_status: str
    triggered_by: str         # "system", "user:<user_id>", "agent:<agent_name>"
    reason: str = ""          # Optional human-readable reason
    metadata: dict[str, Any] = {}
    timestamp: datetime
```

These events are persisted to the `audit_logs` table with `event_type = "state_transition"`.

---

## 7. Implementation Guide

### Adding a new state machine:
1. Define the `StrEnum` in the domain model file.
2. Define a `StateMachine` subclass with `STATES` and `TRANSITIONS`.
3. Add `transition_to()` method to the domain model.
4. Add CHECK constraint migration to the ORM model.
5. Add audit event emission in the transition method.
6. Write unit tests for ALL legal transitions and ALL illegal transitions.

### Testing state machines:

```python
# tests/unit/state_machines/test_action_item_sm.py

import pytest
from finance.state_machines.registry import TransitionError
from finance.state_machines.action import ActionItemSM, ActionStatus

class TestActionItemSM:
    def test_legal_transitions(self):
        """Every defined transition should be legal."""
        for from_status, to_list in ActionItemSM.TRANSITIONS.items():
            for to_status in to_list:
                # Should not raise
                ActionItemSM.assert_legal(from_status, to_status)

    def test_illegal_transitions_raise(self):
        """Every undefined transition should raise TransitionError."""
        illegal = [
            ("proposed", "completed"),    # must go through approved → in_progress
            ("completed", "approved"),    # terminal
            ("rejected", "approved"),     # terminal
        ]
        for from_status, to_status in illegal:
            with pytest.raises(TransitionError):
                ActionItemSM.assert_legal(from_status, to_status)

    def test_no_self_transition(self):
        """Entities should not transition to their current status."""
        for status in ActionItemSM.STATES:
            if status in ActionItemSM.TRANSITIONS.get(status, []):
                # Commentary is an exception (draft → draft = new version)
                continue
            with pytest.raises(TransitionError):
                ActionItemSM.assert_legal(status, status)
```

---

## 8. State Machine Summary

| Entity | States | Transitions | Current Implementation |
|--------|--------|-------------|-----------------------|
| PipelineRun | 6 | 8 | `database.py:PipelineRun` — string status, no enforcement |
| AgentRun | 6 | 8 | `database.py:AgentRun` — string status, no enforcement |
| Job (Runtime) | 9 | 12 | `python_runtime/models.py:JobStatus` — enum, no SM class |
| ActionItem | 6 | 9 | `action.py:ActionStatus` — enum, property guards, no SM class |
| Recommendation | 5 | 6 | `recommendation.py:RecommendationStatus` — enum, no SM |
| Commentary | 5 | 6 | `database.py:CommentaryVersion.status` — string, no SM |
| FiscalPeriod | 5 | 6 | `fiscal_calendar.py:FiscalPeriod.is_closed` — bool, no SM |
| SupportLevel | 4 | Lattice | `assertions.py:SupportLevel` — enum, one-directional downgrade |
