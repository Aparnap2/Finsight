# Reference Data

Curated, tenant-independent reference datasets for the Finance
Operations OS. These files are **data, not code**: the directory name
contains a hyphen so it is intentionally not a Python package.
Consumers load the YAML files directly (e.g. via the platform config
loader or connectors).

## Layout

| Path | Contents |
|------|----------|
| `currency/iso-4217.yaml` | ISO 4217 currency codes used by tenants |
| `country/iso-3166.yaml` | ISO 3166 country codes used by tenants |
| `calendar/fiscal-calendars.yaml` | Fiscal year templates (12/12, 4-4-5, ...) |
| `coa/skeleton-coa.yaml` | Skeleton chart of accounts tenants extend |
| `tax/tax-regimes.yaml` | Income tax / VAT regime defaults |
| `materiality/defaults.yaml` | Default materiality thresholds and tiers |
| `approval_limits/defaults.yaml` | Default approval authority by role |
| `departments/departments.yaml` | Department / cost center default hierarchy |

## Conventions

- Monetary amounts are **decimal**, never float (use `Decimal` when
  loading).
- Tenants override defaults in `tenants/<tenant>/tenant.yaml`; the
  reference data here is the fallback.
- Each file declares its canonical identifiers so cross-references
  (e.g. country → currency) resolve consistently.
