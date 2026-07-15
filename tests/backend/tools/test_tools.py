from backend.tools.gl_tools import drill_gl_detail, fetch_trial_balance
from backend.tools.headcount_tools import query_headcount
from backend.tools.vendor_tools import query_vendor_invoices
from backend.tools.pipeline_tools import query_sales_pipeline
from backend.tools.rag_tools import search_historical_variances, search_finance_policy


def test_drill_gl_detail():
    result = drill_gl_detail(account_id="4000", period="2026-06")
    assert isinstance(result, list)
    assert result[0]["account_id"] == "4000"


def test_drill_gl_detail_with_department():
    result = drill_gl_detail(account_id="4000", period="2026-06", department="Sales")
    assert isinstance(result, list)


def test_fetch_trial_balance():
    result = fetch_trial_balance(period="2026-06")
    assert isinstance(result, list)
    assert "total_debits" in result[0]
    assert "total_credits" in result[0]


def test_fetch_trial_balance_reconciled():
    result = fetch_trial_balance(period="2026-06")
    assert result[0]["total_debits"] == result[0]["total_credits"]


def test_query_headcount():
    result = query_headcount(department="Engineering", period="2026-06")
    assert isinstance(result, dict)
    assert result["department"] == "Engineering"
    assert result["headcount"] > 0


def test_query_vendor_invoices():
    result = query_vendor_invoices(vendor_name="AWS", period="2026-06")
    assert isinstance(result, list)
    assert result[0]["vendor"] == "AWS"


def test_query_sales_pipeline():
    result = query_sales_pipeline(region="EMEA")
    assert isinstance(result, list)
    assert "deal" in result[0]


def test_query_sales_pipeline_filtered():
    result = query_sales_pipeline(region="EMEA", product="Product X")
    assert isinstance(result, list)


def test_search_historical_variances():
    result = search_historical_variances("EMEA revenue decline")
    assert isinstance(result, list)
    assert len(result) > 0


def test_search_finance_policy():
    result = search_finance_policy("revenue recognition")
    assert isinstance(result, list)
    assert len(result) > 0
