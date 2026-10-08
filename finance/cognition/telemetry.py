from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from finance.cognition.state.models import ReasoningState
from shared.safety.secrets import redact_mapping, scrub_text


def _scrub_trace(node: Any) -> Any:
    """Scrub secrets/PII from a trace structure, preserving shape and amounts.

    Secret-named keys collapse, secret-shaped and email values are masked
    inline, everything else (ids, amounts, states, counts) passes through
    so traces stay debuggable. Uses only the approved secrets primitives.
    """
    if isinstance(node, dict):
        return {key: _scrub_trace(value) for key, value in redact_mapping(node).items()}
    if isinstance(node, list):
        return [_scrub_trace(item) for item in node]
    if isinstance(node, str):
        return scrub_text(node)
    return node


class ReasoningTelemetry:
    """Captures structured per-run traces for debugging and evaluation."""

    def __init__(self, output_dir: str = ".reasoning_traces") -> None:
        self._dir = Path(output_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def capture(self, run_id: str, state: ReasoningState) -> Path:
        trace: dict[str, Any] = {
            "run_id": run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "query": state.query,
            "step_count": state.step,
            "iteration_count": state.iteration_count,
            "overall_confidence": state.overall_confidence,
            "loop_decision": state.loop_decision,
            "summary": state.summary,
            "trace": [
                {
                    "node_name": t.node_name,
                    "execution_order": t.execution_order,
                    "confidence": t.confidence,
                    "message": t.message,
                    "result": t.result,
                }
                for t in state.trace
            ],
            "assertions": [a.model_dump() for a in state.assertions],
            "context_keys": list(state.context.keys()),
            "action_traces": state.context.get("action_traces", []),
            "plan_history": (
                [p.model_dump() for p in state.plan_history] if state.plan_history else []
            ),
        }
        path = self._dir / f"{run_id}.json"
        path.write_text(json.dumps(_scrub_trace(trace), indent=2, default=str))
        return path
