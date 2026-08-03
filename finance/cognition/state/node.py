"""Node protocol and result type for the cognitive pipeline.

Defines the contract every cognitive node must satisfy: a ``CognitiveNode``
protocol whose ``execute`` method accepts a ``ReasoningState`` and returns a
``NodeResult``.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel

from finance.cognition.state.models import ReasoningState
from shared.models.assertions import Assertion


class NodeResult(BaseModel):
    """Structured result produced by a single cognitive node execution."""

    node_name: str
    success: bool = True
    state_updates: dict[str, Any] = {}
    new_assertions: list[Assertion] = []
    confidence: float = 0.0
    message: str = ""
    metadata: dict[str, Any] = {}


class CognitiveNode(Protocol):
    """Protocol that every cognitive node in the pipeline must satisfy."""

    def execute(self, state: ReasoningState) -> NodeResult:
        """Execute the cognitive node and return a structured result."""
        ...
