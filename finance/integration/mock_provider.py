"""In-memory mock spreadsheet provider for isolated unit testing."""

from __future__ import annotations

from typing import Any


class MockProvider:
    """In-memory provider that stores data in a dict keyed by range string.

    Parameters
    ----------
    initial_data : dict[str, list[list[str]]] | None
        Optional pre-populated data keyed by range string.
    """

    def __init__(
        self,
        initial_data: dict[str, list[list[str]]] | None = None,
    ) -> None:
        self._data: dict[str, list[list[str]]] = dict(initial_data or {})

    def read_range(self, spreadsheet_id: str, range_str: str) -> list[list[str]]:
        """Return data previously written to *range_str*, or an empty list."""
        return self._data.get(range_str, [])

    def write_range(
        self,
        spreadsheet_id: str,
        range_str: str,
        values: list[list[str]],
    ) -> None:
        """Store *values* keyed by *range_str* (overwrites any existing data)."""
        self._data[range_str] = values

    def validate(self, spreadsheet_id: str) -> dict[str, Any]:
        """Return a valid-result dict."""
        return {"valid": True}

    def sync(self, spreadsheet_id: str) -> dict[str, Any]:
        """Return a summary dict with the total rows stored."""
        total = sum(len(rows) for rows in self._data.values())
        return {"rows_read": total, "source": "mock"}
