"""Pydantic models for the cognitive reasoning state machine.

Defines ReasoningState as the central shared state object passed through
a LangGraph pipeline, and TraceEntry as an immutable audit record produced
by each node execution.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from shared.models.assertions import Assertion


class TraceEntry(BaseModel):
    """Immutable record of a single cognitive node execution."""

    node_name: str
    execution_order: int
    result: dict[str, Any] = {}
    confidence: float = 0.0
    message: str = ""


class ReasoningState(BaseModel):
    """Central shared state passed through a cognitive pipeline.

    Carries the original query, an ordered trace of node executions,
    aggregated assertions, and a monotonically incrementing step counter.
    """

    query: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    step: int = 0
    trace: list[TraceEntry] = []
    assertions: list[Assertion] = []
    context: dict[str, Any] = {}
    overall_confidence: float = 0.0
    iteration_count: int = 0
    max_iterations: int = 5
    loop_decision: str = "continue"
    summary: str = ""
    action_plan: Any = None
    plan_history: list[Any] = []

    def record_step(
        self,
        node_name: str,
        result: dict[str, Any],
        confidence: float = 0.0,
        message: str = "",
    ) -> None:
        """Append a new TraceEntry and increment the step counter."""
        self.step += 1
        entry = TraceEntry(
            node_name=node_name,
            execution_order=self.step,
            result=result,
            confidence=confidence,
            message=message,
        )
        self.trace.append(entry)

    def add_assertions(self, assertions: list[Assertion]) -> None:
        """Append one or more Assertion objects to the state."""
        self.assertions.extend(assertions)
