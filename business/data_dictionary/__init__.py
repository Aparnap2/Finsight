"""Semantic Data Dictionary — field-level business metadata for every column.

The data dictionary bridges database schemas and business meaning. Every
column in the FinSight data model has a business name, definition, data
classification, SOX relevance, PII flag, and optional glossary reference.
"""

from business.data_dictionary.models import (
    ColumnMetadata,
    DataDictionary,
    TableMetadata,
)

__all__ = [
    "ColumnMetadata",
    "DataDictionary",
    "TableMetadata",
]
