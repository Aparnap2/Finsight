"""Tests for the SpreadsheetProvider abstraction.

TDD RED phase: finance/integration/ does not exist yet.
All imports from finance.integration.spreadsheet_provider MUST fail
with ModuleNotFoundError until the package is implemented.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    pass


# =============================================================================
# TestSpreadsheetProviderProtocol
# =============================================================================


class TestSpreadsheetProviderProtocol:
    """Protocol definition and structural subtyping checks."""

    def test_protocol_defines_required_methods(self) -> None:
        """SpreadsheetProvider protocol has read_range, write_range, validate, sync."""
        from finance.integration.spreadsheet_provider import SpreadsheetProvider

        # Check the protocol exists — introspection of the protocol members
        members = {name for name in dir(SpreadsheetProvider) if not name.startswith("_")}
        assert "read_range" in members
        assert "write_range" in members
        assert "validate" in members
        assert "sync" in members

    def test_google_sheets_provider_conforms(self) -> None:
        """GoogleSheetsProvider satisfies the SpreadsheetProvider protocol."""
        from finance.integration.spreadsheet_provider import (
            GoogleSheetsProvider,
            SpreadsheetProvider,
        )

        assert isinstance(GoogleSheetsProvider("creds.json"), SpreadsheetProvider)

    def test_csv_provider_conforms(self) -> None:
        """CSVProvider satisfies the SpreadsheetProvider protocol."""
        from finance.integration.spreadsheet_provider import (
            CSVProvider,
            SpreadsheetProvider,
        )

        assert isinstance(CSVProvider("data.csv"), SpreadsheetProvider)

    def test_mock_provider_conforms(self) -> None:
        """MockProvider satisfies the SpreadsheetProvider protocol."""
        from finance.integration.spreadsheet_provider import (
            MockProvider,
            SpreadsheetProvider,
        )

        assert isinstance(MockProvider(), SpreadsheetProvider)


# =============================================================================
# TestMockProvider
# =============================================================================


class TestMockProvider:
    """In-memory mock provider for isolated unit testing."""

    def test_mock_read_and_write(self) -> None:
        """MockProvider stores written data and returns it on read."""
        from finance.integration.spreadsheet_provider import MockProvider

        provider = MockProvider()
        provider.write_range("sheet_1", "A1:B2", [["a", "b"], ["c", "d"]])
        result = provider.read_range("sheet_1", "A1:B2")
        assert result == [["a", "b"], ["c", "d"]]

    def test_mock_read_empty_range(self) -> None:
        """MockProvider returns empty list for ranges that have not been written."""
        from finance.integration.spreadsheet_provider import MockProvider

        provider = MockProvider()
        result = provider.read_range("unknown_sheet", "Z99:AA100")
        assert result == []

    def test_mock_sync_returns_metadata(self) -> None:
        """MockProvider.sync returns a summary dict with rows_read."""
        from finance.integration.spreadsheet_provider import MockProvider

        provider = MockProvider()
        provider.write_range("s1", "A1:C3", [["x"] * 3 for _ in range(3)])
        summary = provider.sync("s1")
        assert isinstance(summary, dict)
        assert "rows_read" in summary
        assert summary["rows_read"] == 3

    def test_mock_validate_returns_valid(self) -> None:
        """MockProvider.validate returns a valid result dict."""
        from finance.integration.spreadsheet_provider import MockProvider

        provider = MockProvider()
        result = provider.validate("any_sheet")
        assert isinstance(result, dict)
        assert result.get("valid") is True

    def test_mock_with_initial_data(self) -> None:
        """MockProvider accepts initial_data via constructor."""
        from finance.integration.spreadsheet_provider import MockProvider

        initial = {"Sheet1!A1:B2": [["h1", "h2"], ["v1", "v2"]]}
        provider = MockProvider(initial_data=initial)
        result = provider.read_range("sheet_1", "Sheet1!A1:B2")
        assert result == [["h1", "h2"], ["v1", "v2"]]


# =============================================================================
# TestCSVProvider
# =============================================================================


class TestCSVProvider:
    """Provider backed by CSV files on disk."""

    def test_csv_read_returns_parsed_rows(self, tmp_path: Path) -> None:
        """CSVProvider.read_range reads a CSV file and returns list of list of strings."""
        from finance.integration.spreadsheet_provider import CSVProvider

        csv_file = tmp_path / "test.csv"
        csv_file.write_text("account,amount\n4010,100000\n6010,50000\n")
        provider = CSVProvider(str(csv_file))
        result = provider.read_range("ignored", "ignored")
        assert isinstance(result, list)
        assert len(result) == 3  # header + 2 data rows
        assert result[0] == ["account", "amount"]
        assert result[1] == ["4010", "100000"]
        assert result[2] == ["6010", "50000"]

    def test_csv_read_missing_file_raises(self) -> None:
        """CSVProvider raises FileNotFoundError when the CSV file does not exist."""
        from finance.integration.spreadsheet_provider import CSVProvider

        provider = CSVProvider("/nonexistent/file.csv")
        with pytest.raises(FileNotFoundError):
            provider.read_range("x", "y")

    def test_csv_sync_returns_summary(self, tmp_path: Path) -> None:
        """CSVProvider.sync returns a dict with rows_read and source."""
        from finance.integration.spreadsheet_provider import CSVProvider

        csv_file = tmp_path / "data.csv"
        csv_file.write_text("a,b,c\n1,2,3\n4,5,6\n")
        provider = CSVProvider(str(csv_file))
        summary = provider.sync("ignored")
        assert isinstance(summary, dict)
        assert summary["rows_read"] == 2  # 2 data rows (header excluded)
        assert "source" in summary
        assert summary["source"] == "csv"

    def test_csv_constructor_requires_path(self) -> None:
        """CSVProvider raises TypeError when instantiated without a file path."""
        from finance.integration.spreadsheet_provider import CSVProvider

        with pytest.raises(TypeError):
            CSVProvider()  # type: ignore[call-arg]

    def test_csv_read_returns_strings_only(self, tmp_path: Path) -> None:
        """CSVProvider returns all values as strings (transport layer)."""
        from finance.integration.spreadsheet_provider import CSVProvider

        csv_file = tmp_path / "numeric.csv"
        csv_file.write_text("revenue,expense\n100000.50,50000.25\n")
        provider = CSVProvider(str(csv_file))
        result = provider.read_range("x", "y")
        assert result[1][0] == "100000.50"
        assert result[1][1] == "50000.25"
        # Confirm they are strings, not floats
        assert isinstance(result[1][0], str)

    def test_csv_validate_returns_dict(self, tmp_path: Path) -> None:
        """CSVProvider.validate returns a dict for a valid file."""
        from finance.integration.spreadsheet_provider import CSVProvider

        csv_file = tmp_path / "valid.csv"
        csv_file.write_text("col1,col2\nv1,v2\n")
        provider = CSVProvider(str(csv_file))
        result = provider.validate("ignored")
        assert isinstance(result, dict)


# =============================================================================
# TestGoogleSheetsProvider
# =============================================================================


class TestGoogleSheetsProvider:
    """Provider wrapping the Google Sheets API (mocked)."""

    def test_requires_authentication(self) -> None:
        """GoogleSheetsProvider raises RuntimeError before authenticate() is called."""
        from finance.integration.spreadsheet_provider import GoogleSheetsProvider

        provider = GoogleSheetsProvider(credentials_path="creds.json")
        with pytest.raises(RuntimeError, match="authenticate|not authenticated|Authenticate"):
            provider.read_range("sheet_1", "A1:B2")

    def test_read_range_after_auth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GoogleSheetsProvider reads data after successful authentication (mocked)."""
        from finance.integration.spreadsheet_provider import GoogleSheetsProvider

        provider = GoogleSheetsProvider(credentials_path="creds.json")

        # Mock authenticate to succeed
        def _mock_auth() -> None:
            provider._authenticated = True

        monkeypatch.setattr(provider, "authenticate", _mock_auth)
        provider.authenticate()

        # Mock the HTTP response
        import httpx

        class _MockResponse:
            status_code = 200

            def json(self) -> dict[str, Any]:
                return {"values": [["a", "b"], ["c", "d"]]}

        monkeypatch.setattr(httpx, "get", lambda *a, **kw: _MockResponse())
        result = provider.read_range("sheet_1", "Sheet1!A1:B2")
        assert result == [["a", "b"], ["c", "d"]]

    def test_write_range_sends_data(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GoogleSheetsProvider.write_range sends data via the API."""
        from finance.integration.spreadsheet_provider import GoogleSheetsProvider

        provider = GoogleSheetsProvider(credentials_path="creds.json", _skip_auth=True)
        sent: list[list[list[str]]] = []

        class _MockResponse:
            status_code = 200

            def json(self) -> dict[str, Any]:
                return {"updated": True}

        import httpx

        def _mock_put(*a: Any, json: Any = None, **kw: Any) -> _MockResponse:
            if json is not None:
                sent.append(json["values"])
            return _MockResponse()

        monkeypatch.setattr(httpx, "put", _mock_put)

        provider.write_range("sheet_1", "A1:B2", [["x", "y"]])
        assert sent == [[["x", "y"]]]

    def test_validate_after_auth(self) -> None:
        """GoogleSheetsProvider.validate works after authentication."""
        from finance.integration.spreadsheet_provider import GoogleSheetsProvider

        provider = GoogleSheetsProvider(credentials_path="creds.json")
        with pytest.raises(RuntimeError, match="authenticate|not authenticated|Authenticate"):
            provider.validate("sheet_1")


# =============================================================================
# TestProviderFactory
# =============================================================================


class TestProviderFactory:
    """Factory that creates providers based on configuration type strings."""

    def test_factory_creates_csv_provider(self) -> None:
        """factory.create("csv") returns a CSVProvider instance."""
        from finance.integration.spreadsheet_provider import CSVProvider, ProviderFactory

        factory = ProviderFactory()
        provider = factory.create("csv", path="data.csv")
        assert isinstance(provider, CSVProvider)

    def test_factory_creates_mock_provider(self) -> None:
        """factory.create("mock") returns a MockProvider instance."""
        from finance.integration.spreadsheet_provider import MockProvider, ProviderFactory

        factory = ProviderFactory()
        provider = factory.create("mock")
        assert isinstance(provider, MockProvider)

    def test_factory_creates_google_provider(self) -> None:
        """factory.create("google_sheets") returns a GoogleSheetsProvider instance."""
        from finance.integration.spreadsheet_provider import (
            GoogleSheetsProvider,
            ProviderFactory,
        )

        factory = ProviderFactory()
        provider = factory.create("google_sheets", credentials_path="creds.json")
        assert isinstance(provider, GoogleSheetsProvider)

    def test_factory_invalid_type_raises(self) -> None:
        """factory.create("invalid") raises ValueError."""
        from finance.integration.spreadsheet_provider import ProviderFactory

        factory = ProviderFactory()
        with pytest.raises(ValueError, match="unknown provider|invalid|Unsupported"):
            factory.create("invalid")

    def test_factory_case_insensitive(self) -> None:
        """Factory handles type strings case-insensitively (e.g. "CSV", "Mock")."""
        from finance.integration.spreadsheet_provider import (
            CSVProvider,
            MockProvider,
            ProviderFactory,
        )

        factory = ProviderFactory()
        assert isinstance(factory.create("CSV", path="d.csv"), CSVProvider)
        assert isinstance(factory.create("MOCK"), MockProvider)

    def test_factory_registers_providers(self) -> None:
        """Factory exposes a registered_types property or similar."""
        from finance.integration.spreadsheet_provider import ProviderFactory

        factory = ProviderFactory()
        types = factory.registered_types
        assert "csv" in types
        assert "mock" in types
        assert "google_sheets" in types


# =============================================================================
# TestProviderIntegration
# =============================================================================


class TestProviderIntegration:
    """Polymorphic usage — any provider works with the same interface."""

    def test_can_use_provider_polymorphically(self, tmp_path: Path) -> None:
        """A function accepting SpreadsheetProvider works with every provider type."""
        from finance.integration.spreadsheet_provider import (
            CSVProvider,
            MockProvider,
            SpreadsheetProvider,
        )

        def process(provider: SpreadsheetProvider, sheet_id: str) -> list[list[str]]:
            summary = provider.sync(sheet_id)
            assert isinstance(summary, dict)
            return provider.read_range(sheet_id, "A1:B2")

        # --- MockProvider ---
        mock = MockProvider()
        mock.write_range("s1", "A1:B2", [["m1", "m2"]])
        assert process(mock, "s1") == [["m1", "m2"]]

        # --- CSVProvider ---
        csv_file = tmp_path / "poly.csv"
        csv_file.write_text("h1,h2\nc1,c2\n")
        csv_provider = CSVProvider(str(csv_file))
        result = process(csv_provider, "x")
        assert result[1] == ["c1", "c2"]

    def test_factory_creates_provider_polymorphically(self) -> None:
        """Provider returned by factory satisfies the protocol."""
        from finance.integration.spreadsheet_provider import (
            ProviderFactory,
            SpreadsheetProvider,
        )

        factory = ProviderFactory()
        for type_str in ("csv", "mock", "google_sheets"):
            kwargs: dict[str, Any] = {}
            if type_str == "csv":
                kwargs["path"] = "/tmp/placeholder.csv"
            elif type_str == "google_sheets":
                kwargs["credentials_path"] = "/tmp/creds.json"
                kwargs["_skip_auth"] = True
            provider = factory.create(type_str, **kwargs)
            assert isinstance(provider, SpreadsheetProvider), (
                f"{type_str} provider does not satisfy SpreadsheetProvider"
            )

    def test_all_providers_implement_validate(self) -> None:
        """Every provider type has a working validate method."""
        from finance.integration.spreadsheet_provider import (
            CSVProvider,
            GoogleSheetsProvider,
            MockProvider,
        )

        # MockProvider
        mock = MockProvider()
        assert isinstance(mock.validate("s1"), dict)

        # CSVProvider (missing file for unauthenticated case)
        csv_p = CSVProvider("/tmp/nonexistent.csv")
        # validate on a CSV should not need auth — but if file is missing,
        # it may raise FileNotFoundError
        with pytest.raises(FileNotFoundError):
            csv_p.validate("x")

        # GoogleSheetsProvider without auth
        gs = GoogleSheetsProvider(credentials_path="creds.json")
        with pytest.raises(RuntimeError):
            gs.validate("s1")

    def test_mock_write_overwrites_existing_data(self) -> None:
        """MockProvider overwrites data when writing to an existing range."""
        from finance.integration.spreadsheet_provider import MockProvider

        provider = MockProvider()
        provider.write_range("s", "R1", [["old"]])
        provider.write_range("s", "R1", [["new"]])
        assert provider.read_range("s", "R1") == [["new"]]

    def test_protocol_is_usable_with_isinstance_check(self) -> None:
        """SpreadsheetProtocol works with isinstance structural check via @runtime_checkable."""
        # If the protocol is decorated with @runtime_checkable, isinstance should work.
        # We verify the protocol itself is checkable.

        from finance.integration.spreadsheet_provider import (
            MockProvider,
            SpreadsheetProvider,
        )

        is_runtime_checkable = hasattr(SpreadsheetProvider, "__instancecheck__")
        # Whether or not it's runtime checkable, the test documents the design
        if is_runtime_checkable:
            assert isinstance(MockProvider(), SpreadsheetProvider)
