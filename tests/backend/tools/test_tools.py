import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models.database import Base
from backend.data.seed import seed_database
from backend.tools.gl_tools import query_gl_detail, query_trial_balance
from backend.tools.headcount_tools import query_headcount
from backend.tools.vendor_tools import query_vendor_spend
from backend.tools.pipeline_tools import query_sales_pipeline
from backend.tools.rag_tools import query_prior_commentary, query_policy_document


@pytest.fixture(scope="module")
def seeded_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session)
    return engine


TENANT = "CF001"
PERIOD = "2026-06"


# ── GL tools ─────────────────────────────────────────────────────────────────


def test_query_gl_detail_returns_data(seeded_engine):
    result = query_gl_detail(tenant_id=TENANT, period=PERIOD, engine=seeded_engine)
    assert isinstance(result, object)
    assert result.tenant_id == TENANT
    assert result.row_count > 0
    assert len(result.data) == result.row_count
    assert "account_number" in result.data[0]
    assert result.source_type == "financial_fact"


def test_query_gl_detail_by_account(seeded_engine):
    # First find a real account_id
    all_result = query_gl_detail(tenant_id=TENANT, period=PERIOD, engine=seeded_engine)
    acct_id = all_result.data[0]["account_id"]

    result = query_gl_detail(
        tenant_id=TENANT, period=PERIOD, account_id=acct_id, engine=seeded_engine
    )
    assert result.row_count >= 1
    assert all(r["account_id"] == acct_id for r in result.data)


def test_query_gl_detail_coverage(seeded_engine):
    result = query_gl_detail(tenant_id=TENANT, period=PERIOD, engine=seeded_engine)
    assert 0.0 <= result.coverage_pct <= 1.0
    assert isinstance(result.insufficient_data, bool)


def test_query_gl_detail_unknown_tenant(seeded_engine):
    result = query_gl_detail(tenant_id="NONEXIST", period=PERIOD, engine=seeded_engine)
    assert result.row_count == 0
    assert result.insufficient_data is True


def test_query_trial_balance_returns_data(seeded_engine):
    result = query_trial_balance(tenant_id=TENANT, period=PERIOD, engine=seeded_engine)
    assert result.row_count > 0
    assert "debit" in result.data[0]
    assert "credit" in result.data[0]
    assert result.source_type == "financial_fact"


def test_query_trial_balance_reconciled(seeded_engine):
    result = query_trial_balance(tenant_id=TENANT, period=PERIOD, engine=seeded_engine)
    total_debits = sum(r["debit"] for r in result.data)
    total_credits = sum(r["credit"] for r in result.data)
    assert abs(total_debits - total_credits) < 0.01


def test_query_trial_balance_coverage(seeded_engine):
    result = query_trial_balance(tenant_id=TENANT, period=PERIOD, engine=seeded_engine)
    assert 0.0 <= result.coverage_pct <= 1.0


# ── Headcount tools ───────────────────────────────────────────────────────────


def test_query_headcount_returns_data(seeded_engine):
    result = query_headcount(tenant_id=TENANT, period=PERIOD, engine=seeded_engine)
    assert result.row_count > 0
    dept = result.data[0]
    assert "department" in dept
    assert "headcount" in dept
    assert dept["headcount"] > 0
    assert result.source_type == "operational_metric"


def test_query_headcount_by_department(seeded_engine):
    result = query_headcount(
        tenant_id=TENANT, period=PERIOD, department="Engineering", engine=seeded_engine
    )
    assert result.row_count >= 1
    assert all(r["department"] == "Engineering" for r in result.data)


def test_query_headcount_no_match(seeded_engine):
    result = query_headcount(
        tenant_id=TENANT, period=PERIOD, department="BogusDept", engine=seeded_engine
    )
    assert result.row_count == 0
    assert result.insufficient_data is True


# ── Vendor tools ──────────────────────────────────────────────────────────────


def test_query_vendor_spend_returns_data(seeded_engine):
    result = query_vendor_spend(tenant_id=TENANT, period=PERIOD, engine=seeded_engine)
    assert result.row_count > 0
    assert "vendor_name" in result.data[0]
    assert "amount" in result.data[0]
    assert result.source_type == "operational_metric"


def test_query_vendor_spend_by_vendor(seeded_engine):
    result = query_vendor_spend(
        tenant_id=TENANT, period=PERIOD, vendor="AWS", engine=seeded_engine
    )
    assert result.row_count >= 1
    assert all(r["vendor_name"] == "AWS" for r in result.data)


def test_query_vendor_spend_freshness(seeded_engine):
    result = query_vendor_spend(tenant_id=TENANT, period=PERIOD, engine=seeded_engine)
    # All seeded invoices use invoice_date=2026-06-15
    assert result.freshness_seconds is not None
    assert result.freshness_seconds >= 0


# ── Pipeline tools ────────────────────────────────────────────────────────────


def test_query_sales_pipeline_returns_data(seeded_engine):
    result = query_sales_pipeline(tenant_id=TENANT, period=PERIOD, engine=seeded_engine)
    assert result.row_count > 0
    assert "deal_name" in result.data[0]
    assert "stage" in result.data[0]
    assert "amount" in result.data[0]
    assert result.source_type == "operational_metric"


def test_query_sales_pipeline_filtered(seeded_engine):
    result = query_sales_pipeline(
        tenant_id=TENANT, period=PERIOD, region="EMEA", product="Product X", engine=seeded_engine
    )
    assert result.row_count >= 1
    assert all(r["region"] == "EMEA" for r in result.data)
    assert all(r["product"] == "Product X" for r in result.data)


def test_query_sales_pipeline_coverage(seeded_engine):
    result = query_sales_pipeline(tenant_id=TENANT, period=PERIOD, engine=seeded_engine)
    assert 0.0 <= result.coverage_pct <= 1.0


# ── RAG tools ─────────────────────────────────────────────────────────────────


def test_query_prior_commentary(seeded_engine):
    result = query_prior_commentary(
        tenant_id=TENANT, period=PERIOD, engine=seeded_engine
    )
    assert isinstance(result, object)
    assert result.source_type == "precedent"
    # No commentary_drafts are seeded, so data should be empty
    assert result.row_count == 0


def test_query_policy_document():
    result = query_policy_document("revenue recognition")
    assert result.row_count == 0
    assert result.insufficient_data is True
    assert result.source_type == "policy_doc"
