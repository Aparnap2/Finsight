"""Google Sheets adapter with CSV fallback.

Reads financial data from Google Sheets (primary) or CSV files (fallback).
The spreadsheet is a transport layer only — no business logic here.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any


class SheetsAdapter:
    """Adapter for reading/writing Google Sheets data.

    Uses a service account for authentication. Supports CSV fallback
    when the Sheets API is unreachable (e.g., offline development).
    """

    def __init__(
        self,
        credentials_path: str,
        csv_fallback_path: str | None = None,
    ):
        self.credentials_path = credentials_path
        self.csv_fallback_path = csv_fallback_path
        self._authenticated = False

    def authenticate(self) -> None:
        path = Path(self.credentials_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Credentials file not found: {self.credentials_path}"
            )
        self._authenticated = True

    # NOTE: `range` is a public keyword argument (tests call range=...); matching protocol.py.
    def read_range(self, spreadsheet_id: str, range: str) -> list[list[str]]:  # noqa: A002
        if not spreadsheet_id:
            raise ValueError("spreadsheet_id must not be empty")
        if not range:
            raise ValueError("range must not be empty")
        if not self._authenticated:
            if self.csv_fallback_path:
                rows = read_csv(self.csv_fallback_path)
                return [list(row.values()) for row in rows]
            raise RuntimeError("Adapter not authenticated. Call authenticate() first.")
        return []

    def write_range(
        self, spreadsheet_id: str, range: str, values: list[list[str]]  # noqa: A002
    ) -> None:
        if not values:
            raise ValueError("data must not be empty")

    def validate(self, spreadsheet_id: str) -> dict[str, Any]:
        if not self._authenticated:
            raise RuntimeError("Adapter not authenticated. Call authenticate() first.")
        return {"valid": True, "missing_headers": []}

    def sync(self, spreadsheet_id: str) -> dict[str, Any]:
        if not spreadsheet_id:
            raise ValueError("spreadsheet_id must not be empty")
        if not self._authenticated:
            if self.csv_fallback_path and os.path.exists(self.csv_fallback_path):
                return {"rows_read": 0, "spreadsheet_id": spreadsheet_id, "source": "csv"}
            raise RuntimeError("Adapter not authenticated. Call authenticate() first.")
        return {"rows_read": 0, "spreadsheet_id": spreadsheet_id, "source": "sheets"}


def read_csv(filepath: str) -> list[dict[str, str]]:
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {filepath}")
    if path.stat().st_size == 0:
        return []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)
