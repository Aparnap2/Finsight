"""Reasoning pipeline — deterministic evidence → assertion → confidence → commentary.

Public entry point: :func:`run_reasoning_pipeline`. The pipeline is fully
deterministic when used with the default :class:`NullCommentaryProvider`
and stays deterministic under test with a fake ``CommentaryProvider``.
"""

from finance.reasoning.confidence import (
    agreement_score,
    materiality_factor,
    score_assertion,
    source_reliability,
)
from finance.reasoning.llm_boundary import (
    CommentaryOutput,
    CommentaryProvider,
    NullCommentaryProvider,
    StructuredCommentaryProvider,
)
from finance.reasoning.pipeline import ReasoningContext, run_reasoning_pipeline
from finance.reasoning.report import ProvenanceEntry, ReasoningReport

__all__ = [
    "CommentaryOutput",
    "CommentaryProvider",
    "NullCommentaryProvider",
    "ProvenanceEntry",
    "ReasoningContext",
    "ReasoningReport",
    "StructuredCommentaryProvider",
    "agreement_score",
    "materiality_factor",
    "run_reasoning_pipeline",
    "score_assertion",
    "source_reliability",
]
