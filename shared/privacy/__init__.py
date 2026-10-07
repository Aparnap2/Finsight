"""Privacy governance surface (P10): classification before enforcement."""

from shared.privacy.inventory import (
    SOURCE_REGISTRY,
    DataClassification,
    InventoryRow,
    SourceEntry,
    completeness_gaps,
)

__all__ = [
    "SOURCE_REGISTRY",
    "DataClassification",
    "InventoryRow",
    "SourceEntry",
    "completeness_gaps",
]
