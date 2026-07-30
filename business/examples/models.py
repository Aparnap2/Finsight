"""Pydantic models for the Example Library.

Defines ExampleSet (a single curated dataset with metadata) and ExampleLibrary
(a registry with domain/tag lookup, sampling, and edge-case filtering).
"""

# mypy: disable-error-code="misc"
# Pydantic mypy plugin is unavailable with mypy v2.x (see pyproject.toml).

from __future__ import annotations

import csv
import io
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ExampleSet(BaseModel):
    """A curated dataset used for testing FP&A domain logic.

    Attributes:
        example_id: Unique identifier for this example set.
        name: Human-readable name.
        description: What this dataset tests or demonstrates.
        domain: Business domain (e.g. "invoices", "trial_balance", "variance").
        data: List of raw row dicts parsed from the source.
        tags: Classification tags for filtering (e.g. "edge-case", "valid").
        source: Origin path or description.
    """

    example_id: str
    name: str
    description: str
    domain: str
    data: list[dict[str, Any]]
    tags: list[str] = Field(default_factory=list)
    source: str = ""

    @classmethod
    def from_csv(
        cls,
        example_id: str,
        name: str,
        description: str,
        domain: str,
        csv_path: Path,
        tags: list[str] | None = None,
        source: str = "",
    ) -> ExampleSet:
        """Parse a CSV file into an ExampleSet, converting numeric values to Decimal.

        Args:
            example_id: Unique identifier.
            name: Human-readable name.
            description: What this dataset tests.
            domain: Business domain label.
            csv_path: Path to the CSV file.
            tags: Optional classification tags.
            source: Override source description (defaults to the file path).

        Returns:
            A fully populated ExampleSet.
        """
        data: list[dict[str, Any]] = []
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                msg = f"CSV file {csv_path} has no headers"
                raise ValueError(msg)
            for row in reader:
                parsed: dict[str, Any] = {}
                for key, value in row.items():
                    parsed[key] = _try_parse_decimal(value)
                data.append(parsed)

        return cls(
            example_id=example_id,
            name=name,
            description=description,
            domain=domain,
            data=data,
            tags=tags or [],
            source=source or str(csv_path),
        )

    def to_csv_string(self) -> str:
        """Serialise the data back to CSV (header + rows)."""
        if not self.data:
            return ""
        output = io.StringIO()
        fieldnames = list(self.data[0].keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(self.data)
        return output.getvalue()

    def row_count(self) -> int:
        """Return the number of data rows."""
        return len(self.data)

    def filter(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Return rows where all supplied key-value pairs match.

        Args:
            **kwargs: Field name to expected value mappings.

        Returns:
            Filtered list of row dicts.
        """
        result = list(self.data)
        for key, expected in kwargs.items():
            result = [r for r in result if r.get(key) == expected]
        return result


class ExampleLibrary(BaseModel):
    """Registry of ExampleSets with domain/tag lookup and sampling helpers.

    Attributes:
        examples: Dict of example_id → ExampleSet.
    """

    examples: dict[str, ExampleSet] = Field(default_factory=dict)

    def register(self, example: ExampleSet) -> None:
        """Register a single example set.

        Args:
            example: The ExampleSet to register.
        """
        self.examples[example.example_id] = example

    def register_all(self, *examples: ExampleSet) -> None:
        """Register multiple example sets at once.

        Args:
            *examples: One or more ExampleSet instances.
        """
        for ex in examples:
            self.register(ex)

    def by_domain(self, domain: str) -> list[ExampleSet]:
        """Return all example sets belonging to the given domain.

        Args:
            domain: Domain string to match (case-sensitive).

        Returns:
            List of matching ExampleSet objects.
        """
        return [ex for ex in self.examples.values() if ex.domain == domain]

    def by_tag(self, tag: str) -> list[ExampleSet]:
        """Return all example sets that have a specific tag.

        Args:
            tag: Tag string to match (case-sensitive).

        Returns:
            List of matching ExampleSet objects.
        """
        return [ex for ex in self.examples.values() if tag in ex.tags]

    def get_sample(self, domain: str, n: int = 3) -> list[dict[str, Any]]:
        """Return up to *n* sample rows from the first matching domain set.

        Args:
            domain: Domain to sample from.
            n: Maximum number of rows to return.

        Returns:
            Up to *n* row dicts.
        """
        sets = self.by_domain(domain)
        if not sets:
            return []
        return sets[0].data[:n]

    def get_edge_cases(self) -> list[ExampleSet]:
        """Return all example sets tagged ``edge-case``.

        Returns:
            List of ExampleSet objects with the edge-case tag.
        """
        return self.by_tag("edge-case")

    def __len__(self) -> int:
        """Return the number of registered example sets."""
        return len(self.examples)


def _try_parse_decimal(value: str | None) -> Any:
    """Parse a string value into Decimal if it looks numeric; return as-is otherwise.

    Args:
        value: Raw string from CSV, possibly None.

    Returns:
        Decimal for numeric-looking strings, or the original string.
    """
    if value is None or value.strip() == "":
        return None
    stripped = value.strip()
    try:
        return Decimal(stripped)
    except Exception:
        return stripped
