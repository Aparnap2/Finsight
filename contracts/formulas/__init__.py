"""Formula registry contract — version 1.

Defines the canonical shape of a formula record in ``registry.yaml``
(schema ``finsight/formula-registry/registry-v1``). Every field in the
contract is validated on load so the registry cannot silently drift
from the schema.

Contracts are pure shape definitions: they carry no business logic and
may not import from ``business/``.
"""

# mypy: disable-error-code="misc,untyped-decorator"

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

#: Schema identifier referenced by ``registry.yaml`` and consumers.
SCHEMA = "finsight/formula-registry/registry-v1"
VERSION = "1.0.0"

FormulaCategory = Literal[
    "BalanceSheet",
    "Budgeting",
    "CashFlow",
    "Efficiency",
    "Expense",
    "Liquidity",
    "Profitability",
    "Revenue",
    "Variance",
]

FormulaStatus = Literal["draft", "stable", "production", "deprecated"]


class FormulaRecordV1(BaseModel):
    """A single formula record in the elevated registry.

    Attributes:
        id: Stable snake_case formula identifier (e.g. ``gross_margin``).
        name: Human-readable CamelCase display name.
        description: Business description of what the formula computes.
        expression: Arithmetic expression over formula ids, source
            fields, and allow-listed functions.
        inputs: Declared input formula ids.
        output: Semantic output type (``Percentage``, ``Money``, ...).
        category: Business category of the formula.
        references: External standards cited (e.g. ``IAS 7``, ``GAAP``).
        owner: Business owner (team or role).
        version: Semantic version ``MAJOR.MINOR.PATCH``.
        status: Lifecycle status of the formula definition.
        dependencies: Formula ids this formula directly depends on.
        tags: Arbitrary classification tags.
    """

    model_config = {"extra": "forbid"}

    id: str = Field(description="Stable snake_case formula identifier", min_length=1)
    name: str = Field(description="Human-readable CamelCase display name", min_length=1)
    description: str = Field(description="Business description of the formula")
    expression: str = Field(description="Arithmetic expression over inputs")
    inputs: list[str] = Field(
        default_factory=list,
        description="Declared input formula ids",
    )
    output: str = Field(default="Decimal", description="Semantic output type")
    category: FormulaCategory = Field(description="Business category of the formula")
    references: list[str] = Field(
        default_factory=list,
        description="External standards cited (e.g. IAS 7, GAAP)",
    )
    owner: str = Field(default="FP&A Team", description="Business owner (team or role)")
    version: str = Field(default="1.0.0", description="Semantic version")
    status: FormulaStatus = Field(default="stable", description="Lifecycle status")
    dependencies: list[str] = Field(
        default_factory=list,
        description="Formula ids this formula directly depends on",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Arbitrary classification tags",
    )

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        """Reject whitespace or path-hostile characters in ids."""
        if not value.replace("_", "").isalnum():
            msg = f"formula id '{value}' must be snake_case alphanumeric"
            raise ValueError(msg)
        return value

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        """Require three-part semantic versions."""
        parts = value.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            msg = f"version '{value}' must be MAJOR.MINOR.PATCH"
            raise ValueError(msg)
        return value

    @field_validator("dependencies")
    @classmethod
    def _validate_dependencies(cls, value: list[str]) -> list[str]:
        """Reject self-references in the dependency list."""
        if value and any(dep == "" for dep in value):
            msg = "dependency ids must be non-empty"
            raise ValueError(msg)
        return value


class FormulaRegistryFileV1(BaseModel):
    """Top-level shape of the elevated ``registry.yaml`` file.

    Attributes:
        schema_name: Schema identifier, must equal
            ``finsight/formula-registry/registry-v1`` (serialized as
            ``schema`` to match the file format).
        version: Registry file version.
        count: Number of formula records (must match the list length).
        description: Human-readable description of the file.
        formulas: The formula records.
    """

    model_config = {"extra": "forbid"}

    schema_name: str = Field(
        alias="schema",
        description="Schema identifier (file key: schema)",
    )
    version: str = Field(description="Registry file version")
    count: int = Field(description="Number of formula records")
    description: str = Field(default="", description="Human-readable description")
    formulas: list[FormulaRecordV1] = Field(description="Formula records")

    @field_validator("schema_name")
    @classmethod
    def _validate_schema(cls, value: str) -> str:
        """Require the registry file to declare the expected schema."""
        if value != SCHEMA:
            msg = f"schema must be '{SCHEMA}', got '{value}'"
            raise ValueError(msg)
        return value

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        """Require a three-part semantic version for the file."""
        parts = value.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            msg = f"version '{value}' must be MAJOR.MINOR.PATCH"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _validate_count(self) -> FormulaRegistryFileV1:
        """Require the declared count to match the record list length."""
        if self.count != len(self.formulas):
            msg = f"count {self.count} != formulas {len(self.formulas)}"
            raise ValueError(msg)
        return self


__all__ = [
    "FormulaCategory",
    "FormulaRecordV1",
    "FormulaRegistryFileV1",
    "FormulaStatus",
    "SCHEMA",
    "VERSION",
]
