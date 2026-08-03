"""Dataset container and Importer protocol.

Dataset is the universal currency of the compute runtime. Every importer
returns a Dataset. Every downstream stage (validation, transform,
analytics) consumes a Dataset.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

import polars as pl


@dataclass
class Dataset:
    """Typed container for imported tabular data.

    This is an internal container that never crosses the API boundary
    directly. Polars DataFrames are non-trivial to serialize — Dataset
    uses @dataclass (not Pydantic) intentionally.

    Attributes:
        data: The Polars DataFrame with imported data.
        source: String identifier of the source ("csv", "excel", etc.).
        imported_at: Timestamp of import.
        hash: Content hash for cache key generation. Auto-computed if empty.
        metadata: Flexible metadata dict (path, file size, etc.).
    """

    data: pl.DataFrame
    source: str
    imported_at: datetime = field(default_factory=datetime.now)
    hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Auto-compute hash if not provided."""
        if not self.hash:
            self.hash = compute_dataset_hash(self.data)

    @property
    def row_count(self) -> int:
        """Number of rows in the dataset."""
        h = self.data.height
        assert isinstance(h, int)
        return h

    @property
    def column_names(self) -> list[str]:
        """Column names of the dataset."""
        c = self.data.columns
        assert isinstance(c, list)
        return c

    @property
    def schema(self) -> pl.Schema:
        """Polars schema of the dataset."""
        return self.data.schema


def compute_dataset_hash(df: pl.DataFrame) -> str:
    """Deterministic content hash of a DataFrame.

    Uses SHA-256 over the serialized Arrow IPC representation.

    Args:
        df: Polars DataFrame to hash.

    Returns:
        Hex digest string.
    """
    return hashlib.sha256(df.serialize()).hexdigest()


@runtime_checkable
class Importer(Protocol):
    """Protocol for all data importers.

    Mirrors the SpreadsheetProvider pattern in finance/integration/protocol.py.
    """

    source_type: str

    def import_data(self, source_uri: str, **kwargs: Any) -> Dataset:
        """Read data from source and return a typed Dataset.

        Args:
            source_uri: URI or path to the data source.
            **kwargs: Source-specific import options.

        Returns:
            Dataset containing the imported data.
        """
        ...
