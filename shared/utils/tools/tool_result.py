import hashlib
from typing import Any, Literal

from pydantic import BaseModel

from shared.models.degraded_mode import DegradedMode


class ToolResult(BaseModel):
    """Standard contract returned by every evidence-gathering tool.

    Describes the quality, scope, and provenance of every tool query result.
    Immutable once constructed.
    """

    data: list[dict[str, Any]] | dict[str, Any]
    row_count: int
    coverage_pct: float  # 0.0–1.0, how complete vs expected
    quality_score: float  # 0.0–1.0 — based on completeness, freshness, accuracy signals
    freshness_seconds: int | None  # seconds since data was last refreshed
    schema_version: str  # version of the result schema, e.g. "1.0"
    source_diversity: int  # number of distinct source tables/collections queried
    source_type: Literal["financial_fact", "operational_metric", "policy_doc", "precedent"]
    retrieval_scope: Literal["factual", "precedent", "policy"]
    tenant_id: str  # tenant context
    required_filters_present: bool  # whether all required filters (tenant, period) were applied
    insufficient_data: bool  # flag when coverage or row_count below threshold
    degraded_mode: str | None  # None or one of the DegradedMode enum values
    query_fingerprint: str | None  # hash of the query for dedup/caching

    class Config:
        frozen = True  # immutable once constructed


# ── Helper utilities for computing derived fields ──────────────────────────


def compute_quality_score(
    coverage_pct: float,
    row_count: int,
    freshness_seconds: int | None = None,
    max_freshness_threshold: int = 7 * 24 * 3600,  # 7 days
) -> float:
    """Compute a quality score between 0.0 and 1.0.

    Factors:
    - coverage_pct (primary): how complete the data is
    - row_count > 0: whether we got any data at all
    - freshness_seconds (optional): penalise stale data
    """
    if row_count == 0:
        return 0.0

    # Base score from coverage
    if coverage_pct >= 0.9:
        base = 1.0
    elif coverage_pct >= 0.7:
        base = 0.85
    elif coverage_pct >= 0.5:
        base = 0.7
    elif coverage_pct > 0.0:
        base = 0.5
    else:
        base = 0.3

    # Freshness penalty: if data is very stale, knock up to 0.2 off
    if freshness_seconds is not None and freshness_seconds > max_freshness_threshold:
        # Linear decay from threshold to 30 days
        penalty = min(0.2, (freshness_seconds - max_freshness_threshold) / (30 * 24 * 3600) * 0.2)
        base = max(0.0, base - penalty)

    return round(base, 4)


def compute_degraded_mode(coverage_pct: float, row_count: int) -> str | None:
    """Determine the degraded mode based on coverage and row count."""
    if row_count == 0:
        return DegradedMode.LOW_COVERAGE.value
    if coverage_pct < 0.5:
        return DegradedMode.LOW_COVERAGE.value
    return None


def compute_query_fingerprint(function_name: str, **params: Any) -> str:
    """Compute a deterministic hash of function_name + parameters for dedup/caching."""
    # Sort items for deterministic ordering
    sorted_items = sorted(params.items())
    raw = f"{function_name}:{sorted_items}"
    return hashlib.md5(raw.encode()).hexdigest()
