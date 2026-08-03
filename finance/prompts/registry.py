"""Prompt template registry.

Manages versioned prompt templates by name, supporting registration,
lookup, and enumeration.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PromptTemplate(BaseModel):
    """A versioned prompt template with metadata."""

    name: str
    version: str
    template: str
    description: str = ""
    created_at: datetime


class PromptRegistry:
    """Registry for named, versioned prompt templates.

    Examples::

        registry = PromptRegistry()
        registry.register(
            name="variance_analysis",
            version="1.0.0",
            template="Analyze {account_name} variance.",
        )
        tmpl = registry.get("variance_analysis")
    """

    def __init__(self) -> None:
        self._templates: dict[str, PromptTemplate] = {}

    def register(
        self,
        name: str,
        version: str,
        template: str,
        description: str = "",
    ) -> None:
        """Register a prompt template by name.

        Args:
            name: Unique prompt name.
            version: Semantic version string.
            template: Prompt template string with ``{variable}`` placeholders.
            description: Optional human-readable description.

        Raises:
            ValueError: If a template with *name* is already registered.
        """
        if name in self._templates:
            raise ValueError(
                f"Prompt '{name}' is already registered"
            )
        self._templates[name] = PromptTemplate(
            name=name,
            version=version,
            template=template,
            description=description,
            created_at=datetime.now(),
        )

    def get(self, name: str) -> PromptTemplate:
        """Get a registered prompt template by name.

        Args:
            name: The prompt name to look up.

        Returns:
            The matching :class:`PromptTemplate`.

        Raises:
            KeyError: If *name* has not been registered.
        """
        if name not in self._templates:
            raise KeyError(f"Prompt '{name}' not found in registry")
        return self._templates[name]

    def has(self, name: str) -> bool:
        """Check whether a prompt name is registered."""
        return name in self._templates

    def list_names(self) -> list[str]:
        """Return a sorted list of all registered prompt names."""
        return sorted(self._templates.keys())
