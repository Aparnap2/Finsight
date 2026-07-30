"""Pydantic models for the Semantic Data Dictionary.

The data dictionary provides field-level business metadata for every
column in the FinSight data model, bridging database schemas and
business meaning.
"""

from __future__ import annotations

from collections.abc import Iterator

from pydantic import BaseModel, Field

from business.glossary.models import DataClassification, GlossaryRegistry

# ---------------------------------------------------------------------------
# Column metadata
# ---------------------------------------------------------------------------


class ColumnMetadata(BaseModel):  # type: ignore[misc]  # pydantic v2 w/o mypy plugin
    """Business metadata for a single database column.

    Each column entry captures the business-facing definition, data type,
    sensitivity classification, validation rules, and optional link to a
    glossary term.
    """

    column_name: str = Field(description="Physical column name in the database")
    table_name: str = Field(description="Physical table name")
    business_name: str = Field(description="Business-facing column name")
    definition: str = Field(description="1-2 sentence business definition of the column")
    canonical_type: str = Field(
        description="Canonical semantic type (Money, Percentage, FiscalPeriod, etc.)",
    )
    unit: str | None = Field(
        default=None,
        description="Unit of measurement (entity_currency, percentage, count, etc.)",
    )
    classification: DataClassification = Field(
        description="Data sensitivity classification",
    )
    sox_relevant: bool = Field(
        default=False,
        description="Whether this column is subject to SOX controls",
    )
    pii: bool = Field(
        default=False,
        description="Whether this column contains personally identifiable information",
    )
    source_system: str = Field(
        description="Source system of the data in this column",
    )
    example: str | None = Field(
        default=None,
        description="Example value for documentation and testing",
    )
    validation_rules: list[str] = Field(
        default_factory=list,
        description="Business validation rules for this column",
    )
    is_nullable: bool = Field(
        default=False,
        description="Whether this column allows NULL values",
    )
    default_value: str | None = Field(
        default=None,
        description="Default value for the column, if any",
    )
    glossary_ref: str | None = Field(
        default=None,
        description="Reference to a GlossaryEntry.term_id for the business concept",
    )


# ---------------------------------------------------------------------------
# Table metadata
# ---------------------------------------------------------------------------


class TableMetadata(BaseModel):  # type: ignore[misc]  # pydantic v2 w/o mypy plugin
    """Business metadata for a database table.

    Describes the table's business purpose, its columns, key structure,
    ownership, and overall data classification.
    """

    table_name: str = Field(description="Physical database table name")
    business_name: str = Field(description="Business-facing table name")
    definition: str = Field(description="Business definition of the table")
    columns: list[ColumnMetadata] = Field(
        description="All columns in the table with their metadata",
    )
    primary_keys: list[str] = Field(
        description="Column names that form the primary key",
    )
    foreign_keys: list[dict[str, str]] = Field(
        default_factory=list,
        description="Foreign key relationships as {column: referenced_table.column}",
    )
    owner: str = Field(description="Business owner of this table")
    classification: DataClassification = Field(
        description="Default data classification for the table",
    )

    def get_column(self, column_name: str) -> ColumnMetadata | None:
        """Look up a column by its physical name.

        Args:
            column_name: The physical column name.

        Returns:
            The column metadata, or None if not found.
        """
        for col in self.columns:
            if col.column_name == column_name:
                return col
        return None

    def sox_relevant_columns(self) -> list[ColumnMetadata]:
        """Return all columns flagged as SOX-relevant.

        Returns:
            List of SOX-relevant column metadata entries.
        """
        return [col for col in self.columns if col.sox_relevant]

    def pii_columns(self) -> list[ColumnMetadata]:
        """Return all columns flagged as containing PII.

        Returns:
            List of PII-containing column metadata entries.
        """
        return [col for col in self.columns if col.pii]


# ---------------------------------------------------------------------------
# Data dictionary registry
# ---------------------------------------------------------------------------


class DataDictionary:
    """Registry of all table and column metadata in the FinSight data model.

    Provides lookup, search, and classification-aware filtering over
    the full set of database tables.
    """

    def __init__(self) -> None:
        self._tables: dict[str, TableMetadata] = {}

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def register(self, table: TableMetadata) -> None:
        """Register a table definition.

        Args:
            table: The table metadata to register.

        Raises:
            ValueError: If the table is already registered.
        """
        if table.table_name in self._tables:
            msg = f"Table '{table.table_name}' is already registered"
            raise ValueError(msg)
        self._tables[table.table_name] = table

    def register_many(self, tables: list[TableMetadata]) -> None:
        """Register multiple tables in bulk.

        Args:
            tables: List of table metadata to register.
        """
        for table in tables:
            self.register(table)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get_table(self, table_name: str) -> TableMetadata | None:
        """Get metadata for a table by its physical name.

        Args:
            table_name: The physical table name.

        Returns:
            The table metadata, or None if not found.
        """
        return self._tables.get(table_name)

    def get_column(self, table_name: str, column_name: str) -> ColumnMetadata | None:
        """Get metadata for a specific column.

        Args:
            table_name: The physical table name.
            column_name: The physical column name.

        Returns:
            The column metadata, or None if not found.
        """
        table = self.get_table(table_name)
        if table is None:
            return None
        return table.get_column(column_name)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def search(self, query: str) -> list[ColumnMetadata]:
        """Search across all tables for columns matching the query.

        Searches column business name, physical name, and definition.

        Args:
            query: Free-text search string.

        Returns:
            Matching column metadata entries.
        """
        q = query.lower().strip()
        if not q:
            return []

        results: list[ColumnMetadata] = []
        seen: set[tuple[str, str]] = set()

        for table in self._tables.values():
            for col in table.columns:
                key = (col.table_name, col.column_name)
                if key in seen:
                    continue
                if (
                    q in col.business_name.lower()
                    or q in col.column_name.lower()
                    or q in col.definition.lower()
                ):
                    results.append(col)
                    seen.add(key)

        return results

    def tables_by_classification(
        self,
        classification: DataClassification,
    ) -> list[TableMetadata]:
        """List all tables with a given data classification.

        Args:
            classification: The sensitivity level to filter by.

        Returns:
            Matching tables, sorted by name.
        """
        return sorted(
            (t for t in self._tables.values() if t.classification == classification),
            key=lambda t: t.table_name,
        )

    def columns_by_classification(
        self,
        classification: DataClassification,
    ) -> list[ColumnMetadata]:
        """List all columns with a given data classification.

        Args:
            classification: The sensitivity level to filter by.

        Returns:
            Matching columns, sorted by table and column name.
        """
        results: list[ColumnMetadata] = []
        for table in self._tables.values():
            for col in table.columns:
                if col.classification == classification:
                    results.append(col)
        return sorted(results, key=lambda c: (c.table_name, c.column_name))

    def sox_relevant_fields(self) -> list[ColumnMetadata]:
        """List all columns flagged as SOX-relevant across all tables.

        Returns:
            SOX-relevant columns, sorted by table and column name.
        """
        results: list[ColumnMetadata] = []
        for table in self._tables.values():
            results.extend(table.sox_relevant_columns())
        return sorted(results, key=lambda c: (c.table_name, c.column_name))

    def pii_fields(self) -> list[ColumnMetadata]:
        """List all columns flagged as containing PII across all tables.

        Returns:
            PII-containing columns, sorted by table and column name.
        """
        results: list[ColumnMetadata] = []
        for table in self._tables.values():
            results.extend(table.pii_columns())
        return sorted(results, key=lambda c: (c.table_name, c.column_name))

    def __len__(self) -> int:
        return len(self._tables)

    def __contains__(self, table_name: str) -> bool:
        return table_name in self._tables

    def __iter__(self) -> Iterator[TableMetadata]:
        return iter(self._tables.values())

    def link_glossary(
        self,
        glossary: GlossaryRegistry,
    ) -> int:
        """Cross-reference glossary_ref fields against a glossary registry.

        Walks all columns and verifies that each glossary_ref value
        corresponds to a registered glossary term.

        Args:
            glossary: The glossary registry to validate against.

        Returns:
            Number of broken references (0 = all clean).
        """
        broken = 0
        for table in self._tables.values():
            for col in table.columns:
                if col.glossary_ref is not None and glossary.lookup(col.glossary_ref) is None:
                        broken += 1
        return broken
