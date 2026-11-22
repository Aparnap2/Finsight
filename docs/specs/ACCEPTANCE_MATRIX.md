# FinSight Acceptance Matrix

**Version:** 1.0 (Frozen — requires explicit approval to change)
**Status:** Draft for review
**Canonical source:** All other spec files in `docs/specs/`

This is the controlling specification. Every requirement in the other seven files must map to a test. No requirement may be marked complete without evidence.

---

## 1. Financial Correctness

| Req ID | Requirement | Component | Test Location | Test Type | Expected Behavior | Failure Scenario | Acceptance Criterion |
|---|---|---|---|---|---|---|---|
| FC-01 | Allocation conservation | `finance/reconciliation/allocation.py` | `tests/unit/reconciliation/test_financial_contract.py` | Unit | `allocated + open == eligible net`; `allocated + unallocated == deposit` | Change `+` to `-` in conservation | Test fails |
| FC-02 | No double allocation | `finance/reconciliation/allocation.py` | `tests/unit/reconciliation/test_financial_contract.py` | Unit | Each charge in at most one leg per run | Allocate same charge twice | Test fails |
| FC-03 | Decimal-only money | `finance/reconciliation/models.py`, `bank.py` | `tests/unit/reconciliation/test_money_guards.py` | Unit | Reject float/bool at boundary | Pass `float` for money field | `FloatMoneyError` raised |
| FC-04 | No false settlement | `finance/reconciliation/allocation.py` | `tests/unit/reconciliation/test_financial_contract.py` | Unit | Settled ⇒ zero residual + fully credited legs | Force premature settlement | Test fails |
| FC-05 | Determinism | `finance/reconciliation/` (pure, no clock/random/network) | `tests/unit/reconciliation/test_financial_contract.py` | Unit | Same inputs ⇒ same fingerprint | Add `random` or `datetime.now()` | Test fails |
| FC-06 | Provenance | `finance/reconciliation/fingerprints.py` | `tests/unit/reconciliation/test_financial_contract.py` | Unit | Leg fingerprint matches input charge | Substitute evidence reference | Test fails |
| FC-07 | Currency isolation | `finance/reconciliation/allocation.py` | `tests/unit/reconciliation/test_money_guards.py` | Unit | No cross-currency matching | Match different currencies | `CurrencyMismatch` raised |
| FC-08 | Tenant isolation | `finance/reconciliation/allocation.py`, middleware | `tests/unit/reconciliation/test_tenant_isolation.py` | Unit | No cross-tenant data access | Cross-tenant query | `TenantIsolationError` raised |
| FC-09 | Refund conservation | `finance/reconciliation/allocation.py` | `tests/unit/reconciliation/test_financial_contract.py` | Unit | Refunds separate, never increase settled value | Omit refund from net calc | Test fails |
| FC-10 | No float in output | `finance/reconciliation/operator_report.py` | `tests/unit/reconciliation/test_financial_contract.py` | Unit | Recursive float scan of emitted report | Add float to report | Test fails |
| FC-11 | Scenario catalogue (9 scenarios) | `finance/reconciliation/statement_workflow.py` | `tests/unit/reconciliation/test_triangle.py` | Unit | Frozen status/outcome/code per scenario | Change scenario outcome | Test fails |
| FC-12 | Byte-reproducible evidence | `finance/reconciliation/operator_report.py` | `tests/unit/reconciliation/test_golden_evidence.py` | Unit | report.md/report.json/run.json byte-identical | Modify any output byte | Test fails |

---

## 2. Ingestion

| Req ID | Requirement | Component | Test Location | Test Type | Expected Behavior | Failure Scenario | Acceptance Criterion |
|---|---|---|---|---|---|---|---|
| IN-01 | Create import session | `finance/ingestion/service.py` (new) | `tests/integration/test_ingestion.py` (new) | Integration | Session created with status CREATED | Invalid period | 400 error |
| IN-02 | Upload invoice CSV | `finance/ingestion/service.py` (new) | `tests/integration/test_ingestion.py` (new) | Integration | File stored, rows parsed, status UPLOADING | Wrong format | 400 INVALID_FILE |
| IN-03 | Upload Stripe CSV | Same as IN-02 | Same | Integration | Same | Same | Same |
| IN-04 | Upload bank CSV | Same as IN-02 | Same | Integration | Same | Same | Same |
| IN-05 | Validate import | `finance/ingestion/validator.py` (new) | `tests/integration/test_ingestion.py` (new) | Integration | Per-row errors returned, status READY/REJECTED | Missing columns | 400 INVALID_SCHEMA |
| IN-06 | Duplicate file detection | `finance/ingestion/service.py` (new) | `tests/integration/test_ingestion.py` (new) | Integration | Same content hash returns existing file | Re-upload same file | 409 DUPLICATE_IMPORT |
| IN-07 | File size limit | `finance/ingestion/validator.py` (new) | `tests/integration/test_ingestion.py` (new) | Integration | Reject oversized files | Upload 11MB file | 413 error |
| IN-08 | Empty file handling | `finance/ingestion/validator.py` (new) | `tests/integration/test_ingestion.py` (new) | Integration | Reject empty files | Upload 0-byte file | 400 INVALID_FILE |
| IN-09 | Malformed CSV handling | `finance/ingestion/parser.py` (new) | `tests/integration/test_ingestion.py` (new) | Integration | Row-level errors, not crash | Mixed valid/invalid rows | Partial success with errors |
| IN-10 | Preview before accept | `finance/ingestion/service.py` (new) | `tests/integration/test_ingestion.py` (new) | Integration | Preview endpoint returns parsed rows | — | 200 with row preview |

---

## 3. Persistence

| Req ID | Requirement | Component | Test Location | Test Type | Expected Behavior | Failure Scenario | Acceptance Criterion |
|---|---|---|---|---|---|---|---|
| PE-01 | Reconciliation run persists | `finance/persistence/repositories/` (new) | `tests/integration/test_persistence.py` (new) | Integration | Run record in DB after completion | DB disconnect mid-run | Rollback, no partial record |
| PE-02 | Matches persist | Same | Same | Integration | Match records in DB | — | Query returns matches |
| PE-03 | Allocations persist | Same | Same | Integration | Allocation + legs in DB | — | Query returns allocations |
| PE-04 | Exceptions persist | Same | Same | Integration | Exception records in DB | — | Query returns exceptions |
| PE-05 | Decisions persist (append-only) | Same | Same | Integration | Decision record in DB, immutable | UPDATE/DELETE attempt | DB trigger raises error |
| PE-06 | Audit events persist (append-only) | Same | Same | Integration | Audit event in DB, immutable | UPDATE/DELETE attempt | DB trigger raises error |
| PE-07 | Run survives restart | `finance/persistence/` (new) | `tests/integration/test_persistence.py` (new) | Integration | Run retrievable after API restart | Kill and restart container | GET returns same data |
| PE-08 | Idempotent run creation | `finance/persistence/repositories/` (new) | `tests/integration/test_idempotency.py` (new) | Integration | Same key returns existing run | Duplicate POST | 200 with original run_id |
| PE-09 | Migration currency | Alembic | `tests/integration/test_migrations.py` (new) | Integration | `alembic current` == head | Fresh DB | All migrations applied |
| PE-10 | RLS tenant isolation | PostgreSQL RLS | `tests/integration/test_tenant_isolation.py` (new) | Integration | Cross-tenant query returns empty | Query with wrong tenant_id | 0 rows returned |

---

## 4. API

| Req ID | Requirement | Component | Test Location | Test Type | Expected Behavior | Failure Scenario | Acceptance Criterion |
|---|---|---|---|---|---|---|---|
| API-01 | Create import session | `apps/api/routes/imports.py` (new) | `tests/integration/test_api.py` (new) | Integration | 201 with session_id | Invalid period | 400 |
| API-02 | Upload file | Same | Same | Integration | 201 with file_id | Wrong type | 400 |
| API-03 | Validate import | Same | Same | Integration | 200 with validation result | No files | 400 |
| API-04 | Get session | Same | Same | Integration | 200 with session detail | Not found | 404 |
| API-05 | Start reconciliation | `apps/api/routes/runs.py` (new) | `tests/integration/test_api.py` (new) | Integration | 201 with run_id | Session not ready | 400 |
| API-06 | Get run | Same | Same | Integration | 200 with run status | Not found | 404 |
| API-07 | Get matches | Same | Same | Integration | 200 with match list | Not found | 404 |
| API-08 | Get allocations | Same | Same | Integration | 200 with allocation list | Not found | 404 |
| API-09 | Get exceptions | Same | Same | Integration | 200 with exception list | Not found | 404 |
| API-10 | Get exception detail | `apps/api/routes/exceptions.py` (new) | `tests/integration/test_api.py` (new) | Integration | 200 with exception detail | Not found | 404 |
| API-11 | Start investigation | Same | Same | Integration | 201 with investigation_id | Already investigating | 400 |
| API-12 | Get investigation | Same | Same | Integration | 200 with investigation result | Not found | 404 |
| API-13 | Record decision | Same | Same | Integration | 201 with decision | Invalid transition | 409 |
| API-14 | Create export | `apps/api/routes/exports.py` (new) | `tests/integration/test_api.py` (new) | Integration | 201 with export_id | Run not succeeded | 400 |
| API-15 | Get export | Same | Same | Integration | 200 with export status | Not found | 404 |
| API-16 | Health live | `apps/api/routes/health.py` (new) | `tests/integration/test_health.py` (new) | Integration | 200 alive | — | 200 |
| API-17 | Health ready | Same | Same | Integration | 200 ready (DB ok) | DB down | 503 not_ready |
| API-18 | Cross-tenant access | All routes | `tests/integration/test_security.py` (new) | Integration | 403 | Wrong tenant header | 403 TENANT_ACCESS_DENIED |

---

## 5. Security

| Req ID | Requirement | Component | Test Location | Test Type | Expected Behavior | Failure Scenario | Acceptance Criterion |
|---|---|---|---|---|---|---|---|
| SEC-01 | Authentication required | `apps/api/middleware.py` | `tests/integration/test_security.py` (new) | Integration | 401 without auth | Missing auth header | 401 UNAUTHORIZED |
| SEC-02 | Tenant isolation (API) | `apps/api/middleware.py` | `tests/integration/test_security.py` (new) | Integration | 403 cross-tenant | Wrong tenant header | 403 TENANT_ACCESS_DENIED |
| SEC-03 | Tenant isolation (DB) | PostgreSQL RLS | `tests/integration/test_tenant_isolation.py` (new) | Integration | 0 rows cross-tenant | Query with wrong tenant | 0 rows |
| SEC-04 | Authorization (role check) | `finplatform/rbac/matrix.py` | `tests/integration/test_security.py` (new) | Integration | 403 insufficient role | Low-privilege user attempts decision | 403 FORBIDDEN |
| SEC-05 | No secrets in logs | `shared/observability/logging.py` (new) | `tests/integration/test_security.py` (new) | Integration | No secrets in log output | Trigger error with secret in context | Secret not in logs |
| SEC-06 | Upload size limit | `finance/ingestion/validator.py` (new) | `tests/integration/test_ingestion.py` (new) | Integration | Reject oversized files | Upload 11MB file | 413 |
| SEC-07 | Safe filename handling | `finance/ingestion/validator.py` (new) | `tests/integration/test_ingestion.py` (new) | Integration | Reject path traversal | Upload `../../../etc/passwd` | 400 INVALID_FILE |
| SEC-08 | No SQL injection | SQLAlchemy ORM | `tests/integration/test_security.py` (new) | Integration | Parameterized queries | SQL in input field | No injection |

---

## 6. Exception Lifecycle

| Req ID | Requirement | Component | Test Location | Test Type | Expected Behavior | Failure Scenario | Acceptance Criterion |
|---|---|---|---|---|---|---|---|
| EX-01 | State machine transitions | `finance/workflows/exception_lifecycle.py` (new) | `tests/unit/test_exception_lifecycle.py` (new) | Unit | Valid transitions succeed | Invalid transition | `INVALID_STATE_TRANSITION` |
| EX-02 | Append-only decisions | DB trigger + app logic | `tests/integration/test_exception_lifecycle.py` (new) | Integration | UPDATE/DELETE rejected | Attempt UPDATE | DB error |
| EX-03 | Human decision recorded | `finance/workflows/exception_lifecycle.py` (new) | `tests/integration/test_exception_lifecycle.py` (new) | Integration | Decision + audit event persisted | — | 201 with decision_id |
| EX-04 | Authorization for decisions | `finplatform/rbac/matrix.py` | `tests/integration/test_exception_lifecycle.py` (new) | Integration | Only MANAGER can resolve | ANALYST attempts resolve | 403 FORBIDDEN |
| EX-05 | Reopen exception | Same as EX-01 | Same as EX-03 | Integration | RESOLVED → REOPENED allowed | Reopen resolved exception | 201 with new status |
| EX-06 | Investigation lifecycle | `finance/workflows/investigation.py` (new) | `tests/integration/test_investigation.py` (new) | Integration | PENDING → RUNNING → COMPLETED | Provider timeout | FAILED status |

---

## 7. AI Investigation

| Req ID | Requirement | Component | Test Location | Test Type | Expected Behavior | Failure Scenario | Acceptance Criterion |
|---|---|---|---|---|---|---|---|
| AI-01 | AI reads stored evidence only | `agents/investigation/` (adapted) | `tests/integration/test_investigation.py` (new) | Integration | Investigation uses stored evidence refs | — | Evidence refs in result |
| AI-02 | Structured output validation | `finance/reasoning/llm_boundary.py` | `tests/unit/test_investigation.py` (new) | Unit | Invalid schema → degraded mode | Malformed JSON response | Fallback to deterministic |
| AI-03 | Provider timeout handling | `shared/llm/` (consolidated) | `tests/integration/test_investigation.py` (new) | Integration | Timeout → FAILED status, financial data intact | Configure provider to hang | 504, run still accessible |
| AI-04 | Provider unavailable handling | Same | Same | Integration | Unavailable → FAILED status | Configure provider to fail | 503, run still accessible |
| AI-05 | Prompt injection resistance | `shared/privacy/boundary.py` | `tests/unit/test_privacy.py` (existing) | Unit | PII never reaches provider | PII in uploaded content | PII not in prompt |
| AI-06 | AI never modifies financial results | `finance/workflows/investigation.py` (new) | `tests/integration/test_investigation.py` (new) | Integration | Investigation is read-only | — | Financial results unchanged after investigation |
| AI-07 | Deterministic fixtures in CI | `shared/llm/fake.py` (FakeLLM) | `tests/integration/test_investigation.py` (new) | Integration | FakeLLM used in CI, no live calls | — | No network calls in CI |

---

## 8. Exports

| Req ID | Requirement | Component | Test Location | Test Type | Expected Behavior | Failure Scenario | Acceptance Criterion |
|---|---|---|---|---|---|---|---|
| EX-01 | CSV export | `finance/workflows/export.py` (new) | `tests/integration/test_export.py` (new) | Integration | CSV file generated with correct data | — | 201 with export_id |
| EX-02 | JSON export | Same | Same | Integration | JSON file generated | — | 201 with export_id |
| EX-03 | Markdown export | Same | Same | Integration | Markdown file generated | — | 201 with export_id |
| EX-04 | Export status tracking | Same | Same | Integration | PENDING → GENERATING → COMPLETED | Storage failure | FAILED status |
| EX-05 | Export download | Same | Same | Integration | File downloadable | — | 200 with file |

---

## 9. Observability

| Req ID | Requirement | Component | Test Location | Test Type | Expected Behavior | Failure Scenario | Acceptance Criterion |
|---|---|---|---|---|---|---|---|
| OB-01 | Structured JSON logs | `shared/observability/logging.py` (new) | `tests/integration/test_observability.py` (new) | Integration | Every log line is valid JSON | — | Parse log line as JSON |
| OB-02 | Correlation ID propagation | `apps/api/middleware.py` | `tests/integration/test_observability.py` (new) | Integration | request_id in response headers | — | X-Request-ID header present |
| OB-03 | Health live | `apps/api/routes/health.py` (new) | `tests/integration/test_health.py` (new) | Integration | 200 alive | — | 200 |
| OB-04 | Health ready | Same | Same | Integration | 200 ready (DB ok) | DB down | 503 not_ready |
| OB-05 | Metrics endpoint | `apps/api/routes/health.py` (new) | `tests/integration/test_observability.py` (new) | Integration | Prometheus metrics exposed | — | /metrics returns metrics |
| OB-06 | No secrets in logs | `shared/observability/logging.py` (new) | `tests/integration/test_security.py` (new) | Integration | No secrets in log output | Trigger error | Secret not in logs |
| OB-07 | Run diagnosis by run_id | `shared/observability/logging.py` (new) | `tests/integration/test_observability.py` (new) | Integration | Logs searchable by run_id | — | Logs contain run_id |

---

## 10. Staging & Recovery

| Req ID | Requirement | Component | Test Location | Test Type | Expected Behavior | Failure Scenario | Acceptance Criterion |
|---|---|---|---|---|---|---|---|
| ST-01 | Docker build | `Dockerfile` | CI workflow | CI | Image builds successfully | — | docker build exit 0 |
| ST-02 | Migration on fresh DB | Alembic | CI workflow | CI | All migrations apply | Fresh DB | alembic current == head |
| ST-03 | Readiness after migration | `apps/api/routes/health.py` (new) | CI workflow | CI | /health/ready returns 200 | — | 200 ready |
| ST-04 | Full workflow E2E | Playwright | `tests/e2e/test_reconciliation_workflow.py` (new) | E2E | Upload → reconcile → inspect → investigate → decide → export | — | All steps pass |
| ST-05 | Failure injection: invalid file | Ingestion | `tests/integration/test_failure_injection.py` (new) | Integration | 400 with row errors | Malformed CSV | 400 |
| ST-06 | Failure injection: DB disconnect | Persistence | `tests/integration/test_failure_injection.py` (new) | Integration | 503, no partial commit | Stop PostgreSQL mid-run | 503, run FAILED |
| ST-07 | Failure injection: provider timeout | AI investigation | `tests/integration/test_failure_injection.py` (new) | Integration | 504, financial data intact | Configure provider to hang | 504, run accessible |
| ST-08 | Concurrent requests | API | `tests/integration/test_concurrency.py` (new) | Integration | All idempotent, no duplicates | 10 parallel POST /runs | Single run created |
| ST-09 | Restart recovery | Application | `tests/integration/test_recovery.py` (new) | Integration | Run reaches terminal state | Kill + restart container | SUCCEEDED or FAILED |
| ST-10 | Diagnostics on failure | CI workflow | CI workflow | CI | Logs/metrics/traces uploaded | Any test failure | Artifacts uploaded |
| ST-11 | Teardown on failure | CI workflow | CI workflow | CI | docker compose down runs | Any test failure | Cleanup executed |

---

## 11. Test Count Summary

| Category | Existing | New (planned) | Total |
|---|---|---|---|
| Unit (finance/reconciliation) | 352 | 0 | 352 |
| Unit (other) | ~3,000 | ~50 (new ingestion, exception, AI tests) | ~3,050 |
| Contract | 165 (p8) + golden evidence | ~20 (new contract tests) | ~185 |
| Integration | ~50 | ~80 (new API, persistence, security, etc.) | ~130 |
| E2E (Playwright) | 0 | ~10 (critical journeys) | ~10 |
| Failure injection | 0 | ~15 | ~15 |
| **Total** | **~3,805** | **~175** | **~3,980** |

---

## 12. Cross-Specification Consistency Checklist

- [ ] Every domain entity has a corresponding persistence definition (DATABASE_SCHEMA.md §3)
- [ ] Every state enum matches its transition table (STATE_MACHINES.md §2-§6)
- [ ] Every API request/response references an existing schema (API_CONTRACT.md §2)
- [ ] Every API error maps to the error catalog (ERROR_CATALOG.md §2)
- [ ] Every state-changing operation specifies its audit behavior (STATE_MACHINES.md §2-§6)
- [ ] Every important operation has defined idempotency semantics (DATABASE_SCHEMA.md §6)
- [ ] Every required metric has a defined source and bounded labels (OBSERVABILITY_CONTRACT.md §3)
- [ ] Every health endpoint has defined semantics (OBSERVABILITY_CONTRACT.md §4)
- [ ] Every acceptance requirement maps to a test (this file, §1-§10)
- [ ] No contradictory architecture decisions exist
- [ ] No product feature outside `docs/PRODUCT.md` scope

### Identified Contradictions (to resolve before freeze)

1. **Auth**: PRODUCT.md §6 mentions "Better Auth (frontend)" but frontend (Next.js) was deleted. Auth strategy is unresolved (demo headers currently). Resolution: implement explicit auth boundary (JWT or session) as part of P2.

2. **S3 vs local storage**: PRODUCT.md §3 says S3-compatible storage is in scope. But `shared/aws/config.py` is test-only and `finance/object_store/s3_adapter.py` has no production callers. Resolution: implement S3 adapter in P1 or defer to local filesystem for portfolio.

3. **Background workers**: PRODUCT.md §6 mentions SQS worker. But the reconciliation product is synchronous request-driven. Resolution: defer SQS/Temporal to post-MVP unless demonstrated requirement.

4. **AI eval CI**: `finance/evaluation/` is live in CI but is FP&A-generation code. Resolution: migrate eval gate to reconciliation scenarios or retire. Protected until resolved.

5. **`finance/llm/` docstring**: Updated to reference `shared/llm/`. No functional contradiction.