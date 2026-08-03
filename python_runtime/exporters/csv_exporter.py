"""CSV exporter — serializes a DataFrame as CSV with header row."""

from __future__ import annotations

from uuid import UUID

import polars as pl

from python_runtime.exporters.protocol import Artifact


class CSVExporter:
    """Serializes a DataFrame as CSV with header row.

    Uses structural subtyping via the Exporter protocol.
    """

    format: str = "csv"
    content_type: str = "text/csv"

    def export(self, data: pl.DataFrame, job_id: UUID) -> Artifact:
        """Serialize the DataFrame as CSV and return an Artifact.

        Args:
            data: Polars DataFrame to serialize.
            job_id: UUID of the originating job.

        Returns:
            Artifact with CSV payload.
        """
        payload = data.write_csv()
        return Artifact(
            job_id=job_id,
            format=self.format,
            content_type=self.content_type,
            size_bytes=len(payload.encode("utf-8")),
            payload=payload,
        )
