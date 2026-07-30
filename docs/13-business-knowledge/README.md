# Business Knowledge Layer — Index

> **Layer:** Proposed Phase 3 — sits between Data Contracts and the Compute Runtime  
> **Status:** Design proposal — pending review  
> **Audience:** Platform architects, domain engineers, data stewards

## Documents in This Section

| Document | Description |
|----------|-------------|
| [`proposal.md`](./proposal.md) | Phase 3 Business Knowledge Layer — motivation, architecture, components, rollout plan |
| [`glossary.md`](./glossary.md) | Primer glossary of 50 essential FP&A concepts the platform must model |
| [`canonical-objects.md`](./canonical-objects.md) | Design document for canonical value objects (Money, Percentage, CurrencyCode, FiscalPeriod, etc.) |

---

## Documentation Polish Report

This section summarises the consistency audit of `docs/10-schema/`, `docs/11-data-contracts/`, and `docs/12-database/` conducted on 2026-07-30.

### Frontmatter Consistency

| File | Has `> **Layer:**` | Has `> **Audience:**` | Has `> **Status:**` | Issues |
|------|:---:|:---:|:---:|--------|
| `docs/10-schema/indexes.md` | ✗ | ✗ | ✗ | Missing frontmatter entirely |
| `docs/10-schema/query-patterns.md` | ✗ | ✗ | ✗ | Missing frontmatter entirely |
| `docs/10-schema/partitioning.md` | ✗ | ✗ | ✗ | Missing frontmatter entirely |
| `docs/10-schema/vacuum-and-maintenance.md` | ✗ | ✗ | ✗ | Missing frontmatter entirely |
| `docs/10-schema/constraints-performance.md` | ✗ | ✗ | ✗ | Missing frontmatter entirely |
| `docs/11-data-contracts/architecture.md` | ✓ | ✓ | ✓ | No issues |
| `docs/11-data-contracts/domain-models.md` | ✓ | ✓ | ✓ | No issues |
| `docs/11-data-contracts/layer-architecture.md` | ✗ | ✓ | ✓ | Missing `> **Layer:**` — add `Governance & Validation` |
| `docs/11-data-contracts/state-machines.md` | ✓ | ✓ | ✓ | No issues |
| `docs/11-data-contracts/business-rules.md` | ✓ | ✓ | ✓ | No issues |
| `docs/11-data-contracts/implementation-plan.md` | ✗ (N/A) | ✓ | ✓ | N/A for plans; acceptable |
| `docs/12-database/constraints.md` | ✓ | ✗ | ✗ | Has `Scope` and `Design Principle` instead; OK variation |
| `docs/12-database/security.md` | ✓ | ✓ (implied) | ✗ | Has `Scope` and `Design Principle`; OK variation |
| `docs/12-database/rls.md` | ✓ | ✓ (implied) | ✗ | Has `Scope` and `Design Principle`; OK variation |
| `docs/12-database/audit.md` | ✓ | ✓ (implied) | ✗ | Has `Scope` and `Design Principle`; OK variation |
| `docs/12-database/migrations.md` | ✓ | ✓ (implied) | ✗ | Has `Scope` and `Design Principle`; OK variation |

**Recommendation:** Add frontmatter blocks to all `docs/10-schema/` files using the pattern:
```markdown
> **Layer:** 5 (Database Schema)  
> **Audience:** Database engineers, platform team  
> **Status:** Design proposal for Phase 2
```

### Heading Hierarchy

| File | Issues |
|------|--------|
| `docs/10-schema/indexes.md` | Consistent — uses `##` for table groups, inline tables. No issues. |
| `docs/10-schema/query-patterns.md` | Consistent — uses `##` for pattern groups. Good. |
| `docs/10-schema/partitioning.md` | Consistent — uses `##` for major sections, `###` for subsections. Good. |
| `docs/10-schema/vacuum-and-maintenance.md` | Consistent — uses `##` for topics. Good. |
| `docs/10-schema/constraints-performance.md` | Consistent — uses `##` for constraint types. Good. |
| `docs/11-data-contracts/architecture.md` | Consistent — uses `## N.` numbering throughout. Good. |
| `docs/11-data-contracts/domain-models.md` | Consistent — uses `## N.` numbering. Good. |
| `docs/11-data-contracts/layer-architecture.md` | Consistent — uses `## N.` numbering. Good. |
| `docs/11-data-contracts/state-machines.md` | Consistent — uses `## N.` numbering with `### N.M` subsections. Good. |
| `docs/11-data-contracts/business-rules.md` | Consistent — uses `## N.` numbering with `### N.M` subsections. Good. |
| `docs/11-data-contracts/implementation-plan.md` | Consistent — uses `## Phase N:` headings. Good. |
| `docs/12-database/constraints.md` | Consistent — uses `## N.` numbering. Good. |
| `docs/12-database/security.md` | Consistent — uses `## N.` numbering. Good. |
| `docs/12-database/rls.md` | Consistent — uses `## N.` numbering. Good. |
| `docs/12-database/audit.md` | Consistent — uses `## N.` numbering. Good. |
| `docs/12-database/migrations.md` | Consistent — uses `## N.` numbering. Good. |

### Table Formatting

All table-based documents use clean GitHub-flavored Markdown tables with aligned dashes. No issues found.

### Code Block Language Tags

| File | Observations |
|------|--------------|
| `indexes.md` | SQL blocks correctly tagged `sql`. No issues. |
| `query-patterns.md` | SQL and Python blocks tagged `sql` and `python`. No issues. |
| `partitioning.md` | SQL blocks tagged `sql`. No issues. |
| `vacuum-and-maintenance.md` | SQL blocks tagged `sql`, config blocks tagged `ini`. No issues. |
| `constraints-performance.md` | No code blocks. Acceptable. |
| `architecture.md` | Diagram uses code fence. Acceptable. |
| `domain-models.md` | No code blocks in first 30 lines; tables only. Acceptable. |
| `layer-architecture.md` | Diagram uses code fence. Acceptable. |
| `state-machines.md` | Python and SQL blocks tagged. No issues. |
| `business-rules.md` | Python and SQL blocks tagged. No issues. |
| `implementation-plan.md` | Python blocks tagged. No issues. |
| `constraints.md` | SQL blocks tagged `sql`. No issues. |
| `security.md` | SQL, Python, YAML, config blocks tagged. No issues. |
| `rls.md` | SQL and Python blocks tagged. No issues. |
| `audit.md` | SQL blocks tagged `sql`. No issues. |
| `migrations.md` | SQL and Python blocks tagged. No issues. |

### Technical Inaccuracies Found

1. **`docs/10-schema/partitioning.md` lines 23, 45, 62** — `TEXT(7)` is not valid PostgreSQL syntax. Should be `VARCHAR(7)`. The correct pattern appears in `docs/12-database/audit.md` line 19: `VARCHAR(7)`.

2. **`docs/11-data-contracts/layer-architecture.md`** — Missing `> **Layer:**` frontmatter field. The `layer-architecture.md` document describes all 12 layers but does not declare its own layer placement.

3. **`docs/10-schema/` frontmatter gap** — All five files lack any frontmatter block, creating inconsistency with the `docs/11-data-contracts/` and `docs/12-database/` directories which uniformly include structured frontmatter.

### Summary of Required Fixes

| Priority | File | Fix |
|----------|------|-----|
| **High** | `docs/10-schema/indexes.md` | Add frontmatter block |
| **High** | `docs/10-schema/query-patterns.md` | Add frontmatter block |
| **High** | `docs/10-schema/partitioning.md` | Add frontmatter block; fix `TEXT(7)` → `VARCHAR(7)` |
| **High** | `docs/10-schema/vacuum-and-maintenance.md` | Add frontmatter block |
| **High** | `docs/10-schema/constraints-performance.md` | Add frontmatter block |
| **Medium** | `docs/11-data-contracts/layer-architecture.md` | Add `> **Layer:**` line |
| **Low** | All 16 docs | Run through a Markdown linter as part of CI |

---

## Recommended Frontmatter Template

For future documents, use this consistent block at the top of every `.md` file:

```markdown
> **Layer:** `<layer-name>`  
> **Audience:** `<comma-separated roles>`  
> **Status:** `<design proposal | implemented | draft>`
```

For database-layer docs, additionally include:
```markdown
> **Scope:** `<what the document covers>`  
> **Design Principle:** `<one-sentence principle>`
```
