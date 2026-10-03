from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from finance.cognition.registry import NodeRegistry
from finance.cognition.state.models import ReasoningState
from finance.cognition.telemetry import ReasoningTelemetry


class HarnessResult:
    """Result of a full reasoning harness run."""

    def __init__(
        self,
        state: ReasoningState,
        run_id: str,
        success: bool = True,
        stop_reason: str = "finalize",
        state_fingerprint: str = "",
    ) -> None:
        self.state = state
        self.run_id = run_id
        self.success = success
        self.stop_reason = stop_reason
        self.state_fingerprint = state_fingerprint


def _state_fingerprint(state: ReasoningState) -> str:
    payload = json.dumps(
        {
            "query": state.query,
            "context": state.context,
            "iteration_count": state.iteration_count,
            "loop_decision": state.loop_decision,
            "overall_confidence": state.overall_confidence,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class ReasoningHarness:
    """Orchestrates the cognitive reasoning loop.

    Runs the configured pipeline of nodes (planner → retriever → verifier →
    reflection), then checks loop_decision. On "revise", loops back. On
    "finalize" or max iterations, stops. Captures telemetry on each run.
    """

    def __init__(
        self,
        registry: NodeRegistry | None = None,
        max_iterations: int = 5,
        telemetry_dir: str | None = None,
    ) -> None:
        self._registry = registry or NodeRegistry()
        self._max_iterations = max_iterations
        self._telemetry = ReasoningTelemetry(output_dir=telemetry_dir or ".reasoning_traces")

    def run(self, state: ReasoningState) -> HarnessResult:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        pipeline = self._registry.get_pipeline()

        success = False
        stop_reason = "max_iterations_exhausted"

        while state.iteration_count < min(state.max_iterations, self._max_iterations):
            state.iteration_count += 1

            for node_name in pipeline:
                node = self._registry.get(node_name)
                if node is None:
                    stop_reason = "missing_node"
                    break

                started_at = datetime.now(UTC)
                try:
                    result = node.execute(state)
                except Exception:
                    stop_reason = "node_error"
                    self._telemetry.capture(run_id=run_id, state=state)
                    return HarnessResult(
                        state=state,
                        run_id=run_id,
                        success=False,
                        stop_reason="node_error",
                        state_fingerprint=_state_fingerprint(state),
                    )
                duration_ms = (datetime.now(UTC) - started_at).total_seconds() * 1000

                state.record_step(
                    node_name=node_name,
                    result={
                        **result.state_updates,
                        "duration_ms": duration_ms,
                    },
                    confidence=result.confidence,
                    message=result.message,
                )

                state.assertions.extend(result.new_assertions)

                for key, value in result.state_updates.items():
                    if key == "loop_decision":
                        state.loop_decision = value
                    elif key == "overall_confidence":
                        state.overall_confidence = value
                    elif key == "action_plan":
                        from finance.cognition.state.action import ActionPlan

                        if isinstance(value, dict):
                            state.action_plan = ActionPlan.model_validate(value)
                        else:
                            state.action_plan = value
                        state.context[key] = value
                    else:
                        state.context[key] = value

            if stop_reason == "missing_node":
                break

            if state.loop_decision == "finalize":
                success = True
                stop_reason = "finalize"
                break

        self._telemetry.capture(run_id=run_id, state=state)
        return HarnessResult(
            state=state,
            run_id=run_id,
            success=success,
            stop_reason=stop_reason,
            state_fingerprint=_state_fingerprint(state),
        )
