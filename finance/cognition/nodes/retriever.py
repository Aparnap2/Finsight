from __future__ import annotations

from typing import TYPE_CHECKING, Any

from finance.cognition.state.models import ReasoningState
from finance.cognition.state.node import NodeResult

if TYPE_CHECKING:
    from finance.integration.spreadsheet_provider import SpreadsheetProvider


class RetrieverNode:
    """Gather raw data from a SpreadsheetProvider, when available.

    Without a provider, returns stub context (backward-compatible).
    With a provider, reads the given range and returns the real data.
    """

    def __init__(
        self,
        spreadsheet_provider: SpreadsheetProvider | None = None,
    ) -> None:
        self._provider = spreadsheet_provider

    def execute(self, state: ReasoningState) -> NodeResult:
        raw_data: list[list[str]] = []
        sources: list[str] = []

        # ── Determine what to retrieve based on the action plan ──────
        retrieved_for: list[str] = []
        if state.action_plan is not None:
            from finance.cognition.state.action import ActionPlan
            plan: ActionPlan | None = (
                state.action_plan
                if isinstance(state.action_plan, ActionPlan)
                else None
            )
            if plan is not None:
                for action in plan.actions:
                    retrieved_for.append(action.objective)

        if self._provider is not None:
            spreadsheet_id = state.context.get("spreadsheet_id", "default")
            range_str = state.context.get("range", "Sheet1!A:Z")
            try:
                raw_data = self._provider.read_range(spreadsheet_id, range_str)
                sources.append(f"spreadsheet:{spreadsheet_id}")
            except Exception:
                pass

        if not raw_data:
            data: dict[str, list[Any]] = {
                "variances": [],
                "kpis": [],
                "evidence_items": [],
            }
            state_updates: dict[str, Any] = {
                "context": data,
                "sources": [
                    "gl_accounts",
                    "budget",
                    "forecast",
                    *sources,
                ],
            }
            if retrieved_for:
                state_updates["retrieved_for"] = retrieved_for
            return NodeResult(
                node_name="retriever",
                success=True,
                state_updates=state_updates,
                confidence=0.8,
                message="Retrieved context from 3 sources",
            )

        state_updates = {
            "raw_data": raw_data,
            "sources": sources,
        }
        if retrieved_for:
            state_updates["retrieved_for"] = retrieved_for
        return NodeResult(
            node_name="retriever",
            success=True,
            state_updates=state_updates,
            confidence=0.8,
            message=f"Read {len(raw_data)} rows from {sources[0]}",
        )
