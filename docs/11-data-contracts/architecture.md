# Data Contract Architecture

> **Layer:** Governance & Interchange — sits between Connectors and the Compute Runtime
> **Audience:** Platform architects, DataOps engineers, backend developers
> **Status:** Design proposal for Phase 2

## 1. Overview

The Data Contract Layer is the structured interchange boundary between external data sources (CSV, Google Sheets, ERP APIs, PostgreSQL queries) and FinSight's internal compute machinery. It guarantees that every data point crossing into the runtime meets structural, type, and lineage requirements — and that schema changes at the source are detected, classified, and managed (not silently accepted or silently broken).

```
 External Sources                     Data Contract Layer                    Compute Runtime
 ┌──────────────────┐     ┌─────────────────────────────────────────┐     ┌──────────────────┐
 │  CSV Upload      │     │  Connector Validation  (Layer 1)        │     │  DualValidator   │
 │  Google Sheets   │────▶│  API Contract          (Layer 2)        │────▶│  Pandera Schema  │
 │  ERP API         │     │  Dataset Schema        (Layer 3)        │     │  Domain Models   │
 │  PostgreSQL      │     │  Domain Models         (Layer 4)        │     │  Business Rules  │
 └──────────────────┘     │  Versioned Models      (Layer 10)       │     └──────────────────┘
                          └─────────────────────────────────────────┘
                                     │
                                     ▼
                          ┌──────────────────────┐
                          │  Rejected / Warnings  │
                          │  (structured errors)  │
                          └──────────────────────┘
```

### 1.1 Why a Data Contract Layer?

Without explicit data contracts, the following failure modes are impossible to detect at ingestion time:

| Problem | Without Contract | With Contract |
|---------|-----------------|---------------|
| **New column added** | Silently ignored or causes `KeyError` | Contract version mismatch detected; column classified as ignored/mapped/rejected |
| **Column removed** | Downstream `None` errors | Required field check fails at boundary |
| **Type changed** (string→numeric) | DuckDB parse error mid-query | Pandera type violation at ingest |
| **Currency field free-text** | Downstream conversion failure | `ISOCurrency` enum reject or coercion |
| **Vendor name variant** | Duplicate created | Normalizer maps to canonical ID |

### 1.2 Design Principles

1. **Reject early, reject loudly.** Schema violations are caught at the boundary, not mid-pipeline. The caller receives a structured error immediately.
2. **Backward compatibility is explicit.** A contract version change is a deliberate act (new file, new tests, new migration path).
3. **Unknown columns are classified.** Every new column in source data is either ignored (with warning), explicitly mapped, or rejected — never silently dropped.
4. **Monetary precision is sacred.** `Decimal` is the only allowed type. Floats are rejected at every boundary (Pydantic `BeforeValidator`, Pandera check, DB `Numeric` column).
5. **Lineage is non-optional.** Every `Dataset` carries a `source_fingerprint` and `imported_at` timestamp. Every domain model that crosses the boundary can be traced back to a source record.

---

## 2. Layer Architecture

The Data Contract Layer spans 4 of the 12 validation layers:

| Layer | Name | Responsibility | Located In |
|-------|------|---------------|------------|
| 1 | **Connector Validation** | Provider protocol check, credential validation, source reachability | `finance/integration/` |
| 2 | **API Contract** | `RuntimeRequest` Pydantic validation, job type checks, parameter schema | `python_runtime/api/models.py` |
| 3 | **Dataset Schema** | Pandera `DataFrameModel` per pipeline type | `python_runtime/validation/schemas.py` |
| 10 | **Versioned Models** | Schema version resolution, backward compat, migration | `finance/data_contracts/` (proposed) |

### 2.1 Integration with Existing Code

```
finance/integration/                  python_runtime/
  protocol.py  ← SpreadsheetProvider    api/models.py  ← RuntimeRequest
  csv_provider.py                       importers/     ← Dataset, Importer Protocol
  google_sheets_provider.py             validation/    ← DualValidator, Pandera schemas
  factory.py                            dispatcher/    ← JobHandler, Dispatcher
    │                                     │
    ▼                                     ▼
finance/data_contracts/  (NEW)         finance/domain/  (existing 16 models)
  registry.py           ← version mgmt  _types.py       ← MoneyDecimal
  v1/                   ← contract defs company.py      ← Company
  v2/                   ← next version   budget.py       ← Budget, BudgetLine
  migrations/           ← transform fn   ...             ← 16 domain models
```

---

## 3. Schema Versioning Strategy

### 3.1 Version Lifecycle

Every domain model that crosses the data contract boundary has a version lifecycle:

```
InvoiceV1 ──→ InvoiceV2 ──→ InvoiceV3 ──→ InvoiceV4
  │              │              │              │
  │ active       │ active       │ active       │ deprecated (read-only)
  │              │              │              │
  └── consumers  └── consumers  └── consumers  └── migration target
```

- **Active:** New records can be created with this version. Both read and write are supported.
- **Deprecated:** New records cannot be created. Existing records are readable. A migration path exists.
- **Sunset:** Removed from the registry. All consumers must have migrated.

### 3.2 Contract Definition Format

Data contracts are defined as Pydantic models with version metadata:

```python
# finance/data_contracts/v1/invoice.py (proposed)

from datetime import date
from decimal import Decimal
from pydantic import BaseModel, Field
from typing import Annotated
from shared.models.database import MoneyDecimal


class InvoiceV1(BaseModel):
    """Invoice data contract v1 — initial version."""
    
    __contract_version__ = "invoice-v1"
    __deprecated__ = False
    __sunset_date__ = None  # e.g., "2027-01-01"
    
    id: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    vendor_name: str = Field(min_length=1)
    account_code: str = Field(min_length=1)
    amount: MoneyDecimal
    currency: str = Field(pattern=r"^[A-Z]{3}$")  # ISO 4217
    invoice_date: date
    description: str = ""
    department: str | None = None
```

```python
# finance/data_contracts/v2/invoice.py (proposed) — adds tax_amount, removes description

from datetime import date
from pydantic import BaseModel, Field
from shared.models.database import MoneyDecimal


class InvoiceV2(BaseModel):
    """Invoice data contract v2 — adds tax breakdown."""
    
    __contract_version__ = "invoice-v2"
    __deprecated__ = False
    
    id: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    vendor_name: str = Field(min_length=1)
    account_code: str = Field(min_length=1)
    amount: MoneyDecimal
    tax_amount: MoneyDecimal = Decimal("0")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    invoice_date: date
    department: str | None = None
```

### 3.3 Registry

```python
# finance/data_contracts/registry.py (proposed)

from __future__ import annotations
from typing import Any
from pydantic import BaseModel


class ContractInfo:
    """Metadata about a registered data contract version."""
    
    def __init__(
        self,
        version: str,
        model_class: type[BaseModel],
        deprecated: bool = False,
        sunset_date: str | None = None,
        migration_target: str | None = None,
    ):
        self.version = version
        self.model_class = model_class
        self.deprecated = deprecated
        self.sunset_date = sunset_date
        self.migration_target = migration_target


class ContractRegistry:
    """Central registry of all data contract versions.
    
    Usage:
        registry = ContractRegistry()
        registry.register(InvoiceV1)
        registry.register(InvoiceV2)
        latest = registry.latest("invoice")
        v1 = registry.get("invoice", "invoice-v1")
    """
    
    _contracts: dict[str, list[ContractInfo]] = {}
    
    @classmethod
    def register(cls, model_class: type[BaseModel]) -> None:
        """Register a contract version from its class metadata."""
        name = model_class.__name__.split("V")[0].lower()  # "invoice" from "InvoiceV1"
        version = getattr(model_class, "__contract_version__", None)
        if version is None:
            raise ValueError(f"{model_class.__name__} has no __contract_version__")
        
        info = ContractInfo(
            version=version,
            model_class=model_class,
            deprecated=getattr(model_class, "__deprecated__", False),
            sunset_date=getattr(model_class, "__sunset_date__", None),
        )
        if name not in cls._contracts:
            cls._contracts[name] = []
        cls._contracts[name].append(info)
    
    @classmethod
    def latest(cls, name: str) -> type[BaseModel] | None:
        """Get the latest non-deprecated contract version."""
        versions = cls._contracts.get(name, [])
        active = [v for v in versions if not v.deprecated]
        if not active:
            return None
        return active[-1].model_class  # last registered active version
    
    @classmethod
    def get(cls, name: str, version: str) -> type[BaseModel] | None:
        """Get a specific contract version."""
        for info in cls._contracts.get(name, []):
            if info.version == version:
                return info.model_class
        return None
```

---

## 4. Column Handling Strategy

When a new column appears in source data, the system classifies it into one of three actions:

| Action | Definition | Example | Effect |
|--------|------------|---------|--------|
| **Ignore** | Column is unknown and not required | `notes` column in a budget upload | Column is dropped from the loaded `DataFrame`; a warning is emitted to the import log |
| **Map** | Column matches a known canonical field via alias registry | `"Vendor"` → `vendor_name`, `"Vendor Name"` → `vendor_name` | Column is renamed to canonical name via `ColumnMapper` |
| **Reject** | Column conflicts with an existing column or is a breaking change | `amount` column appears alongside `budget_amount` in a budget dataset | Import fails with `DATASET_SCHEMA_VIOLATION`; the user must remove or rename the ambiguous column |

### 4.1 ColumnAlias Registry

```python
# finance/data_contracts/column_mapping.py (proposed)

from __future__ import annotations


COLUMN_ALIASES: dict[str, list[str]] = {
    "vendor_name": ["vendor", "vendor name", "supplier", "supplier_name"],
    "account_code": ["account", "account_number", "gl_code", "acct"],
    "department": ["dept", "department_name", "dept_name", "division"],
    "amount": ["total", "total_amount", "value", "sum"],
    "currency": ["ccy", "currency_code", "iso_code"],
    "invoice_date": ["date", "inv_date", "doc_date", "transaction_date"],
    "description": ["desc", "notes", "memo", "comment"],
    "period": ["fiscal_period", "period_id", "fp", "month"],
}


def resolve_column_name(raw_name: str) -> str:
    """Resolve a raw column name to a canonical name, or return as-is."""
    lower = raw_name.lower().strip()
    for canonical, aliases in COLUMN_ALIASES.items():
        if lower == canonical or lower in aliases:
            return canonical
    return raw_name  # unknown column — will be classified as ignore
```

---

## 5. Required/Optional Column Handling

| Column category | Pandera Field | On missing | Behaviour |
|----------------|---------------|------------|-----------|
| **Required** | `nullable=False` | Reject | `DATASET_MISSING_COLUMN` error |
| **Optional** | `nullable=True` | Default to `None` | Warning emitted in import log |
| **Required with default** | `nullable=False, default=...` | Default applied | No error |
| **Optional with default** | `nullable=True, default=...` | Default applied | No error |

### 5.1 Type Coercion Strategy

Where Pandera cannot natively coerce (e.g., `Decimal`), the `Normalizer` stage handles conversion:

| Source Type | Target Type | Coercion | Failure Behaviour |
|-------------|-------------|----------|-------------------|
| `str` → `Decimal` | Monetary amount | `CurrencyNormalizer` | Leave as-is; Pandera will reject |
| `str` → `date` | Date field | `DateNormalizer` (tries 6 formats) | Leave as-is; Pandera will reject |
| `str` → `bool` | Boolean flag | `BooleanCoercer` | Default to `False` |
| `int` → `Decimal` | Monetary amount | Automatic (`Decimal(int)`) | Always succeeds |

---

## 6. Compatibility Guarantees

### 6.1 Breaking vs. Non-Breaking Changes

| Change | Classification | Version Bump | Migration Required |
|--------|---------------|--------------|-------------------|
| Add optional column (nullable) | Non-breaking | Minor | No |
| Add required column | Breaking | Major | Yes (provide default for existing records) |
| Remove a column | Breaking | Major | Yes (drop from consumers first) |
| Rename a column | Breaking | Major | Yes (alias in `COLUMN_ALIASES` during transition) |
| Change type (wider, e.g., `int`→`Decimal`) | Non-breaking | Minor | No |
| Change type (narrower or incompatible) | Breaking | Major | Yes |
| Add enum variant | Non-breaking | Minor | No |
| Remove enum variant | Breaking | Major | Yes |
| Relax nullability | Non-breaking | Minor | No |
| Tighten nullability | Breaking | Major | Yes |

### 6.2 Deprecation Window

Deprecated contract versions remain readable for **6 months** after deprecation notification. After sunset, the data must have been migrated to a newer version or the contract endpoint returns a `410 Gone` error.

---

## 7. End-to-End Flow

```
Source Data (CSV/Sheets/API)
    │
    ▼
┌──────────────────────────────────────────────┐
│ Layer 1: Connector Validation                 │
│  • Provider protocol check                    │
│  • Credential validation                      │
│  • Source reachability                        │
│  Result: ToolResult or ImportError            │
└──────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────┐
│ Layer 2: API Contract                         │
│  • RuntimeRequest Pydantic model              │
│  • job_type enum check                        │
│  • source_config validation                   │
│  Result: validated RuntimeRequest             │
└──────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────┐
│ Layer 10: Versioned Models                    │
│  • Resolve contract version from request      │
│  • Load correct InvoiceV2 (or V1, V3)         │
│  • Apply ColumnMapper aliases                 │
│  • Classify unknown columns (ignore/map/rej)  │
│  Result: schema-matched Dataset               │
└──────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────┐
│ Layer 3: Dataset Schema (Pandera)             │
│  • FinancialDatasetSchema validation          │
│  • Null checks, type checks, enum checks      │
│  • Numeric bounds (ge=0)                      │
│  Result: validated DataFrame or ComputeError  │
└──────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────┐
│ Normalizer (pre-execution)                    │
│  • CurrencyNormalizer                         │
│  • DateNormalizer                             │
│  • BooleanCoercer                             │
│  • VendorIDCanonicalizer                      │
│  Result: cleaned Dataset                      │
└──────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────┐
│ Layer 4: Domain Models                        │
│  • Pydantic models (Budget, Actual, Variance) │
│  • MoneyDecimal rejection of float            │
│  • Cross-field invariants                     │
│  Result: domain objects or ValidationError    │
└──────────────────────────────────────────────┘
    │
    ▼
  Compute Runtime (analytics, forecast, risk...)
```

---

## 8. Error Codes

Data Contract Layer errors follow the same structure as `RuntimeErrorInfo` in `python_runtime/shared/errors.py`:

| Code | Layer | Example | Recoverable |
|------|-------|---------|-------------|
| `CONTRACT_VERSION_UNKNOWN` | Versioned Models | Requested contract `invoice-v0` not in registry | No |
| `CONTRACT_DEPRECATED` | Versioned Models | Contract `invoice-v1` is deprecated | Yes (use latest) |
| `CONTRACT_COLUMN_CONFLICT` | Versioned Models | `amount` column ambiguous in source | No |
| `CONTRACT_MIGRATION_FAILED` | Versioned Models | Automatic migration from V1→V2 failed | No |
| `DATASET_UNKNOWN_COLUMN` | Column Mapping | New column `tax_rate` not in registry | Yes (ignored) |
| `DATASET_MISSING_COLUMN` | Pandera | Required column `account_id` missing | No |
| `DATASET_TYPE_MISMATCH` | Pandera | `amount` is string, not float | No |
| `DATASET_NULL_VIOLATION` | Pandera | `vendor_id` contains nulls | No |
| `DATASET_ENUM_VIOLATION` | Pandera | `currency` is "BTC" | No |
| `DATASET_BOUND_VIOLATION` | Pandera | `tenure_years` is -5 | No |
| `NORMALIZATION_FAILED` | Normalizer | Unparseable date format | Yes |
| `INVARIANT_VIOLATION` | Domain Model | Budget period after fiscal year end | No |

---

## 9. Integration Points Summary

| Existing Module | Integration | Proposed Change |
|----------------|-------------|-----------------|
| `python_runtime/validation/schemas.py` | Pandera schemas consumed after contract resolution | No change needed (schemas already exist) |
| `python_runtime/validation/validator.py` | `DualValidator` orchestrates Pydantic→Pandera | Add optional contract version parameter |
| `python_runtime/importers/protocol.py` | `Dataset` is universal container | No change needed |
| `python_runtime/models.py` | `Job` stores reference to contract version | Add `contract_version: str | None` field |
| `finance/domain/` | Domain models are the output of contract layer | Add `__contract_version__` metadata mixin |
| `shared/models/database.py` | ORM models persist the domain data | Add `contract_version` column for traceability |
| `finance/integration/` | Providers produce raw data | Add `ContractRegistry.resolve()` in factory |

---

## 10. Directory Structure (Proposed)

```
finance/data_contracts/
├── __init__.py              # Re-exports
├── registry.py              # ContractRegistry
├── column_mapping.py        # COLUMN_ALIASES, resolve_column_name()
├── migration.py             # Migration functions between versions
├── compatibility.py         # Breaking/non-breaking classification
├── v1/
│   ├── __init__.py
│   ├── invoice.py           # InvoiceV1
│   ├── vendor.py            # VendorV1
│   ├── payment.py           # PaymentV1
│   └── ledger.py            # LedgerEntryV1
├── v2/
│   ├── __init__.py
│   ├── invoice.py           # InvoiceV2 (adds tax_amount)
│   └── vendor.py            # VendorV2 (adds risk_score)
└── migrations/
    ├── __init__.py
    ├── invoice_v1_to_v2.py  # Transform function
    └── vendor_v1_to_v2.py   # Transform function
```

---

---

## 12. Related Documents

This document is part of the `docs/11-data-contracts/` suite:

| Document | Purpose |
|----------|---------|
| `architecture.md` | **(This file)** — Overall data contract architecture, schema versioning, column handling |
| `domain-models.md` | Rich domain model design, aggregate architecture, invariant enforcement, model audit |
| `state-machines.md` | State machine definitions for all 7 workflow entities, CHECK constraints, dispatcher integration |
| `business-rules.md` | Business rule engine design, validation vs. rules, rule catalog, policy integration |
| `layer-architecture.md` | How all 12 validation layers compose, data flow, error propagation, degraded mode cascading |
| `implementation-plan.md` | 6-phase rollout plan with tasks, effort estimates, risks |

### Integration Points

| Existing Module | How It Connects |
|----------------|-----------------|
| `python_runtime/validation/validator.py` | `DualValidator` orchestrates Layer 2 (Pydantic) → Layer 3 (Pandera) → Layer 10 (Versioned Models) |
| `python_runtime/dispatcher/router.py` | `Dispatcher` enforces JobSM state machine (Layer 6) |
| `finance/integration/` | Providers validate at Layer 1; data contracts resolve at Layer 10 |
| `shared/utils/validators/assertion_validator.py` | Layer 12 — assertion support level validation |
| `shared/models/state.py` | `PipelineState` carries `degraded_modes` from Layer 7 → Layer 12 |
| `finance/domain/` | Domain models enforce Layer 4 invariants and Layer 6 state transitions |
| `shared/models/database.py` | ORM models provide Layer 5 constraints; `AuditLog` implements Layer 9 |
| `apps/api/routes.py` | API routes enforce Layer 8 security (tenant_id validation) |
| `agents/assertion_pipeline.py` | Consumes Layer 7 rule evaluations for policy routing |

---

## 13. Key Architectural Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Contract format | Pydantic v2 models with `__contract_version__` metadata | No new schema language; reuses existing validation stack |
| Registry location | `finance/data_contracts/` | Contracts are DataOps-owned; sits alongside domain models |
| Version identifier | Semantic `<name>-v<N>` (e.g., `invoice-v1`) | Simple, human-readable, supports cross-type references |
| Migration engine | Explicit Python functions per version pair | Avoids framework lock-in; each migration is testable |
| Unknown column handling | Classify as ignore/map/reject | Explicit over silent; prevents surprise breakage |
| Monetary type | `MoneyDecimal` (Pydantic annotated `Decimal`) | Rejects float at every boundary; consistent with existing `_types.py` |
