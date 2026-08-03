"""Tests for python_runtime.importers.factory — ImporterFactory."""

import pytest

from python_runtime.importers.csv_importer import CSVImporter
from python_runtime.importers.factory import ImporterFactory
from python_runtime.importers.protocol import Dataset, Importer


class TestImporterFactory:
    """Factory for creating Importers by source type string."""

    def test_create_csv_importer(self) -> None:
        importer = ImporterFactory.create("csv")
        assert isinstance(importer, CSVImporter)
        assert isinstance(importer, Importer)

    def test_create_returns_new_instance(self) -> None:
        i1 = ImporterFactory.create("csv")
        i2 = ImporterFactory.create("csv")
        assert i1 is not i2  # fresh instance each call

    def test_unknown_type_raises_key_error(self) -> None:
        with pytest.raises(KeyError, match="No importer registered"):
            ImporterFactory.create("excel")

    def test_list_sources_includes_csv(self) -> None:
        sources = ImporterFactory.list_sources()
        assert "csv" in sources

    def test_register_new_importer(self) -> None:
        """Register a custom importer dynamically."""

        class MockImporter:
            source_type: str = "mock"

            def import_data(self, source_uri: str, **kwargs) -> Dataset:  # type: ignore[empty-body]
                ...

        # Must be registered as type[Importer]
        ImporterFactory.register("mock", MockImporter)  # type: ignore[arg-type]
        try:
            assert "mock" in ImporterFactory.list_sources()
            importer = ImporterFactory.create("mock")
            assert isinstance(importer, MockImporter)
        finally:
            # Clean up — remove from registry
            ImporterFactory._IMPORTERS.pop("mock", None)

    def test_register_overwrites_existing(self) -> None:
        """Registering same source_type twice overwrites."""

        class NewCSV:
            source_type: str = "csv"

            def import_data(self, source_uri: str, **kwargs) -> Dataset:  # type: ignore[empty-body]
                ...

        ImporterFactory.register("csv", NewCSV)  # type: ignore[arg-type]
        importer = ImporterFactory.create("csv")
        assert isinstance(importer, NewCSV)
        # Restore original
        ImporterFactory.register("csv", CSVImporter)
