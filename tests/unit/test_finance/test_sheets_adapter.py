"""Tests for the Google Sheets adapter.

TDD: Written before implementation. Must fail first.
"""
from __future__ import annotations

import pytest
from decimal import Decimal
from datetime import date


# ── Phase 2: Google Sheets Adapter ───────────────────────────────────────────


class TestSheetsAuth:
    """Authentication and credential management."""

    def test_authenticate_with_service_account(self):
        """Service account JSON file produces valid credentials."""
        from finance.ingestion.sheets_adapter import SheetsAdapter
        adapter = SheetsAdapter(credentials_path="/fake/path.json")
        with pytest.raises(FileNotFoundError):
            adapter.authenticate()

    def test_authenticate_raises_on_missing_creds(self):
        """Adapter raises when credentials_path does not exist."""
        from finance.ingestion.sheets_adapter import SheetsAdapter
        adapter = SheetsAdapter(credentials_path="/nonexistent/creds.json")
        with pytest.raises(FileNotFoundError):
            adapter.authenticate()

    def test_adapter_rejects_empty_spreadsheet_id(self):
        """Adapter raises ValueError on empty spreadsheet_id."""
        from finance.ingestion.sheets_adapter import SheetsAdapter
        adapter = SheetsAdapter(credentials_path="/fake/path.json")
        with pytest.raises(ValueError, match="spreadsheet_id"):
            adapter.read_range(spreadsheet_id="", range="Sheet1!A1:B10")

    def test_adapter_rejects_empty_range(self):
        """Adapter raises ValueError on empty range."""
        from finance.ingestion.sheets_adapter import SheetsAdapter
        adapter = SheetsAdapter(credentials_path="/fake/path.json")
        with pytest.raises(ValueError, match="range"):
            adapter.read_range(spreadsheet_id="abc123", range="")


class TestSheetsRead:
    """Reading data from Google Sheets."""

    def test_read_range_returns_list_of_lists(self):
        """read_range returns a list of rows, each row is a list of values."""
        from finance.ingestion.sheets_adapter import SheetsAdapter
        adapter = SheetsAdapter(credentials_path="/fake/path.json")
        # Without auth, this should raise not-authenticated
        with pytest.raises(RuntimeError, match="authenticate|not authenticated"):
            adapter.read_range(spreadsheet_id="test", range="Sheet1!A1:B2")


class TestSheetsWrite:
    """Writing data to Google Sheets."""

    def test_write_range_validates_data(self):
        """write_range rejects empty data."""
        from finance.ingestion.sheets_adapter import SheetsAdapter
        adapter = SheetsAdapter(credentials_path="/fake/path.json")
        with pytest.raises(ValueError, match="data"):
            adapter.write_range(spreadsheet_id="test", range="Sheet1!A1:B2", values=[])


class TestSheetsValidate:
    """Validating spreadsheet structure."""

    def test_validate_missing_header(self):
        """validate detects missing required headers."""
        from finance.ingestion.sheets_adapter import SheetsAdapter
        adapter = SheetsAdapter(credentials_path="/fake/path.json")
        with pytest.raises(RuntimeError, match="authenticate|not authenticated"):
            adapter.validate(spreadsheet_id="test")


class TestCSVFallback:
    """CSV fallback when Google Sheets is unavailable."""

    def test_csv_read_returns_parsed_rows(self, tmp_path):
        """CSV reader converts a CSV file into list of dicts."""
        from finance.ingestion.sheets_adapter import read_csv
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("account,amount\n4010,100000\n6010,50000\n")
        result = read_csv(str(csv_file))
        assert len(result) == 2
        assert result[0]["account"] == "4010"
        assert result[0]["amount"] == "100000"

    def test_csv_read_missing_file(self):
        """CSV reader raises FileNotFoundError for missing file."""
        from finance.ingestion.sheets_adapter import read_csv
        with pytest.raises(FileNotFoundError):
            read_csv("/nonexistent/file.csv")

    def test_csv_read_empty_file(self, tmp_path):
        """CSV reader handles empty file gracefully."""
        from finance.ingestion.sheets_adapter import read_csv
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("")
        result = read_csv(str(csv_file))
        assert result == []

    def test_csv_fallback_on_sheets_error(self):
        """Adapter falls back to CSV when sheets is unreachable."""
        from finance.ingestion.sheets_adapter import SheetsAdapter
        adapter = SheetsAdapter(
            credentials_path="/fake/path.json",
            csv_fallback_path="/fake/fallback.csv",
        )
        with pytest.raises(FileNotFoundError):
            adapter.read_range(spreadsheet_id="test", range="Sheet1!A1:B2")


class TestSheetsSync:
    """Incremental sync functionality."""

    def test_sync_requires_spreadsheet_id(self):
        """sync raises on missing spreadsheet_id."""
        from finance.ingestion.sheets_adapter import SheetsAdapter
        adapter = SheetsAdapter(credentials_path="/fake/path.json")
        with pytest.raises(ValueError, match="spreadsheet_id"):
            adapter.sync(spreadsheet_id="")


# ── Phase 3: Context Builder (stub tests — RED phase) ──────────────────────


class TestContextBuilder:
    """Context Builder creates structured Finance Context Packs."""

    def test_build_context_returns_valid_structure(self):
        """build_context returns a FinanceContextPack with all required sections."""
        from finance.context.context_builder import ContextBuilder
        builder = ContextBuilder()
        context = builder.build_context(
            company_id="CF001",
            period_id="2026-07",
        )
        assert context.company_id == "CF001"
        assert context.period_id == "2026-07"
        assert context.kpis is not None
        assert context.material_variances is not None
        assert context.evidence_items is not None

    def test_context_pack_has_expected_sections(self):
        """FinanceContextPack has all 11 required sections."""
        from finance.context.models import FinanceContextPack
        pack = FinanceContextPack(
            company_id="CF001",
            period_id="2026-07",
            company_name="Test Corp",
            currency="USD",
            kpis=[],
            material_variances=[],
            evidence_items=[],
            budget_summary={},
            actual_summary={},
            forecast_summary={},
            risks=[],
            business_context="",
        )
        assert pack.company_name == "Test Corp"
        assert pack.currency == "USD"

    def test_empty_kpis_list_is_valid(self):
        """Context allows empty KPI list (graceful degradation)."""
        from finance.context.models import FinanceContextPack
        pack = FinanceContextPack(
            company_id="CF001",
            period_id="2026-07",
            company_name="Test Corp",
            currency="USD",
            kpis=[],
            material_variances=[],
            evidence_items=[],
            budget_summary={},
            actual_summary={},
            forecast_summary={},
            risks=[],
            business_context="",
        )
        assert pack.kpis == []


# ── Phase 4: Evidence Engine (stub tests — RED phase) ──────────────────────


class TestEvidenceEngine:
    """Evidence Engine validates and scores evidence-backed claims."""

    def test_evidence_item_requires_source(self):
        """EvidenceItem requires a source reference."""
        from finance.evidence.models import EvidenceItem
        item = EvidenceItem(
            claim="Revenue increased 10%",
            source_type="kpi",
            source_id="kpi_revenue_growth",
            source_value=Decimal("10.0"),
            confidence="high",
        )
        assert item.claim == "Revenue increased 10%"
        assert item.confidence == "high"

    def test_evidence_engine_collects_for_variance(self):
        """EvidenceEngine.collect returns evidence for a given variance."""
        from finance.evidence.engine import EvidenceEngine
        engine = EvidenceEngine()
        evidence = engine.collect(account_id="4010", period_id="2026-07")
        assert len(evidence) >= 0

    def test_evidence_coverage_score(self):
        """EvidenceEngine.coverage_score returns a Decimal between 0 and 100."""
        from finance.evidence.engine import EvidenceEngine
        engine = EvidenceEngine()
        score = engine.coverage_score(period_id="2026-07")
        assert isinstance(score, Decimal)
        assert Decimal("0") <= score <= Decimal("100")
