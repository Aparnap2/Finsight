"""JSON exporter — serializes a DataFrame as a JSON array of objects."""

from __future__ import annotations

from uuid import UUID

import polars as pl

from python_runtime.exporters.protocol import Artifact


class JSONExporter:
    """Serializes a DataFrame as a JSON array of objects.

    Uses structural subtyping via the Exporter protocol.
    """

    format: str = "json"
    content_type: str = "application/json"

    def export(self, data: pl.DataFrame, job_id: UUID) -> Artifact:
        """Serialize the DataFrame as JSON and return an Artifact.

        Args:
            data: Polars DataFrame to serialize.
            job_id: UUID of the originating job.

        Returns:
            Artifact with JSON payload.
        """
        payload = data.write_json()
        return Artifact(
            job_id=job_id,
            format=self.format,
            content_type=self.content_type,
            size_bytes=len(payload.encode("utf-8")),
            payload=payload,
        )
