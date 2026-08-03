"""Business Glossary — canonical registry of every financial term the platform understands.

The glossary provides a single source of truth for term definitions, aliases,
formulas, data classifications, and ownership. Every financial concept in
FinSight should have a corresponding GlossaryEntry.
"""

from business.glossary.models import (
    DataClassification,
    GlossaryCategory,
    GlossaryEntry,
    GlossaryRegistry,
)

__all__ = [
    "DataClassification",
    "GlossaryCategory",
    "GlossaryEntry",
    "GlossaryRegistry",
]
