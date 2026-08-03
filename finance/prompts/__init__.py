"""FinSight Prompt Harness.

Typed, versioned prompt templates for FP&A AI agents. Provides schemas,
registry, renderer, execution context, and pre-built templates for all
prompt types used in the FinSight platform.
"""

from finance.prompts.execution_context import ExecutionContext
from finance.prompts.registry import PromptRegistry, PromptTemplate
from finance.prompts.renderer import PromptRenderer
from finance.prompts.schemas import (
    BoardReportInput,
    ExecutiveSummaryInput,
    ExecutiveSummaryOutput,
    VarianceAnalysisInput,
    VarianceAnalysisOutput,
)

__all__ = [
    "BoardReportInput",
    "ExecutiveSummaryInput",
    "ExecutiveSummaryOutput",
    "ExecutionContext",
    "PromptRegistry",
    "PromptRenderer",
    "PromptTemplate",
    "VarianceAnalysisInput",
    "VarianceAnalysisOutput",
]
