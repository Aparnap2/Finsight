"""JSON exporter for BoardReport.

Serialises a ``BoardReport`` to a JSON string using Pydantic's
``model_dump(mode="json")`` which automatically handles ``Decimal``
and ``datetime`` serialisation.
"""

from __future__ import annotations

import json
import re

from finance.domain.board_report import BoardReport


class JSONExporter:
    """Exports a ``BoardReport`` as a JSON string.

    Parameters
    ----------
    indent : int
        Number of spaces for JSON indentation (default ``2``).
    """

    def __init__(self, indent: int = 2) -> None:
        self.indent = indent

    def export(self, report: BoardReport) -> str:
        """Serialise *report* to a pretty-printed JSON string.

        Uses ``report.model_dump(mode="json")`` so that ``Decimal``
        values are converted to floats and ``datetime`` objects are
        converted to ISO-8601 strings.
        """
        json_str = json.dumps(
            report.model_dump(mode="json"),
            indent=self.indent,
        )
        # Pydantic serialises UTC-aware datetimes with 'Z' suffix;
        # replace with '+00:00' to match consumer expectations.
        json_str = re.sub(
            r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z',
            r'\1+00:00',
            json_str,
        )
        return json_str
