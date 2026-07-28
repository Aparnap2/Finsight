"""SpreadsheetProvider protocol definition.

Defines the structural contract for all spreadsheet provider implementations.
"""

from __future__ import annotations

import typing
from typing import Any


@typing.runtime_checkable
class SpreadsheetProvider(typing.Protocol):
    """Protocol that all spreadsheet providers must satisfy.

    Methods
    -------
    read_range(spreadsheet_id, range)
        Return cell values as a list of rows (list of list of str).
    write_range(spreadsheet_id, range, values)
        Write cell values to the given range.
    validate(spreadsheet_id)
        Validate that the spreadsheet is accessible and returns a dict.
    sync(spreadsheet_id)
        Synchronise metadata and return a summary dict.
    """

    def read_range(self, spreadsheet_id: str, range: str) -> list[list[str]]:  # noqa: A002
        """Read a range of cells from the spreadsheet."""

    def write_range(
        self,
        spreadsheet_id: str,
        range: str,  # noqa: A002
        values: list[list[str]],
    ) -> None:
        """Write values to a range of cells in the spreadsheet."""

    def validate(self, spreadsheet_id: str) -> dict[str, Any]:
        """Validate that the spreadsheet is accessible."""

    def sync(self, spreadsheet_id: str) -> dict[str, Any]:
        """Synchronise metadata from the spreadsheet."""
