# Feasibility Report — Deterministic Context Preparation Pipeline

**Date:** 2026-11-25
**Audited HEAD:** `fdc24e1824cc81848ee504955eca6ec31d1bacf3`
**Question:** Is the proposed "Reconciliation Context Builder" (Pydantic context models + deterministic validation sequence + composed `diagnose_exception` + bounded agent) feasible in FinSight, and at what cost?
**Verdict:** **Feasible, low-risk, additive. ~80% of the primitives already exist; the work is composition and typing, not new infrastructure.**

---

## 1. What already exists (mapped to the proposal)

| Proposal deliverable | Existing asset | Evidence |
|---|---|---|
| A. Context models (Pydantic, generated JSON Schema) | `finance/reconciliation/investigation.InvestigationContext`, `InvestigationFinding` (Pydantic); `agents/investigation/context.InvestigationContext` (frozen dataclass); `shared/models/reconciliation.*` | `finance/reconciliation/investigation.py:14-46`; `agents/investigation/context.py:44-60` |
| B. Validation result contract (rule_id, status, severity, expected/actual, evidence_refs) | `finance/validation/harness.ValidationResult` (Pydantic, severity ∈ {error,warning,info}); `finance/source_ingestion.issues.RowIssue` (IssueCode, line_number, field_name, raw, related_line) | `finance/validation/harness.py:13-25`; `finance/source_ingestion/issues.py:150-183` |
| C. Context builder (one plain Python function assembling existing run results) | `agents/investigation/context.build_context()` (tenant/case/evidence authorization, bounds, fingerprinting); `finance/reconciliation/statement_workflow.run_statement_reconciliation()` | `agents/investigation/context.py:118-200`; `statement_workflow.py:300` |
| D. Exception calculator (reuse existing arithmetic, compose diagnostics) | `reconcile()`, `run_statement_reconciliation()`, `ReconciliationReport`, `_severity_for`, `_title_for`, `fingerprint_pair` | `reconciler.py:33`; `persistence.py:249-268` |
| E. Agent integration (prepared context → investigation flow) | `BoundedInvestigation.investigate(InvestigationContext)`; `investigate_exception` route builds context from persisted exception | `finance/reconciliation/investigation.py:48-95`; `apps/api/reconciliation_routes.py:591-645` |
| F. Contract tests (completeness, determinism, precision, tenant isolation) | `tests/unit/api/test_error_contract.py` (149), `tests/integration/test_reconciliation_http.py` (12), golden evals, OKF bundle | `tests/` |
| Immutable snapshot / versioning | `ReconciliationRun`: `engine_version`, `input_fingerprint`, `input_snapshot_ref`; `ReconciliationReport.fingerprint`; `fingerprints.py` | `shared/models/reconciliation.py:180-219`; `statement_workflow.py` (fingerprint) |
| Monetary precision (Decimal, money as strings) | `MoneyDecimal` boundary; `_money_text`/`_render_money` emit strings; `Decimal` everywhere | `apps/api/schemas.py`; `service.py:_money_text` |
| Tenant isolation (server-determined scope) | `TenantAuthMiddleware` (header/actor gate) + `after_begin` GUC hook; 4-test RLS suite | `apps/api/middleware.py`; `tests/integration/test_reconciliation_rls.py` |
| Evidence refs + provenance | `ReconciliationException.evidence_refs` (JSON list); `Provenance` dataclass with source_type/format/content_digest/table_digest/line_number; `EvidenceContext.content_hash` | `shared/models/reconciliation.py:380`; `source_ingestion/normalizer.py:Provenance`; `agents/investigation/context.py:30-42` |
| Audit trail | `audit_logs` append-only (trigger prevents UPDATE/DELETE); `get_audit_events(entity_ids=...)` run-scoped | `finance/reconciliation/persistence.py` |
| Error catalog / codes | `shared/errors/catalog.py` (31 codes, `ErrorSpec`, `code_for_status`); `finance/source_ingestion/issues.ApiErrorCode = ErrorCode` | `shared/errors/catalog.py`; `issues.py:24` |

## 2. What is missing (the actual gaps)

1. **No single composed Pydantic context model.** `InvestigationContext` (finance) is flat and stringly-typed (`match_summary: str`, `allocation_summary: str`); it does not carry calculated variances, validation summary, or rule IDs. The richer `agents/investigation/context.InvestigationContext` is generic (not reconciliation-specific). Neither matches the proposed `ReconciliationRunContext` / `ExceptionInvestigationContext` shape.
2. **No rule-ID-based validation result for reconciliation.** `ValidationResult` (finance/validation) uses `validator_name`/`is_valid`/`messages`, not `rule_id`/`status ∈ {PASS,FAIL,WARNING,BLOCKED,NOT_APPLICABLE}`/`expected`/`actual`/`difference`. `RowIssue` is ingestion-only. There is no reconciliation-level rule result (e.g. `PAYOUT_004` fee variance).
3. **No `diagnose_exception(snapshot_id, exception_id)` composed function.** Arithmetic exists (`reconcile`, `run_statement_reconciliation`) but there is no single entry point that, given a persisted run + exception, assembles the evidence packet + calculates the relevant variance/mismatch and returns a self-contained context. The route currently does ad-hoc assembly inline.
4. **No validation *sequence* runner.** The proposed 10-step ordered pipeline (source validation → normalization → integrity → cross-source matching → allocation → fee/refund calc → variance → invariants → evidence assembly → eligibility) is implicit in `run_statement_reconciliation` + `ingest_source`, not a named, auditable, ordered sequence with per-step status.
5. **Investigation does not receive structured calculations.** `BoundedInvestigation.investigate` receives `match_summary`/`allocation_summary` strings; monetary values are not passed as structured `Decimal`-serialized fields. The LLM cannot be given a clean evidence packet without re-deriving it.
6. **No "investigation eligibility" gate.** The proposal's step 10 (sufficient evidence → eligible) is not explicit; abstention happens reactively inside `investigate`.

## 3. Feasibility assessment

- **Effort:** Medium (1–2 slices). No new tables, brokers, or frameworks. All work is additive composition + Pydantic models + tests.
- **Risk:** Low. The deterministic core (`reconcile`, `run_statement_reconciliation`, fingerprints) is frozen and must not change; the new layer reads from persisted runs, it does not re-run ingestion.
- **Compatibility:** Additive only. New models + one builder function + one composed diagnostic function + optional route wiring. No breaking API changes. Existing golden tests remain green (they test the core, not the context layer).
- **Tenant safety:** Straightforward — the builder must take `tenant_id` from the trusted actor (as `investigate_exception` already does) and filter every query by tenant; cross-tenant → 404, never 403 (established pattern).
- **Determinism:** Achievable — `ReconciliationReport.fingerprint` and `engine_version`/`input_fingerprint` already exist; the new context model must embed `run_id`, `snapshot_id`, `engine_version`, `rule_version`, and a content fingerprint, and be byte-identical for the same input (testable with `json.dumps(..., sort_keys=True)` equality).
- **Token efficiency:** Achievable — send run summary + selected exception packet, not all source rows (matches existing `MAX_EVIDENCE_ITEMS`/`MAX_CONTEXT_CHARS` bounds in `agents/investigation/context.py`).

## 4. Recommended bounded implementation (no new subsystem)

Following the standing principle ("add code only when a demonstrated requirement cannot be met cleanly with what already exists"):

| Deliverable | Scope | Reuses |
|---|---|---|
| A. Context models | `finance/reconciliation/context.py`: `ReconciliationRunContext`, `ExceptionInvestigationContext`, `ValidationRuleResult` (Pydantic, `model_json_schema()` for the contract). Money as `str`. | `ReconciliationException`, `ReconciliationMatch`, `PayoutAllocation`, `AllocationLeg`, `ReconciliationRun` |
| B. Validation result contract | Extend `finance/validation/harness.ValidationResult` OR add a reconciliation-specific `RuleResult` with `rule_id`, `status ∈ {PASS,FAIL,WARNING,BLOCKED,NOT_APPLICABLE}`, `severity`, `expected`, `actual`, `difference`, `currency`, `evidence_refs`. Keep both; do not collapse. | `RowIssue`, `IssueCode` |
| C. Context builder | `build_exception_context(session, tenant_id, run_id, exception_id) -> ExceptionInvestigationContext` — one plain function, reads persisted rows, computes variances via existing `_severity_for`/arithmetic, assembles evidence refs + provenance. | `persistence.get_run`, `get_audit_events(entity_ids=...)`, `statement_workflow` arithmetic helpers |
| D. Exception calculator | `diagnose_exception(snapshot_id, exception_id)` = builder + a small set of deterministic checks (payout variance, fee variance, allocation balance, missing-transaction comparison), each returning a `RuleResult`. | `reconcile`, `ReconciliationReport` |
| E. Agent integration | Pass `ExceptionInvestigationContext` (serialized, money as strings) into `BoundedInvestigation` as structured fields instead of `match_summary`/`allocation_summary` strings. Keep `InvestigationContext` (finance) as the LLM boundary. | `BoundedInvestigation`, `InvestigationFinding` |
| F. Contract tests | Completeness (all fields populated), determinism (byte-identical re-run), precision (Decimal round-trip), tenant isolation (cross-tenant 404), eligibility gate, mutation (wrong operator killed). | existing test patterns |

**Explicitly NOT in scope (per standing exclusions):** new DB tables, message broker, agent framework, graph DB, new orchestrator, LLM-side arithmetic, removing `detail` from API, Stage 2 metrics.

## 5. Acceptance criteria (mapped to the proposal's checklist)

- [ ] All three sources ingested once per run (already true — `ingest_source` is pure; run persists once).
- [ ] Every validation has a rule ID and explicit status (gap #2 — implement).
- [ ] Money calculations use `Decimal` and preserve currency (already true; serialize as strings in context).
- [ ] Every discrepancy has supporting evidence refs (already true — `ReconciliationException.evidence_refs`).
- [ ] Missing evidence explicitly reported (gap #5/#6 — add `investigation_eligible` + reason).
- [ ] Run context versioned and fingerprinted (already true — `engine_version`/`input_fingerprint`/`fingerprint`).
- [ ] Same snapshot → byte-identical calculation output (test to add).
- [ ] Agent receives complete case-specific context (gap #5 — structured fields).
- [ ] No arbitrary source hunting for ordinary cases (gap #3 — `diagnose_exception`).
- [ ] AI cannot change reconciliation results (already enforced — `BoundedInvestigation` only reads).
- [ ] Existing engine golden tests unchanged and green (no core changes).

## 6. Recommendation

Proceed. The proposal is not a new subsystem; it is the **composition layer the codebase is already shaped for**. The highest-value, lowest-risk first slice is **(A) + (C)**: define the two Pydantic context models and a `build_exception_context` function reading from persisted rows, with contract tests for completeness + determinism + tenant isolation. That alone closes gaps #1, #3, #5 and makes the agent boundary typed. Then (D) and (E) in a second slice, (B) and (F) alongside.

Do not start (E) (agent wiring) until (A)+(C) are green and the context shape is stable — the agent prompt depends on it.

**Estimated scope:** ~400–600 LOC new, ~0 LOC changed in frozen core, ~15–25 new tests. One Ralph Loop task per deliverable (A, B, C, D, E, F).