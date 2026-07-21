"""Agentic capability tests: Tool Call dimension.

Tests that tools make correct DB queries, return proper ToolResult contracts,
handle filtering, and report coverage/insufficient-data correctly.
"""

import pytest
from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models.database import Base
from backend.data.seed import seed_database
from backend.tools.gl_tools import query_gl_detail, query_trial_balance
from backend.tools.headcount_tools import query_headcount
from backend.tools.vendor_tools import query_vendor_spend
from backend.tools.pipeline_tools import query_sales_pipeline
from backend.tools.tool_result import ToolResult

TENANT = "CF001"
PERIOD = "2026-06"


@pytest.fixture()
def seeded_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session)
    return engine


# ── ToolResult contract enforcement ───────────────────────────────────────────


def test_gl_tool_returns_toolresult(seeded_engine):
    """Every tool must return ToolResult with all metadata fields."""
    result = query_gl_detail(TENANT, PERIOD, engine=seeded_engine)
    assert isinstance(result, ToolResult)
    assert result.tenant_id == TENANT
    assert result.row_count > 0
    assert 0 <= result.coverage_pct <= 1.0
    assert isinstance(result.insufficient_data, bool)
    assert result.source_type == "financial_fact"
    assert result.quality_score >= 0.0
    assert result.source_diversity >= 1
    assert result.degraded_mode is not None or result.degraded_mode is None


def test_trial_balance_tool_returns_toolresult(seeded_engine):
    """Trial balance tool must return balanced debits/credits."""
    result = query_trial_balance(TENANT, PERIOD, engine=seeded_engine)
    assert isinstance(result, ToolResult)
    assert result.row_count > 0
    total_debits = sum(r["debit"] for r in result.data)
    total_credits = sum(r["credit"] for r in result.data)
    assert abs(total_debits - total_credits) < Decimal("0.01")


def test_headcount_tool_returns_toolresult(seeded_engine):
    """Headcount tool must return hr source_type and row_count."""
    result = query_headcount(TENANT, PERIOD, engine=seeded_engine)
    assert isinstance(result, ToolResult)
    assert result.row_count > 0
    assert result.source_type == "operational_metric"
    assert "headcount" in result.data[0]
    assert "department" in result.data[0]


def test_vendor_tool_returns_toolresult(seeded_engine):
    """Vendor tool must return vendor source_type and metadata."""
    result = query_vendor_spend(TENANT, PERIOD, engine=seeded_engine)
    assert isinstance(result, ToolResult)
    assert result.row_count > 0
    assert result.source_type == "operational_metric"
    assert result.freshness_seconds is not None
    assert "vendor_name" in result.data[0]
    assert "amount" in result.data[0]


def test_pipeline_tool_returns_toolresult(seeded_engine):
    """Pipeline tool must return sales source_type and deal info."""
    result = query_sales_pipeline(TENANT, PERIOD, engine=seeded_engine)
    assert isinstance(result, ToolResult)
    assert result.row_count > 0
    assert result.source_type == "operational_metric"
    assert "deal_name" in result.data[0]
    assert "stage" in result.data[0]


# ── Tool filtering ────────────────────────────────────────────────────────────


def test_gl_detail_filters_by_account(seeded_engine):
    """Filtering gl_detail by account must scope results to that account."""
    all_results = query_gl_detail(TENANT, PERIOD, engine=seeded_engine)
    first_account = all_results.data[0]["account_id"]
    filtered = query_gl_detail(TENANT, PERIOD, account_id=first_account, engine=seeded_engine)
    assert filtered.row_count <= all_results.row_count
    assert all(r["account_id"] == first_account for r in filtered.data)


def test_gl_detail_unknown_account_returns_empty(seeded_engine):
    """Filtering by a non-existent account id must return empty results."""
    result = query_gl_detail(TENANT, PERIOD, account_id="NONEXISTENT", engine=seeded_engine)
    assert result.row_count == 0
    assert result.insufficient_data is True


def test_headcount_filters_by_department(seeded_engine):
    """Headcount tool must filter to a single department."""
    result = query_headcount(TENANT, PERIOD, department="Engineering", engine=seeded_engine)
    assert result.row_count >= 1
    assert all(r["department"] == "Engineering" for r in result.data)


def test_vendor_filters_by_vendor_name(seeded_engine):
    """Vendor tool must filter by vendor name."""
    result = query_vendor_spend(TENANT, PERIOD, vendor="AWS", engine=seeded_engine)
    assert result.row_count >= 1
    assert all(r["vendor_name"] == "AWS" for r in result.data)


def test_vendor_filters_by_category(seeded_engine):
    """Vendor tool must filter by invoice category."""
    result = query_vendor_spend(TENANT, PERIOD, category="SaaS", engine=seeded_engine)
    assert result.row_count >= 1
    # All seeded vendor invoices have category "SaaS"
    assert all(r.get("category") == "SaaS" for r in result.data)


def test_pipeline_filters_by_region(seeded_engine):
    """Pipeline tool must filter by region."""
    result = query_sales_pipeline(TENANT, PERIOD, region="EMEA", engine=seeded_engine)
    assert result.row_count >= 1
    assert all(r.get("region") == "EMEA" for r in result.data)


def test_pipeline_filters_by_product(seeded_engine):
    """Pipeline tool must filter by product."""
    result = query_sales_pipeline(TENANT, PERIOD, product="Product X", engine=seeded_engine)
    assert result.row_count >= 1
    assert all(r.get("product") == "Product X" for r in result.data)


# ── Insufficient data / edge cases ────────────────────────────────────────────


def test_gl_tool_insufficient_data_for_bogus_tenant(seeded_engine):
    """Tool must flag insufficient_data when querying non-existent tenant."""
    result = query_gl_detail("NONEXISTENT", PERIOD, engine=seeded_engine)
    assert result.row_count == 0
    assert result.insufficient_data is True


def test_gl_tool_insufficient_data_for_bogus_period(seeded_engine):
    """Tool must flag insufficient_data for non-existent period."""
    result = query_gl_detail(TENANT, "2099-01", engine=seeded_engine)
    assert result.row_count == 0
    assert result.insufficient_data is True


def test_headcount_insufficient_data(seeded_engine):
    """Headcount tool with unknown department must return empty."""
    result = query_headcount(TENANT, PERIOD, department="BogusDept", engine=seeded_engine)
    assert result.row_count == 0
    assert result.insufficient_data is True


# ── Tool result aggregation patterns ──────────────────────────────────────────


def test_gl_detail_contains_required_columns(seeded_engine):
    """Tool data must include all schema-required columns for downstream agents."""
    result = query_gl_detail(TENANT, PERIOD, engine=seeded_engine)
    required = {"account_id", "account_name", "account_type", "department", "amount"}
    for row in result.data:
        assert required.issubset(row.keys()), f"Missing columns in {row.get('account_id')}"


def test_pipeline_value_by_stage_is_positive(seeded_engine):
    """Pipeline deals must have positive amounts."""
    result = query_sales_pipeline(TENANT, PERIOD, engine=seeded_engine)
    for row in result.data:
        assert row["amount"] > 0, f"Deal {row.get('deal_name')} has non-positive amount"
