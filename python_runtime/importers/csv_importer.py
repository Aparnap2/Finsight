"""CSV importer — reads CSV files as Datasets."""

from __future__ import annotations

import logging
from pathlib import Path

import polars as pl

from python_runtime.importers.protocol import Dataset

logger = logging.getLogger(__name__)


class CSVImporter:
    """Imports CSV files as Datasets.

    Uses structural subtyping via the Importer protocol (not explicit
    subclassing). Matches the SpreadsheetProvider pattern.
    """

    source_type: str = "csv"

    def import_data(
        self,
        source_uri: str,
        *,
        has_header: bool = True,
        infer_schema_length: int = 100,
        **kwargs: str,
    ) -> Dataset:
        """Read a CSV file and return a typed Dataset.

        Args:
            source_uri: Path to the CSV file.
            has_header: Whether the CSV has a header row.
            infer_schema_length: Number of rows to scan for schema inference.
            **kwargs: Additional polars.read_csv arguments.

        Returns:
            Dataset containing the CSV data.

        Raises:
            FileNotFoundError: If the CSV file does not exist.
            pl.exceptions.ComputeError: If the CSV is malformed.
        """
        path = Path(source_uri)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {source_uri}")

        df = pl.read_csv(
            source_uri,
            has_header=has_header,
            infer_schema_length=infer_schema_length,
            **kwargs,
        )
        logger.info(
            "Imported CSV: %s (%d rows, %d columns)",
            source_uri,
            df.height,
            df.width,
        )
        return Dataset(
            data=df,
            source="csv",
            metadata={
                "path": str(path.absolute()),
                "file_size_bytes": path.stat().st_size,
            },
        )
