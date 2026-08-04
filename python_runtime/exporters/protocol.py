"""Artifact model and Exporter protocol for serializing compute results.

Artifact is a Pydantic model that crosses API boundaries. The Exporter
protocol defines how Datasets are serialized into Artifacts.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    import polars as pl


class Artifact(BaseModel):
    """A stored export artifact — the result of a compute job.

    Attributes:
        id: Unique artifact identifier.
        job_id: Job that produced this artifact.
        format: Serialization format ("json", "csv").
        size_bytes: Size of the payload in bytes.
        created_at: Timestamp of creation.
        storage_path: Optional local filesystem path.
        content_type: MIME type of the payload.
        payload: Inline content for small artifacts.
    """

    id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    format: str
    size_bytes: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    storage_path: str | None = None
    content_type: str = "application/octet-stream"
    payload: str | None = None


@runtime_checkable
class Exporter(Protocol):
    """Protocol for serializing a DataFrame into an Artifact."""

    format: str
    content_type: str

    def export(
        self,
        data: pl.DataFrame,
        job_id: UUID,
    ) -> Artifact:
        """Serialize the DataFrame and return an Artifact.

        Args:
            data: Polars DataFrame to export.
            job_id: UUID of the originating job.

        Returns:
            Artifact with serialized payload.
        """
        ...
