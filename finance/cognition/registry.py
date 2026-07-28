from __future__ import annotations

from typing import TYPE_CHECKING

from finance.cognition.state.node import CognitiveNode

if TYPE_CHECKING:
    from finance.evidence.engine import EvidenceEngine
    from finance.formula_engine.evaluator import FormulaEvaluator
    from finance.integration.spreadsheet_provider import SpreadsheetProvider
    from finance.validation.harness import ValidationSuite
    from finance.variance_engine.materiality import MaterialityEngine


class NodeRegistry:
    """Registry of named cognitive nodes with configurable pipeline order.

    Optional engine dependencies can be injected at construction time;
    they are forwarded to the default nodes that support them.
    """

    def __init__(
        self,
        spreadsheet_provider: SpreadsheetProvider | None = None,
        materiality_engine: MaterialityEngine | None = None,
        formula_evaluator: FormulaEvaluator | None = None,
        evidence_engine: EvidenceEngine | None = None,
        validation_suite: ValidationSuite | None = None,
    ) -> None:
        self._nodes: dict[str, CognitiveNode] = {}
        self._pipeline: list[str] = [
            "planner",
            "retriever",
            "executor",
            "verifier",
            "reflection",
        ]
        self._register_defaults(
            spreadsheet_provider=spreadsheet_provider,
            materiality_engine=materiality_engine,
            formula_evaluator=formula_evaluator,
            evidence_engine=evidence_engine,
            validation_suite=validation_suite,
        )

    def _register_defaults(
        self,
        spreadsheet_provider: SpreadsheetProvider | None = None,
        materiality_engine: MaterialityEngine | None = None,
        formula_evaluator: FormulaEvaluator | None = None,
        evidence_engine: EvidenceEngine | None = None,
        validation_suite: ValidationSuite | None = None,
    ) -> None:
        from finance.cognition.nodes import (
            PlannerNode,
            ReflectionNode,
            VerifierNode,
        )
        from finance.cognition.nodes.executor import ExecutorNode
        from finance.cognition.nodes.retriever import RetrieverNode

        self.register("planner", PlannerNode())
        self.register("retriever", RetrieverNode(
            spreadsheet_provider=spreadsheet_provider,
        ))
        self.register("executor", ExecutorNode(
            materiality_engine=materiality_engine,
            formula_evaluator=formula_evaluator,
            evidence_engine=evidence_engine,
            validation_suite=validation_suite,
        ))
        self.register("verifier", VerifierNode())
        self.register("reflection", ReflectionNode())

    def register(self, name: str, node: CognitiveNode) -> None:
        self._nodes[name] = node

    def get(self, name: str) -> CognitiveNode | None:
        return self._nodes.get(name)

    def list_nodes(self) -> list[str]:
        return list(self._nodes.keys())

    def configure_pipeline(self, pipeline: list[str]) -> None:
        for name in pipeline:
            if name not in self._nodes:
                raise ValueError(
                    f"Node '{name}' not registered. "
                    f"Registered: {list(self._nodes)}"
                )
        self._pipeline = list(pipeline)

    def get_pipeline(self) -> list[str]:
        return list(self._pipeline)

    def default_pipeline(self) -> list[str]:
        return [
            "planner",
            "retriever",
            "executor",
            "verifier",
            "reflection",
        ]
