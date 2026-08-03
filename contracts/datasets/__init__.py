"""Dataset contract — version 1.

Defines the canonical shape of a dataset registry entry: a named,
versioned data product with schema, lineage, and sensitivity
metadata. Registry entries reference this contract instead of
inlining field definitions.

Contracts are pure shape definitions: they carry no business logic and
may not import from ``business/``.
"""

# mypy: disable-error-code="misc,untyped-decorator"

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

#: Schema identifier referenced by dataset registries.
SCHEMA = "finsight/dataset-registry/dataset-v1"
VERSION = "1.0.0"

DatasetSensitivity = Literal["public", "internal", "confidential", "restricted"]


class DatasetContractV1(BaseModel):
    """A single dataset in the platform.

    Attributes:
        dataset_id: Stable identifier (e.g. ``finance.actuals``).
        name: Human-readable name.
        description: What the dataset contains and is used for.
        version: Semantic version ``MAJOR.MINOR.PATCH``.
        table: Physical table or logical source name.
        schema_ref: Reference to the canonical schema definition.
        owner: Business owner (team or role).
        sensitivity: Data sensitivity classification.
        source_system: Origin system (ERP, CRM, ...).
        lineage: Upstream sources this dataset is derived from.
        updated_at: Last modification timestamp (ISO 8601).
    """

    model_config = {"extra": "forbid"}

    dataset_id: str = Field(description="Stable dataset identifier", min_length=1)
    name: str = Field(description="Human-readable name", min_length=1)
    description: str = Field(description="What the dataset contains and is used for")
    version: str = Field(default="1.0.0", description="Semantic version")
    table: str = Field(description="Physical table or logical source name")
    schema_ref: str = Field(description="Reference to the canonical schema definition")
    owner: str = Field(default="FP&A Team", description="Business owner (team or role)")
    sensitivity: DatasetSensitivity = Field(
        default="internal",
        description="Data sensitivity classification",
    )
    source_system: str = Field(default="ERP", description="Origin system")
    lineage: list[str] = Field(
        default_factory=list,
        description="Upstream sources this dataset is derived from",
    )
    updated_at: str = Field(description="Last modification timestamp (ISO 8601)")

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        """Require three-part semantic versions."""
        parts = value.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            msg = f"version '{value}' must be MAJOR.MINOR.PATCH"
            raise ValueError(msg)
        return value

    @field_validator("dataset_id")
    @classmethod
    def _validate_dataset_id(cls, value: str) -> str:
        """Reject whitespace or path-hostile characters in dataset ids."""
        if any(ch.isspace() for ch in value):
            msg = f"dataset id '{value}' must not contain whitespace"
            raise ValueError(msg)
        return value


__all__ = ["DatasetContractV1", "DatasetSensitivity", "SCHEMA", "VERSION"]
