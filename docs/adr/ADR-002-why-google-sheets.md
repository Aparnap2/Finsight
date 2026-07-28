# ADR-002: Why Google Sheets as Initial Data Source

**Status:** Accepted  
**Date:** 2026-07-28  
**Deciders:** Architecture Team, Product Management  

---

## Context

FinSight needs financial data to analyse. The target enterprise market (FP&A teams) stores budget and actual data in a variety of systems — ERPs (NetSuite, SAP, Dynamics), planning tools (Anaplan, Adaptive), databases (PostgreSQL, Snowflake), and, overwhelmingly, spreadsheets.

Industry research and user interviews confirmed:
- **~80% of FP&A teams** use spreadsheets (Excel or Google Sheets) as their primary analysis tool
- Spreadsheets are the common denominator — even teams with ERPs export to spreadsheets for variance analysis
- Google Sheets is preferred over Excel in mid-market FP&A due to real-time collaboration, API accessibility, and no desktop dependency
- Building connectors to every ERP/planning tool before proving product-market fit would delay MVP by 6–12 months

The risk: coupling business logic to a specific spreadsheet platform would make the system brittle and hard to migrate when users demand ERP connectors.

## Decision

We adopt Google Sheets as the **initial primary data source** for the MVP, with two critical architectural safeguards:

### Primary: Google Sheets API

- **Stage 1 (MVP):** FP&A teams maintain their source data in Google Sheets. A designated "FinSight Source" sheet contains defined columns: `account_id`, `account_name`, `department`, `period`, `amount`, with optional `notes`.
- **Stage 1 ingestion:** A lightweight Google Sheets reader (using the Google Sheets API v4) pulls data at pipeline invocation. No webhooks, no real-time sync, no change tracking.
- **Stage 1 structure:** The sheet schema is strict — the ingestion layer validates column presence and data types before accepting data. Non-conforming sheets produce a clear validation error.

### Secondary: CSV Fallback

- Every Google Sheets ingestion path has an equivalent **CSV upload** endpoint (`POST /import/csv`).
- The CSV format mirrors the Google Sheets schema exactly.
- Users can download their sheet as CSV and upload directly — no Google dependency for pipeline execution.
- The CSV path must always be supported (never removed) to prevent Google lock-in.

### Safeguard: Never Couple Business Logic to Sheets

The cardinal rule:

> **`finance/` and `agents/` never import Google Sheets libraries.**
> **`shared/` never references Google Sheets concepts.**

Data source abstraction is enforced at the ingestion boundary:

```
Google Sheets API  ──┐
                     ├──→ ingestion/ingestion_agent.py ──→ rest of system
CSV Upload ──────────┘
```

- `finance/ingestion/ingestion_agent.py` calls reader functions that return plain `list[dict]` — identical shape regardless of source
- The reader layer (Google Sheets client, CSV parser) lives in `shared/utils/tools/` as tool contracts
- The rest of the system operates on `PipelineState["actuals"]` and `PipelineState["budget"]` — it has no knowledge of whether the data came from Sheets, CSV, or (future) a direct ERP connector

### Future: Connector Abstraction

When ERP connectors are added (Phase 2), they follow the same pattern:

1. Implement a `ToolResult`-returning reader in `shared/utils/tools/`
2. The ingestion node processes `ToolResult` uniformly regardless of source
3. Data quality checks (`freshness`, `coverage`, `source_diversity`) apply to all sources equally

## Consequences

### Positive

- **Rapid MVP delivery.** No ERP vendor negotiations, no OAuth complexity, no custom API integrations needed for launch.
- **Universal compatibility.** Every FP&A team can export data to Sheets or CSV. The system works on day one for any organisation.
- **Source abstraction from day one.** Because we enforce the decoupling from the start, adding a new data source (NetSuite, SAP, Anaplan) is additive — no refactoring of `finance/` or `agents/`.
- **CSV as emergency path.** If Google API goes down, users upload CSVs. No pipeline blockage.

### Negative

- **Manual data preparation.** FP&A teams must format their sheets to the expected schema. Automation is limited until API connectors exist.
- **No real-time sync.** Data is pulled on demand (pipeline invocation), not pushed. Freshness depends on manual sheet updates.
- **Google API rate limits.** Large charts of accounts may hit Google Sheets API quotas. Mitigated by CSV fallback.
- **MVP scope excludes write-back.** FinSight analyses cannot be written back to Google Sheets in v1. Users manually copy results.

## Compliance

1. **No Google Sheets imports in `finance/`.** The `finance/pyproject.toml` must not include `google-api-python-client` or `gspread`. Only `shared/utils/tools/` may contain Google Sheets dependencies.
2. **`ingestion_node` returns `list[dict]` only.** The ingestion layer's return type is pure Python dicts — no Google-specific types, no Sheet cell references, no row objects.
3. **CSV upload endpoint always supported.** The `POST /import/csv` route must never be removed. It is the guaranteed data entry path.
4. **Every data source test has a CSV equivalent.** Integration tests that run against Google Sheets data must also run against CSV-sourced data to prove source transparency.
5. **No spreadsheets in `finance/domain/`.** The domain model represents financial concepts (accounts, periods, entities) — never rows, cells, sheets, or workbooks.
