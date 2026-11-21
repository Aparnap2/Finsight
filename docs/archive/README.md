# Archive — historical product documents

Everything in this directory describes a **previous product generation** or a
completed engineering phase. None of it is normative. The current product is
defined by [`../PRODUCT.md`](../PRODUCT.md).

These files are kept, not deleted, because they contain reasoning that may still
be useful (invariants, failure analysis, deployment lessons). They are moved out
of the repository root so a reader cannot mistake them for the current product.

| File | Described | Why archived |
|---|---|---|
| `PRD.md` | Meridian Commerce, Razorpay/QuickBooks/COBOL reconciliation agent | different company, different provider, different architecture |
| `FinSight_PRD_v1.md` | "FinSight FP&A Intelligence System" product requirements | different product (FP&A commentary, not payment reconciliation) |
| `FinSight_Technical_Architecture.md` | FP&A system technical architecture | describes the FP&A generation |
| `SYSTEM_ARCHITECTURE.md` | FP&A system context, containers, sequences | describes the FP&A generation |
| `IMPLEMENTATION_PLAN.md` | "v2" task plan referencing a `backend/` package that no longer exists | stale plan; task tracking moved to Linear |
| `ROADMAP.md` | FP&A phase roadmap (formula engine, commentary, forecasting) | FP&A generation |
| `todo.md` | production-readiness checklist for the FP&A generation | completed phase, stale baseline numbers |

## Still to be archived

These remain in the tree because code or tests still reference them. They are
**not** normative:

- `docs/architecture/*_CONTRACT.md` — P5–P8 phase contracts for the FP&A and
  runtime generations. Some are cited by test docstrings, so they move only when
  those references are updated in the same commit.
- `docs/00-executive-summary/`, `docs/03-system-design/`, `docs/07-ai-runtime/`,
  `docs/08-evaluation/`, `docs/10-schema/`, `docs/11-data-contracts/`,
  `docs/13-business-knowledge/`, `docs/14-platform/`, `docs/14-testing/` — FP&A
  and platform documentation.

`CHANGELOG.md` stays at the repository root: a changelog is historical by
definition, and its early entries correctly describe the FP&A generation.

## Rule

Do not add to this directory. If a document stops being true, update it or
delete it — archiving is for history that has already been superseded.
