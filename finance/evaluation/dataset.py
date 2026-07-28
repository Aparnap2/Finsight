"""Pydantic models for golden test datasets used in evaluation runs.

Each dataset defines a scenario (input + expected behaviour) across five
concerns — planning, execution, verification, reflection, and output.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class DatasetMetadata(BaseModel):
    """Classification and identification metadata for a golden dataset."""

    id: str
    name: str
    category: str = "financial_logic"
    subcategory: str = ""
    description: str = ""
    tags: list[str] = []
    difficulty: str = "basic"


class DatasetInput(BaseModel):
    """Input payload fed into the cognitive harness."""

    query: str = ""
    context: dict[str, Any] = {}
    spreadsheet_data: dict[str, list[list[str]]] = {}
    variances: list[dict[str, Any]] = []


class PlanningExpectation(BaseModel):
    """What the planner should (and should not) produce."""

    required_intents: list[str] = []
    forbidden_intents: list[str] = []
    min_actions: int = 1
    max_actions: int | None = None
    max_replans: int = 0


class ExecutionExpectation(BaseModel):
    """How the executor should perform."""

    min_success_rate: float = 1.0
    max_retries_total: int = 0
    max_failed_actions: int = 0
    max_latency_ms: int | None = None


class VerificationExpectation(BaseModel):
    """Quality gates for assertions and evidence."""

    max_unsupported: int = 0
    max_contradictions: int = 0
    max_low_confidence: int = 0
    min_evidence: int = 0
    min_confidence: float = 0.0


class ReflectionExpectation(BaseModel):
    """Expected reflection outcome."""

    expected_decision: str = "finalize"
    max_gaps: int = 0


class OutputExpectation(BaseModel):
    """Expected pipeline output (variances, KPIs, report content)."""

    variances: list[dict[str, Any]] = []
    kpis: list[dict[str, Any]] = []
    report_sections: dict[str, str] = {}
    required_claims: list[str] = []
    forbidden_claims: list[str] = []


class ExpectedBehaviour(BaseModel):
    """Aggregate expectations across all five cognitive concerns."""

    planning: PlanningExpectation = PlanningExpectation()
    execution: ExecutionExpectation = ExecutionExpectation()
    verification: VerificationExpectation = VerificationExpectation()
    reflection: ReflectionExpectation = ReflectionExpectation()
    output: OutputExpectation = OutputExpectation()


class GoldenDataset(BaseModel):
    """A golden dataset for evaluating the cognitive reasoning pipeline.

    Combines metadata, input data, and structured expectations across all
    stages of the pipeline so that evaluation can score runtime behaviour
    and financial accuracy independently.
    """

    metadata: DatasetMetadata
    input: DatasetInput
    expected: ExpectedBehaviour = ExpectedBehaviour()
