"""Factory for creating Importers by source type string.

Mirrors the ProviderFactory pattern in finance/integration/factory.py.
"""

from __future__ import annotations

from python_runtime.importers.csv_importer import CSVImporter
from python_runtime.importers.protocol import Importer


class ImporterFactory:
    """Factory for creating Importers by source type string.

    Usage:
        importer = ImporterFactory.create("csv")
        sources = ImporterFactory.list_sources()
    """

    _IMPORTERS: dict[str, type[Importer]] = {}

    @classmethod
    def register(cls, source_type: str, importer_cls: type[Importer]) -> None:
        """Register an importer class for a source type.

        Args:
            source_type: String key (e.g. "csv", "excel").
            importer_cls: Class implementing the Importer protocol.
        """
        cls._IMPORTERS[source_type] = importer_cls

    @classmethod
    def create(cls, source_type: str) -> Importer:
        """Create a new importer instance for the given source type.

        Args:
            source_type: String key for the importer type.

        Returns:
            A fresh Importer instance.

        Raises:
            KeyError: If no importer is registered for source_type.
        """
        if source_type not in cls._IMPORTERS:
            raise KeyError(
                f"No importer registered for source type: '{source_type}'. "
                f"Registered: {list(cls._IMPORTERS)}"
            )
        return cls._IMPORTERS[source_type]()

    @classmethod
    def list_sources(cls) -> list[str]:
        """Return list of registered source types."""
        return list(cls._IMPORTERS.keys())


# Register built-in importers on module load
ImporterFactory.register("csv", CSVImporter)
