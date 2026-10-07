"""P10-01 source registry and inventory completeness contract.

The registry names every data-bearing source; INVENTORY holds one row
per sensitive field with the full descriptor set. The completeness test
(``tests/unit/privacy/test_inventory_completeness.py``) fails until
every registered source is inventoried — unknowns are recorded as gap
strings by :func:`completeness_gaps`, never invented.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import StrEnum


class DataClassification(StrEnum):
    """Closed data-class vocabulary (see DATA_CLASSIFICATION.md)."""

    PUBLIC = "public"
    INTERNAL = "internal"
    PERSONAL = "personal"
    FINANCIAL_SENSITIVE = "financial_sensitive"
    SECRET = "secret"


REQUIRED_SOURCE_IDS: tuple[str, ...] = (
    "razorpay",
    "quickbooks",
    "legacy_financial",
    "sheets",
    "gmail",
    "slack",
    "finsight_derived",
)


@dataclass(frozen=True)
class SourceEntry:
    """One data-bearing source and where it enters the system."""

    source_id: str
    description: str
    module_refs: tuple[str, ...]


SOURCE_REGISTRY: tuple[SourceEntry, ...] = (
    SourceEntry(
        source_id="razorpay",
        description="Razorpay webhooks (HMAC-verified raw provider payloads).",
        module_refs=("apps/api/webhooks.py", "apps/api/middleware.py"),
    ),
    SourceEntry(
        source_id="quickbooks",
        description="QuickBooks accounting records via provider adapter/registry.",
        module_refs=("finance/accounting/mock.py", "finance/integration/registry.py"),
    ),
    SourceEntry(
        source_id="legacy_financial",
        description="Legacy/internal financial source (exact module surface TBD).",
        module_refs=(),
    ),
    SourceEntry(
        source_id="sheets",
        description="Google Sheets ingestion adapter.",
        module_refs=("finance/ingestion/sheets_adapter.py",),
    ),
    SourceEntry(
        source_id="gmail",
        description="Gmail evidence gathering (capability surface; reader TBD).",
        module_refs=("agents/capabilities/capabilities.py",),
    ),
    SourceEntry(
        source_id="slack",
        description="Slack evidence gathering (capability surface; reader TBD).",
        module_refs=("agents/capabilities/capabilities.py",),
    ),
    SourceEntry(
        source_id="finsight_derived",
        description="FinSight-generated data: Postgres rows, LLM context, "
        "telemetry/traces, eval fixtures/reports, observation projections.",
        module_refs=(
            "finance/exceptions/models.py",
            "finance/execution/models.py",
            "shared/safety/idempotency.py",
            "shared/tracing/",
            "tests/fixtures/eval_golden/",
            "apps/api/observations.py",
        ),
    ),
)


@dataclass(frozen=True)
class InventoryRow:
    """One sensitive field with its full handling descriptor set."""

    source_id: str
    field: str
    classification: DataClassification
    purpose: str
    system_of_record: str
    storage: str
    derived_copies: str
    llm_exposure: str
    logging_exposure: str
    retention: str
    deletion_rule: str
    tenant_boundary: str


#: Field-level inventory. Empty until the P10-01 GREEN pass fills it;
#: the completeness test fails while any source is uncovered.
INVENTORY: tuple[InventoryRow, ...] = ()


def completeness_gaps(
    inventory: tuple[InventoryRow, ...] = INVENTORY,
) -> list[str]:
    """List every coverage gap: unknown sources, uncovered sources, blanks.

    A row counts as complete only when all descriptor fields are
    non-blank; blank means "not yet inventoried", never "not applicable"
    (use an explicit N/A-with-reason string for the latter).
    """
    gaps: list[str] = []
    known_ids = {entry.source_id for entry in SOURCE_REGISTRY}
    for required in REQUIRED_SOURCE_IDS:
        if required not in known_ids:
            gaps.append(f"unregistered source: {required}")
    by_source: dict[str, list[InventoryRow]] = {}
    for row in inventory:
        if row.source_id not in known_ids:
            gaps.append(f"row for unknown source: {row.source_id}/{row.field}")
            continue
        by_source.setdefault(row.source_id, []).append(row)
    descriptor_names = [f.name for f in fields(InventoryRow) if f.name != "source_id"]
    for entry in SOURCE_REGISTRY:
        rows = by_source.get(entry.source_id, [])
        if not rows:
            gaps.append(f"uncovered source: {entry.source_id} ({entry.description})")
            continue
        for row in rows:
            for name in descriptor_names:
                value = getattr(row, name)
                text = value.value if isinstance(value, DataClassification) else value
                if not isinstance(text, str) or not text.strip():
                    gaps.append(f"blank {name}: {row.source_id}/{row.field}")
    return gaps
