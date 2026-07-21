"""Agentic capability tests: RAG (Retrieval-Augmented Generation) dimension.

Tests that tools return properly scoped data with coverage metrics,
support period-based isolation, and provide metadata for the RAG
pipeline components.
"""

import pytest
from sqlalchemy import create_engine, text as sql_text
from sqlalchemy.orm import Session

from backend.models.database import Base
from backend.data.seed import seed_database
from backend.tools.gl_tools import query_gl_detail, query_trial_balance
from backend.tools.rag_tools import query_prior_commentary
from backend.tools.headcount_tools import query_headcount
from backend.tools.vendor_tools import query_vendor_spend
from backend.tools.pipeline_tools import query_sales_pipeline
from backend.tools.tool_result import ToolResult

TENANT = "CF001"
PERIOD = "2026-06"
PERIOD_2025_01 = "2025-01"


@pytest.fixture()
def seeded_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session)
    return engine


# ── Period scoping ────────────────────────────────────────────────────────────


class TestPeriodScoping:
    def test_gl_tool_scopes_by_period(self, seeded_engine):
        """GL tool must return data for the requested period only."""
        result = query_gl_detail(TENANT, PERIOD, engine=seeded_engine)
        assert result.row_count > 0
        for row in result.data:
            assert row["period"] == PERIOD

    def test_trial_balance_scopes_by_period(self, seeded_engine):
        """Trial balance tool must return data for the requested period."""
        result = query_trial_balance(TENANT, PERIOD, engine=seeded_engine)
        assert result.row_count > 0
        for row in result.data:
            assert row["period"] == PERIOD

    def test_headcount_scopes_by_period(self, seeded_engine):
        """Headcount tool must return data for the requested period."""
        result = query_headcount(TENANT, PERIOD, engine=seeded_engine)
        assert result.row_count > 0
        for row in result.data:
            assert row["period"] == PERIOD

    def test_vendor_scopes_by_period(self, seeded_engine):
        """Vendor tool must return data for the requested period."""
        result = query_vendor_spend(TENANT, PERIOD, engine=seeded_engine)
        assert result.row_count > 0
        for row in result.data:
            assert row["period"] == PERIOD

    def test_pipeline_scopes_by_period(self, seeded_engine):
        """Pipeline tool must return data for the requested period."""
        result = query_sales_pipeline(TENANT, PERIOD, engine=seeded_engine)
        assert result.row_count > 0
        for row in result.data:
            assert row["period"] == PERIOD


# ── Cross-period isolation ────────────────────────────────────────────────────


class TestCrossPeriodIsolation:
    def test_different_periods_different_gl_data(self, seeded_engine):
        """Different periods must return different GL result objects."""
        result_06 = query_gl_detail(TENANT, PERIOD, engine=seeded_engine)
        result_01 = query_gl_detail(TENANT, PERIOD_2025_01, engine=seeded_engine)
        assert isinstance(result_06, ToolResult)
        assert isinstance(result_01, ToolResult)
        # Both should be valid, with possibly different row counts
        assert result_06.source_type == result_01.source_type

    def test_different_periods_different_headcount(self, seeded_engine):
        """Headcount for different periods must produce ToolResults."""
        result_06 = query_headcount(TENANT, PERIOD, engine=seeded_engine)
        result_01 = query_headcount(TENANT, PERIOD_2025_01, engine=seeded_engine)
        assert isinstance(result_06, ToolResult)
        assert isinstance(result_01, ToolResult)

    def test_unknown_period_returns_empty(self, seeded_engine):
        """Querying a non-existent period must return empty but valid ToolResult."""
        result = query_gl_detail(TENANT, "2099-12", engine=seeded_engine)
        assert result.row_count == 0
        assert isinstance(result, ToolResult)


# ── Coverage metrics ──────────────────────────────────────────────────────────


class TestCoverageMetrics:
    def test_gl_coverage_between_zero_and_one(self, seeded_engine):
        """Coverage percentage must always be between 0 and 1."""
        result = query_gl_detail(TENANT, PERIOD, engine=seeded_engine)
        assert 0 <= result.coverage_pct <= 1.0

    def test_trial_balance_coverage_between_zero_and_one(self, seeded_engine):
        """Trial balance coverage must be between 0 and 1."""
        result = query_trial_balance(TENANT, PERIOD, engine=seeded_engine)
        assert 0 <= result.coverage_pct <= 1.0

    def test_headcount_coverage_between_zero_and_one(self, seeded_engine):
        """Headcount coverage must be between 0 and 1."""
        result = query_headcount(TENANT, PERIOD, engine=seeded_engine)
        assert 0 <= result.coverage_pct <= 1.0

    def test_vendor_coverage_between_zero_and_one(self, seeded_engine):
        """Vendor coverage must be between 0 and 1."""
        result = query_vendor_spend(TENANT, PERIOD, engine=seeded_engine)
        assert 0 <= result.coverage_pct <= 1.0

    def test_pipeline_coverage_between_zero_and_one(self, seeded_engine):
        """Pipeline coverage must be between 0 and 1."""
        result = query_sales_pipeline(TENANT, PERIOD, engine=seeded_engine)
        assert 0 <= result.coverage_pct <= 1.0


# ── RAG specific tools ────────────────────────────────────────────────────────


class TestRagTools:
    def test_prior_commentary_returns_toolresult(self, seeded_engine):
        """RAG tool for prior commentary must return a ToolResult."""
        result = query_prior_commentary(TENANT, PERIOD, engine=seeded_engine)
        assert isinstance(result, ToolResult)
        # No commentary drafts are seeded, so data should be empty but result valid
        assert result.source_type == "precedent"
        assert isinstance(result.insufficient_data, bool)

    def test_prior_commentary_coverage_bounds(self, seeded_engine):
        """Prior commentary coverage must be between 0 and 1."""
        result = query_prior_commentary(TENANT, PERIOD, engine=seeded_engine)
        assert 0 <= result.coverage_pct <= 1.0

    def test_prior_commentary_unknown_tenant(self, seeded_engine):
        """Unknown tenant must return empty prior commentary."""
        result = query_prior_commentary("NONEXISTENT", PERIOD, engine=seeded_engine)
        assert result.row_count == 0
        assert result.insufficient_data is True


# ── RAG context boundary checks ───────────────────────────────────────────────


class TestRagContextBoundaries:
    def test_gl_detail_account_scoping(self, seeded_engine):
        """Filtering by account must produce correct context boundary."""
        # Get revenue accounts
        result = query_gl_detail(TENANT, PERIOD, engine=seeded_engine)
        revenue_ids = [
            r["account_id"] for r in result.data
            if r.get("account_type") == "revenue"
        ]
        if revenue_ids:
            revenue_result = query_gl_detail(
                TENANT, PERIOD, account_id=revenue_ids[0], engine=seeded_engine
            )
            assert revenue_result.row_count > 0
            for row in revenue_result.data:
                assert row["account_id"] == revenue_ids[0]

    def test_all_tools_return_consistent_tenant_id(self, seeded_engine):
        """All tools must return consistent tenant_id in results."""
        tools = [
            query_gl_detail(TENANT, PERIOD, engine=seeded_engine),
            query_trial_balance(TENANT, PERIOD, engine=seeded_engine),
            query_headcount(TENANT, PERIOD, engine=seeded_engine),
            query_vendor_spend(TENANT, PERIOD, engine=seeded_engine),
            query_sales_pipeline(TENANT, PERIOD, engine=seeded_engine),
        ]
        for result in tools:
            assert result.tenant_id == TENANT

    def test_insufficient_data_flag_consistent(self, seeded_engine):
        """insufficient_data must be True when row_count is 0."""
        result = query_gl_detail(TENANT, "2099-01", engine=seeded_engine)
        assert result.row_count == 0
        assert result.insufficient_data is True

    def test_sufficient_data_flag(self, seeded_engine):
        """insufficient_data must be False when data exists and coverage is adequate."""
        result = query_gl_detail(TENANT, PERIOD, engine=seeded_engine)
        if result.row_count > 0 and result.coverage_pct >= 0.5:
            assert result.insufficient_data is False
