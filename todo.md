# FinSight — Final Verification & Production Readiness

> **Epic:** https://github.com/Aparnap2/Finsight/issues/5
> Branch: `feat/verification-readiness` (off `feat/ml-reasoning-runtime` / PR #4)
> Base branch for PR #4: `feat/ml-reasoning-runtime` → main

The **last major engineering phase** before release. Goal: prove the platform is
**correct, reliable, secure, observable, and production-ready**. NO new features.

## Ops rules

- **Never start more than one Docker container at a time** (project rule).
- Run verification gates before every commit: `uv run ruff check .` → `uv run python -m mypy .` → `uv run python -m pytest -q`.
- Delegate each issue to a dedicated subagent (`python-agent`, `backend-developer`, `testing-agent`, `database-optimizer`, `devops-agent`, etc.).
- Pre-existing failures (known debt, do NOT chase): `tests/llm/test_providers.py` (poolside + fallback chain — needs live LLM keys), `tests/test_python_runtime/test_api.py` (4 job API tests — need X-Tenant-ID/X-Role headers + Postgres).

---

## Repository layout (baseline)

- Layers: `shared` ← `finance` ← `agents` ← `apps`, plus `finplatform` (layer-0 config), `business`, `contracts`, `reference-data`, `database/migrations`, `alembic`.
- Money = `decimal.Decimal` (never float). 100-char line limit. mypy strict. Ruff `E,F,I,N,UP,B,A,SIM`.
- Full suite baseline (pre-verification): **767 passed / 6 failed / 6 skipped**.
- ruff baseline: 268 errors → **0 (DONE via Issue #6)**.
- mypy baseline: 655 errors in 73 files → **0 in 351 files (DONE via Issue #6)**.
- Doc note: `apps/api/middleware.py` + `agents/orchestrator.py:139 build_graph` show as "unused" in vulture — these are FastAPI/registry-decorated, false positives.

---

## Workstream A — Engineering Quality (issues #6 #7 #8)

### [ ] Issue #6 — A1: Engineering Quality Gate
https://github.com/Aparnap2/Finsight/issues/6

Gates:
- [x] Ruff 0 errors/warnings (268 → 0)
- [x] mypy strict (655 → 0, 351 files)
- [x] Secret scanning (clean outside .venv)
- [x] Dependency audit (`uvx pip-audit`: no known vulnerabilities)
- [x] SQL lint / migration validation (migration module imports; alembic 2 versions)
- [x] OpenAPI validation (19 paths generate)
- [x] Architecture conformance (AST check: no layer violations)
- [x] Import cycle detection (no true module cycles)
- [x] Docs links (only false positive: `dataset.rows` is code)
- [ ] Dead code detection (vulture 564 hits — all FastAPI/pydantic false positives, needs manual triage + whitelist)
- [ ] License headers (decide convention)
- [x] Report: **`docs/14-testing/ENGINEERING_QUALITY.md` still MISSING — agent created the fixes but not the report. WRITE IT.**

Notes: `git diff --name-only` = 106 files modified by the agent (mostly `# type: ignore` removal + annotations). Verify agent changes are all legitimate before commit.

### [ ] Issue #7 — A2: Domain Validation
https://github.com/Aparnap2/Finsight/issues/7

15 aggregates: Invoice, Vendor, Budget, Forecast, Ledger, Journal, TrialBalance, BalanceSheet, IncomeStatement, CashFlow, Variance, Recommendation, Evidence, Assertion, Commentary. Target **250+ tests**. Each: construction / invariants / serialization / validation / version migration / edge cases.

Deliverable: `docs/14-testing/DOMAIN_VALIDATION.md` + `tests/unit/test_domain/`.

### [ ] Issue #8 — A3: Engine Validation
https://github.com/Aparnap2/Finsight/issues/8

8 engines: Formula, Forecast, Recommendation, Policy, Evidence, Validation, Materiality, Variance. Each: correctness / determinism / idempotency / property (hypothesis) / fuzz / benchmark.

Deliverable: `docs/14-testing/ENGINE_VALIDATION.md` + `tests/property/` + `tests/fuzz/` + `tests/benchmarks/`.

---

## Workstream B — Platform Reliability (issues #9 #10 #11)

### [ ] Issue #9 — B1: Runtime Reliability
https://github.com/Aparnap2/Finsight/issues/9

6 components: Planner, Retriever, Executor, Verifier, Reflection, Harness.
Failure modes: retries, timeout, cancellation, dependency failure, duplicate execution, replay, partial execution, resume. Planner: empty/impossible/cyclic/huge plan. Verifier: unsupported assertions, contradictory evidence, missing evidence. Reflection: revise/finalize/max iterations/confidence threshold.

Deliverable: `docs/14-testing/RUNTIME_RELIABILITY.md` + `tests/runtime/`.

### [ ] Issue #10 — B2: Compute Runtime Validation
https://github.com/Aparnap2/Finsight/issues/10

Import (malformed sheet, empty, duplicate header, unicode, emojis, 1M rows) → Validate (wrong types, schema drift, duplicates, overflow) → Compute (div-by-zero, NaN, infinite, overflow, memory pressure) → Export (csv, excel, parquet, markdown).

Deliverable: `docs/14-testing/COMPUTE_RUNTIME.md`.

### [ ] Issue #11 — B3: Database Integrity
https://github.com/Aparnap2/Finsight/issues/11

**Needs docker (one container at a time: postgres:17-alpine).**
Positive: CRUD/RLS/triggers per tenant. Negative: FK, CHECK (negative amount), UNIQUE, RLS cross-tenant, trigger guards, NOT NULL/type — DB must reject.

Deliverable: `docs/14-testing/DATABASE_INTEGRITY.md` + `tests/integration/test_database/`.

---

## Workstream C — AI Reliability (issues #12 #13 #14)

### [ ] Issue #12 — C1: LLM Runtime Reliability
https://github.com/Aparnap2/Finsight/issues/12

16 failure modes: Malformed JSON, Wrong schema, Timeout, 429, 500, Provider unavailable, Hallucinated field, Prompt injection, Indirect prompt injection, Jailbreak, Tool failure, Context overflow, Token truncation, Partial output, Empty output, Wrong language. Plus structured-output repair + provider failover (LiteLLM). **Mocked — no live keys.**

Deliverable: `docs/14-testing/LLM_RELIABILITY.md` + `tests/ai/`.

### [ ] Issue #13 — C2: Prompt Harness Validation
https://github.com/Aparnap2/Finsight/issues/13

Grounding, evidence coverage, unsupported assertions (rejected), retrieval precision, reflection quality, action quality, policy compliance.

Deliverable: `docs/14-testing/PROMPT_HARNESS.md` + `tests/ai/test_prompt_harness/`.

### [ ] Issue #14 — C3: Golden Dataset Evaluation
https://github.com/Aparnap2/Finsight/issues/14

**100 scenarios** in 10 groups: Revenue, Expenses, Cash Flow, Forecast, Budget, Audit, Compliance, Risk, Fraud, Data Quality. Each: spreadsheet + expected assertions/evidence/recommendations/actions/confidence/metrics/runtime path.

Deliverable: `evaluation/golden/` + `docs/14-testing/GOLDEN_DATASETS.md` + `tests/golden/`.

---

## Workstream D — Business Validation (issues #15 #16)

### [ ] Issue #15 — D1: Business Workflow Validation
https://github.com/Aparnap2/Finsight/issues/15

6 workflows end-to-end: Record-to-Report, Procure-to-Pay, Budget Cycle, Variance Analysis, Forecast Update, Month-End Close.

Deliverable: `docs/14-testing/BUSINESS_VALIDATION.md` + `tests/e2e/`.

### [ ] Issue #16 — D2: Business Capability Validation
https://github.com/Aparnap2/Finsight/issues/16

7 capabilities: Budgeting, Forecasting, Reporting, Risk, Recommendation, Analysis, Audit. Each with inputs/outputs/metrics/tests.

Deliverable: `docs/14-testing/BUSINESS_CAPABILITIES.md`.

---

## Workstream E — Production Readiness (issues #17 #18 #19 #20)

### [ ] Issue #17 — E1: Security Verification
https://github.com/Aparnap2/Finsight/issues/17

RLS, RBAC, ABAC, SQL injection, Prompt injection, CSV injection, Excel formula injection, SSRF, Path traversal, Rate limit, Replay attack. Positive = allowed, negative = blocked.

Deliverable: `docs/14-testing/SECURITY.md` + `tests/security/`.

### [ ] Issue #18 — E2: Performance Verification
https://github.com/Aparnap2/Finsight/issues/18

Sizes: 10 / 100 / 1k / 10k / 100k / 1M rows. Metrics: CPU, memory, latency, cache, throughput.

Deliverable: `docs/14-testing/PERFORMANCE.md` + `tests/benchmarks/` + `evaluation/benchmark/`.

### [ ] Issue #19 — E3: Chaos Engineering
https://github.com/Aparnap2/Finsight/issues/19

Kill: PostgreSQL, Redis, Python Runtime, LiteLLM, Google Sheets, Mockoon + network timeout, expired OAuth. Verify graceful degradation / retry / fallback / audit. **One container at a time.**

Deliverable: `docs/14-testing/CHAOS.md` + `tests/chaos/`.

### [ ] Issue #20 — E4: Release Readiness & Documentation
https://github.com/Aparnap2/Finsight/issues/20

Checklists (Engineering/Business/AI), full docs tree, **traceability matrix** (PRD → code → tests → golden dataset → evaluation → evidence).

Deliverables in `docs/14-testing/`:
- [ ] TEST_STRATEGY.md
- [ ] TRACEABILITY_MATRIX.md
- [ ] TEST_MATRIX.md
- [ ] GOLDEN_DATASETS.md
- [ ] PERFORMANCE.md
- [ ] SECURITY.md
- [ ] CHAOS.md
- [ ] RELEASE_READINESS.md
- [ ] BUSINESS_VALIDATION.md
- [ ] PRODUCTION_CHECKLIST.md

---

## Target test directory layout

```
tests/
├── unit/
├── property/
├── fuzz/
├── integration/
├── contract/
├── runtime/
├── ai/
├── security/
├── performance/
├── chaos/
├── e2e/
├── golden/
└── benchmarks/

evaluation/
├── metrics/
├── report_cards/
├── regression/
├── benchmark/
└── dashboards/

docs/14-testing/   (10 docs above)
```

---

## Git / PR workflow

1. Work on `feat/verification-readiness` (created off PR #4's branch state).
2. Commit per issue (Conventional Commits: `test:`, `chore:`, `fix:`).
3. PR #4 (`feat/ml-reasoning-runtime` → main) is currently MERGEABLE/CLEAN — rebase onto merged main already done, force-pushed. Do NOT break it.
4. When verification phase complete: final PR for `feat/verification-readiness`.
5. Close issues as they complete with evidence comments.
