"""Action and ActionPlan models for the cognitive runtime.

These models represent the decomposition of a reasoning goal into discrete
actions that can be routed to deterministic engines (variance, KPI, evidence,
validation) by the ExecutorNode.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ActionStatus(StrEnum):
    """Status of a single action within an ActionPlan."""

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class Action(BaseModel):
    """A single atomic action within a plan (e.g. compute a variance)."""

    objective: str
    status: ActionStatus = ActionStatus.PENDING
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    tool: str = ""
    latency_ms: float = 0.0
    retry_count: int = 0
    evidence_ids: list[str] = Field(default_factory=list)
    id: str = Field(default_factory=lambda: f"act_{uuid.uuid4().hex[:8]}")


class ActionPlan(BaseModel):
    """Ordered list of actions produced by the planner."""

    actions: list[Action] = Field(default_factory=list)
    iteration: int = 0

    def add(
        self,
        objective: str,
        inputs: dict[str, Any] | None = None,
    ) -> Action:
        """Create and append an Action, returning it for further mutation."""
        action = Action(objective=objective, inputs=inputs or {})
        self.actions.append(action)
        return action

    @property
    def completed(self) -> list[Action]:
        return [a for a in self.actions if a.status == ActionStatus.SUCCESS]

    @property
    def pending(self) -> list[Action]:
        return [a for a in self.actions if a.status == ActionStatus.PENDING]

    @property
    def failed(self) -> list[Action]:
        return [a for a in self.actions if a.status == ActionStatus.FAILED]
