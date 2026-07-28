"""Spreadsheet provider backed by CSV files on disk."""

from __future__ import annotations

import csv
from typing import Any


class CSVProvider:
    """Read-only provider backed by a local CSV file.

    Parameters
    ----------
    path : str
        Filesystem path to the CSV file to read.
    """

    def __init__(self, path: str) -> None:
        self._path = path

    def _read_rows(self) -> list[list[str]]:
        """Open the CSV file and return every row as a list of strings."""
        with open(self._path, newline="") as f:
            reader = csv.reader(f)
            return [row for row in reader]

    def read_range(self, spreadsheet_id: str, range_str: str) -> list[list[str]]:
        """Return the full contents of the CSV file.

        *spreadsheet_id* and *range_str* are ignored — the entire file is
        returned every call.
        """
        return self._read_rows()

    def write_range(
        self,
        spreadsheet_id: str,
        range_str: str,
        values: list[list[str]],
    ) -> None:
        """Not supported — raises ``NotImplementedError``."""
        raise NotImplementedError("CSVProvider does not support write_range")

    def validate(self, spreadsheet_id: str) -> dict[str, Any]:
        """Validate the CSV file is readable.

        Raises ``FileNotFoundError`` if the file does not exist.
        """
        self._read_rows()  # will raise FileNotFoundError if missing
        return {"valid": True}

    def sync(self, spreadsheet_id: str) -> dict[str, Any]:
        """Return a summary dict with data-row count and source label.

        The header row is excluded from *rows_read*.
        """
        rows = self._read_rows()
        data_rows = max(0, len(rows) - 1)  # exclude header
        return {"rows_read": data_rows, "source": "csv"}
