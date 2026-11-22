# FinSight Documentation Disposition

**Version:** 1.0 (Task D deliverable)
**Status:** Read-only investigation
**Date:** 2026-11-22

---

## Canonical Authority Map

| Document | Authority | Classification |
|---|---|---|
| `docs/PRODUCT.md` | Product scope and requirements | AUTHORITATIVE |
| `docs/ARCHITECTURE.md` | Actual system architecture | MISSING (needs creation) |
| `docs/specs/DOMAIN_MODEL.md` | Domain contracts | AUTHORITATIVE (new) |
| `docs/specs/DATABASE_SCHEMA.md` | Data model | AUTHORITATIVE (new) |
| `docs/specs/API_CONTRACT.md` | API behavior | AUTHORITATIVE (new) |
| `docs/specs/STATE_MACHINES.md` | State transitions | AUTHORITATIVE (new) |
| `docs/specs/ERROR_CATALOG.md` | Error semantics | AUTHORITATIVE (new) |
| `docs/specs/OBSERVABILITY_CONTRACT.md` | Monitoring contracts | AUTHORITATIVE (new) |
| `docs/specs/STAGING_WORKFLOW.md` | CI/staging behavior | AUTHORITATIVE (new) |
| `docs/specs/ACCEPTANCE_MATRIX.md` | Requirements-to-tests mapping | AUTHORITATIVE (new) |
| `docs/OPERATIONS.md` | Running and recovering the system | MISSING (needs creation) |
| `docs/TESTING.md` | Testing strategy and commands | PARTIAL (CONTRIBUTING.md covers some) |
| `AGENTS.md` | Agent implementation rules | AUTHORITATIVE |
| `CONTRIBUTING.md` | Contributor workflow | AUTHORITATIVE |

---

## Documentation Inventory

### Authoritative (keep as-is)

| Document | Purpose | Issues |
|---|---|---|
| `docs/PRODUCT.md` | Canonical product spec | None. Keep. |
| `docs/release/RECONCILIATION_BOUNDARY.md` | Cleanup boundary manifest | Updated per slice. Keep. |
| `docs/release/RECONCILIATION_CONTRACT.md` | Behavioral contract | Keep. |
| `docs/release/LOCAL_DEPLOYMENT.md` | Local deployment guide | Keep. |
| `AGENTS.md` | Agent instructions | Testing standard added. Keep. |
| `CONTRIBUTING.md` | Contributor guide | Testing standard added. Keep. |
| `README.md` | Project README | Rewritten to reconciliation product. Keep. |
| `docs/specs/*` (8 files) | Architecture specs | New. Frozen pending review. |

### Supporting (keep, may need updates)

| Document | Purpose | Issues |
|---|---|---|
| `docs/repository.md` | Folder map | Updated (frontend/ removed). Keep. |
| `docs/09-platform/*.md` | Platform layer docs | Some stale (references deleted frontend). Update in slice 9. |
| `docs/12-database/rls.md` | RLS documentation | Useful. Keep. |
| `docs/08-evaluation/` | Evaluation docs | Useful. Keep. |
| `openspec/` | Spec-driven workflow | Active. Keep. |
| `SECURITY.md` | Security policy | Keep. |

### Historical (archive, keep for reference)

| Document | Purpose | Issues |
|---|---|---|
| `docs/archive/PRD.md` | Original PRD | Archived. Keep. |
| `docs/archive/FinSight_PRD_v1.md` | PRD v1 | Archived. Keep. |
| `docs/archive/FinSight_Technical_Architecture.md` | Technical architecture | Archived. Keep. |
| `docs/archive/IMPLEMENTATION_PLAN.md` | Implementation plan | Archived. Keep. |
| `docs/archive/ROADMAP.md` | Roadmap | Archived. Keep. |
| `docs/archive/todo.md` | Todo list | Archived. Keep. |
| `docs/archive/SYSTEM_ARCHITECTURE.md` | System architecture | Archived. Keep. |
| `docs/archive/README.md` | Archive index | Keep. |

### Stale (remove or archive)

| Document | Issue | Action |
|---|---|---|
| `docs/07-ai-runtime/ai-architecture-guide.md` | Describes FP&A AI runtime (deleted generation) | Archive in slice 9 |
| `docs/14-platform/implementation-plan.md` | Describes deleted `backend/` package | Archive in slice 9 |
| `docs/11-data-contracts/implementation-plan.md` | References `finance/data_contracts/` (doesn't exist) | Archive in slice 9 |
| `docs/architecture/*_CONTRACT.md` (21 files) | Phase docs for excluded generations; still cited by 3 test files | Archive after updating test references (slice 9) |

### Broken References Identified

| Source | Reference | Target (missing) | Status |
|---|---|---|---|
| `docs/11-data-contracts/implementation-plan.md` | `finance/data_contracts/` | Doesn't exist | Broken |
| `docs/architecture/test_approval.py` (test) | `docs/architecture/*_CONTRACT.md` | Exists but stale | Cited |
| `docs/architecture/test_correlation.py` (test) | `docs/architecture/*_CONTRACT.md` | Exists but stale | Cited |
| `tests/contract/test_p7_08_control_plane_integration_red.py:560` | `docs/architecture/*_CONTRACT.md` | Exists but stale | Cited |
| `finance/llm/__init__.py` | `shared.utils.llm_client` | Fixed in slice 5 | Done |

### Duplicate Specifications

| Concern | Documents | Resolution |
|---|---|---|
| Product definition | `docs/PRODUCT.md` (canonical) + 7 archived | `docs/PRODUCT.md` is authoritative; rest archived |
| Architecture | `docs/SYSTEM_ARCHITECTURE.md` (archived) + `docs/09-platform/` | Needs `docs/ARCHITECTURE.md` (missing) |
| Testing | `CONTRIBUTING.md` + `AGENTS.md` | Both now have testing standard (added in slice 5 commit) |

### Missing Documents (needed for spec freeze)

| Document | Purpose | Status |
|---|---|---|
| `docs/ARCHITECTURE.md` | Actual system architecture | Not created |
| `docs/OPERATIONS.md` | Running and recovering the system | Not created |
| `docs/TESTING.md` | Testing strategy and commands | Partial (CONTRIBUTING.md) |
| `docs/api/*` | API documentation | Not created (OpenAPI from FastAPI) |

---

## Recommendations

1. **Create `docs/ARCHITECTURE.md`** from the architecture convergence investigation (Deliverable 1-2). This should describe the actual current architecture, not the target.
2. **Archive stale docs** in slice 9, not now. The 21 `docs/architecture/*_CONTRACT.md` files are still cited by tests.
3. **Fix broken references** in slice 9 after updating test references.
4. **Do not claim features as implemented** unless code and tests establish it. `docs/PRODUCT.md` §5 already does this correctly.