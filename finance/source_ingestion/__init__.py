"""Source ingestion and normalization for three-source reconciliation.

This package turns invoice-register, processor (Stripe), and bank-statement
data into canonical, provenance-bearing records that the frozen
reconciliation engine consumes. It is deliberately not a file-import
product:

* one deterministic parser/normalizer/validator pipeline;
* one transport adapter (CSV) plus an in-memory table adapter that proves
  the interface is source-independent;
* three canonical schemas;
* row-level validation with actionable errors and original row references;
* no persistence, API, UI, AI mapping, or reconciliation decisions.

Public surface::

    from finance.source_ingestion import ingest_source, SourceType

    report = ingest_source(
        raw=csv_bytes,
        source_type=SourceType.INVOICE,
        tenant_id="tenant-acme",
        filename="invoices.csv",
    )

Adding a Google Sheets transport later means writing one ``SourceAdapter``
and passing it as ``adapter=``; nothing downstream changes.
"""

from finance.source_ingestion.adapters import (
    CsvAdapter,
    ParsedTable,
    RowShapeIssue,
    SourceAdapter,
    TableAdapter,
    adapter_for,
    content_digest,
)
from finance.source_ingestion.issues import (
    ApiErrorCode,
    IngestionError,
    IssueCode,
    RowIssue,
)
from finance.source_ingestion.normalizer import (
    IngestedRecord,
    NormalizationOutcome,
    Provenance,
    normalize_table,
)
from finance.source_ingestion.schemas import (
    BANK_SCHEMA,
    INVOICE_SCHEMA,
    STRIPE_SCHEMA,
    ColumnSpec,
    ResolvedColumns,
    SourceSchema,
    SourceType,
    normalize_header,
    schema_for,
)
from finance.source_ingestion.service import (
    IngestionReport,
    ingest_source,
    ingest_table,
)

__all__ = [
    "BANK_SCHEMA",
    "INVOICE_SCHEMA",
    "STRIPE_SCHEMA",
    "ApiErrorCode",
    "ColumnSpec",
    "CsvAdapter",
    "IngestedRecord",
    "IngestionError",
    "IngestionReport",
    "IssueCode",
    "NormalizationOutcome",
    "ParsedTable",
    "Provenance",
    "ResolvedColumns",
    "RowIssue",
    "RowShapeIssue",
    "SourceAdapter",
    "SourceSchema",
    "SourceType",
    "TableAdapter",
    "adapter_for",
    "content_digest",
    "ingest_source",
    "ingest_table",
    "normalize_header",
    "normalize_table",
    "schema_for",
]
