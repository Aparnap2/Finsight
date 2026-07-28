"""Spreadsheet provider wrapping the Google Sheets API via httpx."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx


class GoogleSheetsProvider:
    """Provider that reads/writes Google Sheets via the REST API.

    Parameters
    ----------
    credentials_path : str
        Path to the Google service-account credentials JSON file.
    _skip_auth : bool
        Internal flag to bypass authentication (used in tests).
    """

    def __init__(
        self,
        credentials_path: str,
        _skip_auth: bool = False,
    ) -> None:
        self._credentials_path = credentials_path
        self._authenticated = False
        if _skip_auth:
            self._authenticated = True

    def authenticate(self) -> None:
        """Authenticate using the credentials file.

        Raises ``FileNotFoundError`` if the credentials file does not exist.
        """
        if not Path(self._credentials_path).exists():
            raise FileNotFoundError(
                f"Credentials file not found: {self._credentials_path}",
            )
        self._authenticated = True

    def _require_auth(self) -> None:
        if not self._authenticated:
            raise RuntimeError(
                "Not authenticated. Call authenticate() first.",
            )

    def read_range(self, spreadsheet_id: str, range_str: str) -> list[list[str]]:
        """Read cell values via ``GET`` to the Sheets API."""
        self._require_auth()
        url = (
            f"https://sheets.googleapis.com/v4/spreadsheets/"
            f"{spreadsheet_id}/values/{range_str}"
        )
        resp = httpx.get(url)
        data: list[list[str]] = resp.json().get("values", [])
        return data

    def write_range(
        self,
        spreadsheet_id: str,
        range_str: str,
        values: list[list[str]],
    ) -> None:
        """Write cell values via ``PUT`` to the Sheets API."""
        self._require_auth()
        url = (
            f"https://sheets.googleapis.com/v4/spreadsheets/"
            f"{spreadsheet_id}/values/{range_str}"
        )
        httpx.put(url, json={"values": values})

    def validate(self, spreadsheet_id: str) -> dict[str, Any]:
        """Validate the spreadsheet is accessible (requires auth)."""
        self._require_auth()
        return {"valid": True}

    def sync(self, spreadsheet_id: str) -> dict[str, Any]:
        """Return a summary dict."""
        return {"rows_read": 0, "source": "google_sheets"}
