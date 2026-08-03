"""Pydantic models for the Business Glossary registry.

This module defines the data structures for representing financial terms
in the FinSight Business Knowledge Layer (Layer 0). It has zero internal
dependencies beyond the standard library and Pydantic.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Data classification
# ---------------------------------------------------------------------------

DataClassification = Literal["public", "internal", "confidential", "restricted"]
"""Sensitivity levels for financial data per the BKL data classification matrix.

- public:       No harm if disclosed (product names, public reports)
- internal:     Harmless but not public (department names, fiscal calendars)
- confidential: Harm if disclosed broadly (actuals, budgets, headcount)
- restricted:   Significant harm if disclosed — PII, bank accounts, compensation
"""

# ---------------------------------------------------------------------------
# Category enum
# ---------------------------------------------------------------------------


class GlossaryCategory(StrEnum):
    """High-level groupings for financial glossary terms."""

    REVENUE = "revenue"
    EXPENSE = "expense"
    PROFITABILITY = "profitability"
    BALANCE_SHEET = "balance_sheet"
    CASH_FLOW = "cash_flow"
    BUDGETING = "budgeting"
    VARIANCE = "variance"
    FORECASTING = "forecasting"


# ---------------------------------------------------------------------------
# Glossary entry model
# ---------------------------------------------------------------------------


class GlossaryEntry(BaseModel):  # type: ignore[misc]  # pydantic v2 w/o mypy plugin
    """A single term in the Business Glossary.

    Each entry captures the canonical definition, formula, data classification,
    ownership, and metadata for one financial concept. Entries are identified
    by a stable dotted-term_id (e.g. ``glossary.revenue.net``) and may have
    multiple aliases for lookup resolution.
    """

    term_id: str = Field(
        description="Stable dotted identifier (e.g. glossary.revenue.net)",
        pattern=r"^glossary\.[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$",
    )
    term: str = Field(description="Canonical human-readable name")
    aliases: list[str] = Field(
        default_factory=list,
        description="Alternative names used in source systems or reports",
    )
    definition: str = Field(description="1-2 sentence business definition")
    category: GlossaryCategory = Field(description="High-level grouping category")
    formula: str | None = Field(
        default=None,
        description="Canonical formula expressed in business terms",
    )
    data_type: str = Field(
        description="Canonical value type (Money, Percentage, Ratio, Count, etc.)",
    )
    source_system: str = Field(
        description="Typical source system (ERP, CRM, billing, computed)",
    )
    classification: DataClassification = Field(
        description="Data sensitivity classification for access control",
    )
    sox_relevant: bool = Field(
        default=False,
        description="Whether this field is subject to Sarbanes-Oxley controls",
    )
    pii: bool = Field(
        default=False,
        description="Whether this term contains personally identifiable information",
    )
    owner: str = Field(description="Business owner (team or individual)")
    steward: str = Field(description="Data steward responsible for quality")
    tags: list[str] = Field(
        default_factory=list,
        description="Arbitrary categorization tags (gaap, saas, kpi, etc.)",
    )
    version: str = Field(
        default="1.0.0",
        description="Semantic version of this glossary entry",
    )
    valid_from: date = Field(
        description="Date this entry version became active",
    )
    url: str | None = Field(
        default=None,
        description="Link to external reference documentation or policy",
    )

    def model_post_init(self, __context: object) -> None:
        """Validate that aliases don't duplicate the primary term."""
        normalized_aliases = {a.lower().strip() for a in self.aliases}
        if self.term.lower().strip() in normalized_aliases:
            msg = (
                f"Alias list for '{self.term_id}' contains the primary "
                f"term '{self.term}'"
            )
            raise ValueError(msg)


# ---------------------------------------------------------------------------
# Glossary registry
# ---------------------------------------------------------------------------


class GlossaryRegistry:
    """In-memory registry of all Business Glossary entries.

    Provides lookup, search, and filter operations over registered terms.
    The registry is populated at startup from the canonical term definitions
    in :mod:`business.glossary.registry`.
    """

    def __init__(self) -> None:
        self._entries: dict[str, GlossaryEntry] = {}
        self._alias_map: dict[str, str] = {}  # lowercase alias → term_id

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def register(self, entry: GlossaryEntry) -> None:
        """Register a single glossary entry.

        Args:
            entry: The glossary entry to register.

        Raises:
            ValueError: If the term_id or an alias is already registered.
        """
        if entry.term_id in self._entries:
            msg = f"Glossary entry '{entry.term_id}' is already registered"
            raise ValueError(msg)

        for alias in entry.aliases:
            key = alias.lower().strip()
            if key in self._alias_map:
                msg = (
                    f"Alias '{alias}' for '{entry.term_id}' conflicts with "
                    f"existing entry '{self._alias_map[key]}'"
                )
                raise ValueError(msg)

        self._entries[entry.term_id] = entry
        for alias in entry.aliases:
            self._alias_map[alias.lower().strip()] = entry.term_id

    def register_many(self, entries: list[GlossaryEntry]) -> None:
        """Register multiple glossary entries in bulk.

        Args:
            entries: Iterable of glossary entries to register.
        """
        for entry in entries:
            self.register(entry)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def lookup(self, term_id: str) -> GlossaryEntry | None:
        """Retrieve an entry by its stable term_id.

        Args:
            term_id: The dotted identifier (e.g. ``glossary.revenue.net``).

        Returns:
            The matching entry, or None if not found.
        """
        return self._entries.get(term_id)

    def resolve_alias(self, alias: str) -> GlossaryEntry | None:
        """Resolve a term alias to its canonical glossary entry.

        Args:
            alias: An alias or alternative name for a term.

        Returns:
            The canonical entry, or None if the alias is unknown.
        """
        term_id = self._alias_map.get(alias.lower().strip())
        if term_id is None:
            return None
        return self._entries.get(term_id)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def search(self, query: str) -> list[GlossaryEntry]:
        """Search entries by term name, aliases, or definition (case-insensitive).

        Args:
            query: Free-text search string.

        Returns:
            Matching entries ordered by relevance (exact term match first).
        """
        q = query.lower().strip()
        if not q:
            return list(self._entries.values())

        results: list[tuple[GlossaryEntry, int]] = []

        for entry in self._entries.values():
            score = 0
            if q == entry.term.lower():
                score = 100
            elif entry.term.lower().startswith(q):
                score = 80
            elif any(q == a.lower() for a in entry.aliases):
                score = 70
            elif any(a.lower().startswith(q) for a in entry.aliases):
                score = 50
            elif q in entry.definition.lower():
                score = 30
            elif q in entry.term.lower():
                score = 20

            if score > 0:
                results.append((entry, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return [entry for entry, _ in results]

    def list_by_category(self, category: GlossaryCategory) -> list[GlossaryEntry]:
        """List all entries belonging to a given category.

        Args:
            category: The category to filter by.

        Returns:
            Entries in the specified category, sorted by term_id.
        """
        return sorted(
            (e for e in self._entries.values() if e.category == category),
            key=lambda e: e.term_id,
        )

    def list_by_classification(
        self,
        classification: DataClassification,
    ) -> list[GlossaryEntry]:
        """List all entries with a given data classification.

        Args:
            classification: The sensitivity level to filter by.

        Returns:
            Matching entries, sorted by term_id.
        """
        return sorted(
            (e for e in self._entries.values() if e.classification == classification),
            key=lambda e: e.term_id,
        )

    def sox_relevant(self) -> list[GlossaryEntry]:
        """List all entries flagged as SOX-relevant.

        Returns:
            SOX-relevant entries, sorted by term_id.
        """
        return sorted(
            (e for e in self._entries.values() if e.sox_relevant),
            key=lambda e: e.term_id,
        )

    def pii_terms(self) -> list[GlossaryEntry]:
        """List all entries flagged as containing PII.

        Returns:
            PII-containing entries, sorted by term_id.
        """
        return sorted(
            (e for e in self._entries.values() if e.pii),
            key=lambda e: e.term_id,
        )

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, term_id: str) -> bool:
        return term_id in self._entries

    def __iter__(self) -> Iterator[GlossaryEntry]:
        return iter(self._entries.values())
