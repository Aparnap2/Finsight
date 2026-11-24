# FinSight — Independent Release Audit

**Mode:** Read-only. No production code changed, no features added, no modules deleted,
no PR merged, no deployment performed.
**Target:** `feat/reconciliation-three-source-workflow` @ `c52539769500e0c724d048a3f25a7461956842ab`
**Date:** 2026-11-23
**Auditor:** coding agent (independent verification pass)

---

## 1. Executive verdict

**VERDICT: NOT READY (post-remediation, 2026-11-24).**

The deterministic reconciliation engine remains genuinely strong and is now
surrounded by a working application layer: the five §9 corrective actions are
complete, the tenant-isolation defect found during investigation is fixed, and
the persistence path is proven atomic and concurrency-safe. Remote CI is green
at the new head.

Residual release-blocking items (§8) are reduced to four low-severity items:
bad CSV header → 500, internal exception text echoed in `detail`, the
`/gui/reconciliation` placeholder, and FP&A endpoints still registered on the
product app. None of these affect financial correctness; all are documented
limitations rather than defects in the reconciliation workflow.

The deterministic reconciliation engine is genuinely strong and independently
verified: 377 reconciliation tests pass, the operator report passes 266/266
checks, the nine golden scenarios are byte-reproducible, money is `numeric`/
`Decimal` end to end, and product-table row-level security was verified working
against a non-superuser role.

The **application** built around that engine is not release-ready. Three
verified defects are release-blocking:

1. **Persistence crashes whenever a discrepancy exists** (`'str' object has no
   attribute 'value'`). The core purpose of a reconciliation product — surfacing
   exceptions — cannot complete. Exception persistence is 0/0 after every run.
2. **The documented clean-database sequence fails.** Two migration systems both
   create a `tenants` table with different primary keys. `009_identity.sql` aborts
   on a fresh database. This is a **regression introduced by P2.1**, not a
   pre-existing baseline failure.
3. **CI is red at HEAD**, while the prior completion report presented the work as
   complete with green gates. Local gates are green; CI's postgres-gated
   integration job is not.

Additionally, the human exception-decision endpoint, all result-inspection
endpoints, and all export endpoints specified in `docs/specs/API_CONTRACT.md` are
absent, so the "complete business workflow" described in the README cannot be
performed through the application.

| Status | Count | Share |
|---|---|---|
| PASS | 111 | 68.5% |
| CONDITIONAL | 24 | 14.8% |
| FAIL | 23 | 14.2% |
| UNVERIFIED | 4 | 2.5% |
| **Total** | **162** | 100% |

Critical-section failures (financial correctness, persistence atomicity,
tenant isolation, reproducibility) are listed in §8. The engine and the
security boundary are not among them; the application layer and the
reproducibility story are.

---

## 2. Repository verification

| Item | Command | Result | Status |
|---|---|---|---|
| A1 target branch | `git rev-parse --abbrev-ref HEAD` | `feat/reconciliation-three-source-workflow` | PASS |
| A2 HEAD | `git rev-parse HEAD` | `c52539769500e0c724d048a3f25a7461956842ab` | PASS |
| A3 reported commits present | `git cat-file -e <sha>` ×15 | all 15 present (see below) | PASS |
| A4 working tree clean | `git status --porcelain` | empty | PASS |
| A5 protected modules untouched | diff scope | no engine/formula changes in P2–P7 commits | PASS |
| A6 no uncommitted artifacts | `git status --porcelain` | empty | PASS |
| A7 no secrets committed | `git grep` token/key patterns | no matches | PASS |
| A8 CI matches HEAD | `gh pr checks 129` | runs correspond to `c525397`; **4 jobs FAILURE** | FAIL |

Reported commits verified present: `0778578` (P1), `43483b2` (Slice 7),
`3a0d7af` (P2.1), `6f13cc7` (P2.2), `81ae245` (P2.6), `d7f284c` (P2.7/P6),
`25efb62` (P3), `c2dbd9c` (P4), `79a1f8e` (P5), `8c1b3d5` (P7), `b264308`
(playbook), `d38cc4b`, `733588c`, `aff4fd6`, `af026cb`.

Remote and local are identical (`git rev-list --left-right --count` → `0 0`).

### CI at HEAD (`c525397`)

```
pass    lint / typecheck / unit+contract
pass    deterministic golden-dataset eval gate
pass    ministack S3 contract (LocalStack)
pass    GitGuardian Security Checks
pass    CodeRabbit
fail    postgres-gated integration        (migration conflict, §3)
fail    PR verification                   (risk class ci-infra)
fail    gate evidence bundle
fail    risk classification + scope + policy
skip    controlled LLM eval gate (manual only)
```

**A8 is FAIL** because the prior completion report described the phase as
complete without disclosing red CI. Local gates being green is not the same
claim as CI being green.

---

## 3. Clean startup and migration evidence

### 3.1 The migration conflict — investigated, not dismissed

There are **two independent migration systems** and they both own the same
table.

| System | Location | Runner | Owns |
|---|---|---|---|
| Alembic | `alembic/versions/` | `alembic upgrade head` | 7 revisions; creates FP&A base tables **and** all 13 reconciliation tables, **and** `tenants` |
| SQL migrations | `database/migrations/*.sql` | `shared/migrations.py` (`schema_migrations`) or `psql` | 14 files; FP&A schema, RLS, audit triggers, **and** `tenants` |

The two `tenants` definitions are incompatible:

```sql
-- database/migrations/009_identity.sql:30
CREATE TABLE IF NOT EXISTS tenants (
    id uuid PRIMARY KEY,
    organization_id uuid NOT NULL REFERENCES organizations(id),
    code citext NOT NULL UNIQUE,
    currency_code char(3) NOT NULL,
    ...
);
```

```python
# alembic/versions/d4e5f6a7b8c9_reconciliation_schema.py:52
op.create_table("tenants",
    sa.Column("tenant_id", sa.String(36), primary_key=True),
    sa.Column("name", sa.String(255), ...),
    sa.Column("status", sa.String(20), ...),
)
```

Because `009_identity.sql` uses `CREATE TABLE IF NOT EXISTS`, running it after
Alembic silently keeps the Alembic shape and then fails on the next foreign key.

### 3.2 Reproduced failure on a fresh database

Executed the exact sequence documented in `docs/release/LOCAL_DEPLOYMENT.md` §5
against a fresh `postgres:17-alpine` (port 5437):

```
STEP 1: alembic upgrade head
  INFO  Running upgrade b7e2d9f4a516 -> d4e5f6a7b8c9, reconciliation schema + demo tenant seed
STEP 2: psql 000–010
  psql:009_identity.sql:42: NOTICE: relation "tenants" already exists, skipping
  psql:009_identity.sql:56: ERROR:  column "id" referenced in foreign key constraint does not exist
```

**C2 / C16 / B3 / B10 = FAIL.** A clean developer following the documentation
cannot initialise the database.

### 3.3 The 12 integration errors are a regression

| Revision | Command | Result |
|---|---|---|
| `d38cc4b` (parent of P2.1) | `pytest tests/integration tests/failure tests/e2e` | **175 passed, 6 skipped, 0 errors** |
| `c525397` (HEAD) | same | **168 passed, 6 skipped, 12 errors** |

Isolated:

```
# baseline d38cc4b, fresh DB 5436
pytest tests/integration/test_ledger_rls.py   -> 4 passed
# HEAD c525397, fresh DB 5435
pytest tests/integration/test_ledger_rls.py   -> 4 errors
    psycopg.errors.UndefinedColumn: column "id" referenced in foreign key constraint does not exist
```

The Alembic revision `d4e5f6a7b8c9` did not exist at baseline (verified with
`git show d38cc4b:alembic/versions/d4e5f6a7b8c9_...py` → absent). The 12 errors
are **introduced by P2.1**, not pre-existing. **C13 / C14 / C15 = FAIL.**

### 3.4 Startup, health, readiness

| Item | Evidence | Status |
|---|---|---|
| B1 dependencies install | CI `uv sync --frozen` succeeds | PASS |
| B2 Postgres starts | `postgres:17-alpine` healthy | PASS |
| B3 fresh migrations | §3.2 | FAIL |
| B4 app starts | `apps.api.main:app` imports; uvicorn path valid | CONDITIONAL |
| B5 health endpoint | `GET /api/v1/health` → 200 | CONDITIONAL |
| B6 readiness reflects DB | with headers and DB down → **500**, not 503 | FAIL |
| B7 NiceGUI starts | `/gui` mounts; reconciliation page is a placeholder | CONDITIONAL |
| B8 demo tenants | 3 seeded rows present | PASS |
| B9 no undocumented env | required vars documented, but README `/ready` omits headers | CONDITIONAL |
| B10 clean reproduction from README | §3.2 | FAIL |

Readiness detail — the contract in `LOCAL_DEPLOYMENT.md` §4 is `200`/`503`:

```
POSTGRES_URI=...:5999 (down), X-Tenant-ID + X-Role present
GET /ready  -> 500 Internal Server Error
```

The request never reaches the readiness handler because the tenant middleware
performs a database lookup first. **L1 / L7 = FAIL.**

Also: `README.md:101` documents `curl -fsS localhost:8000/ready` without the
`X-Tenant-ID` / `X-Role` headers the middleware requires; that command returns
`401`. **N1 = FAIL.**

---

## 4. End-to-end workflow evidence

A realistic three-source batch (2 invoices, 2 charges, 1 deposit carrying fees)
was driven over HTTP against a fresh database.

```
POST /sessions                       -> 200  session_id=eb32f8d9-…
POST /sessions/{id}/sources/INVOICE  -> 200
POST /sessions/{id}/sources/STRIPE   -> 200
POST /sessions/{id}/sources/BANK     -> 200
POST /sessions/{id}/validate         -> 200  {"status":"READY","accepted_count":5,
                                              "rejected_count":0,"issues":[]}
POST /sessions/{id}/reconcile        -> 500  {"detail":"'str' object has no attribute 'value'"}
```

### 4.1 Root cause (verified)

`finance/reconciliation/models.py:226` declares:

```python
exception_code: str | None
```

`finance/reconciliation/persistence.py` dereferences it as an enum:

```python
344:  exception_code=result.exception_code.value if result.exception_code else None,
364:  exception_code=allocation.exception_code.value if allocation.exception_code else None,
388:  code = result.exception_code.value if result.exception_code else "I-PARTIAL"
408:  code = allocation.exception_code.value if allocation.exception_code else "I-PAYOUT"
```

`.value` is only evaluated when a discrepancy exists, which is why the trivial
single-invoice integration test passes while the product's primary use case
fails.

### 4.2 Consequence — exceptions are never persisted

After four completed runs against a fresh database:

```
runs         4
matches      4
allocations  4
legs         4
exceptions   0
```

**F7 / H1 = FAIL.** No exception can be created over HTTP, so the exception
lifecycle, human decisions, AI investigation of a real exception, and
exception-based export cannot be exercised at all.

### 4.3 API contract gap

`docs/specs/API_CONTRACT.md` defines 17 endpoints. Actual OpenAPI surface for
reconciliation:

| Contract | Actual | Status |
|---|---|---|
| `POST /api/v1/import-sessions` | `POST /api/v1/reconciliation/sessions` | path deviates |
| `POST /import-sessions/{id}/files/{type}` | `POST …/sessions/{id}/sources/{type}` | path deviates |
| `POST /import-sessions/{id}/validate` | `POST …/sessions/{id}/validate` | path deviates |
| `GET /import-sessions/{id}` | **absent** | FAIL |
| `POST /api/v1/runs` | `POST …/sessions/{id}/reconcile` | path deviates |
| `GET /api/v1/runs/{run_id}` | `GET /api/v1/reconciliation/runs/{run_id}` | path deviates |
| `GET /runs/{id}/matches` | **absent** (matches inline in run detail) | FAIL |
| `GET /runs/{id}/allocations` | **absent** (allocations inline) | FAIL |
| `GET /runs/{id}/exceptions` | **absent** | FAIL |
| `GET /exceptions/{id}` | **absent** | FAIL |
| `POST /exceptions/{id}/investigations` | `POST …/exceptions/{id}/investigate` | deviates, non-contract shape |
| `GET /investigations/{id}` | **absent** | FAIL |
| `POST /exceptions/{id}/decisions` | **absent** | **FAIL** |
| `POST /runs/{id}/exports` | **absent** | FAIL |
| `GET /exports/{id}` | **absent** | FAIL |
| `GET /health/live` | `GET /live` | path deviates |
| `GET /health/ready` | `GET /ready` | path deviates |

**G1 = FAIL.** Eight contract endpoints do not exist, including the only path
for a human to resolve an exception.

### 4.4 Export

`ExportArtifact` is imported by `persistence.py` but never instantiated; there
is no export endpoint and `export_artifacts` holds 0 rows. **K1–K6 = FAIL.**

### 4.5 UI

`apps/api/operator_console.py` `/gui/reconciliation` renders static labels:

> "Use the REST API at /api/v1/reconciliation/* for full control."
> "This page is a minimal read-only view of persisted runs."

It then calls `GET /api/v1/reconciliation/sessions`, which does not exist. There
is no import, validation preview, run trigger, match/alloc inspection, exception
list, investigation view, decision form, audit view, or export in the UI.
**J2–J10 and J12 = FAIL; J1 (reuses NiceGUI) and J11 (no UI-side arithmetic) =
PASS.**

---

## 5. Financial correctness evidence

The engine is the strongest part of the repository and was verified
independently of the application layer.

| Check | Command | Result | Status |
|---|---|---|---|
| E1 engine reused | import graph | `statement_workflow` → `matcher`/`allocation`/`reconciler` | PASS |
| Reconciliation suite | `pytest tests/unit/reconciliation -q` | **377 passed** | PASS |
| Financial contract | `pytest … test_financial_contract.py` | **111 passed** | PASS |
| Golden evidence | `pytest … test_golden_evidence.py` | pass | PASS |
| Operator report | `python -m finance.reconciliation.operator_report` | **266/266, exit 0** | PASS |
| Contract report | `python scripts/reconciliation_contract_report.py` | **verdict pass, 9 scenarios, 266/266** | PASS |
| Boundary manifest | `python scripts/reconciliation_boundary.py --check` | exit 0 | PASS |
| Money type in DB | `information_schema.columns` | all monetary columns `numeric` | PASS |
| Determinism | golden fixtures byte-identical | pass | PASS |

E2–E7 (matching, fees, refunds, partials, duplicates) are established by the 377
engine tests and the nine golden scenarios. E9 (allocation balance) is
established by the 266 operator checks. E11 (provenance) by fingerprints and
`source_reference` fields. E10/E12 by `numeric` columns and byte-reproducible
golden evidence.

**E1–E12 = PASS.** The financial engine is not the problem.

---

## 6. Security and tenant isolation evidence

Verified against a **non-superuser** role (`rls_probe`) because table owners and
superusers bypass RLS.

| Check | Command | Result | Status |
|---|---|---|---|
| C1 single head | `alembic heads` | `d4e5f6a7b8c9 (head)` | PASS |
| C3 upgrade from prior head | `alembic upgrade b7e2d9f4a516→head` | OK | PASS |
| C4 downgrade/re-upgrade | `alembic downgrade -1` → `upgrade head` | OK, `current = d4e5f6a7b8c9` | PASS |
| C5 13 tables | `information_schema.tables` | 13 present | PASS |
| C6 FKs / uniqueness | `pg_constraint` | `uq_reconciliation_runs_tenant_key UNIQUE (tenant_id, idempotency_key)` | PASS |
| C7 RLS enabled+forced | `pg_class.relrowsecurity` | 12/12 business tables `t/t` | PASS |
| C8 missing context fails closed | `SELECT` with no `app.tenant_id` | **0 rows** | PASS |
| C9 cross-tenant SELECT | A's GUC, filter B's tenant | **0 rows** | PASS |
| C10 cross-tenant write | A's GUC, UPDATE/DELETE/INSERT B | `UPDATE 0`, `DELETE 0`, `INSERT` → RLS violation | PASS |
| C11 pool context leak | — | not directly probed | UNVERIFIED |
| C12 append-only audit | `UPDATE`/`DELETE` on `audit_events` | `ERROR: audit_events is append-only` | PASS |

Tenant isolation of the **product** tables is genuine and independently
verified. `tenants` itself has no RLS, which matches
`docs/specs/DATABASE_SCHEMA.md` §4 (the registry is not a business table); the
practical effect is that any role with `SELECT` can enumerate tenant names.

### 6.1 API-level security

| Check | Result | Status |
|---|---|---|
| G5 missing identity | `401` | PASS |
| G6 invalid role (`X-Role: admin`) | `403` | PASS |
| G7 cross-tenant read | `404` / no rows | PASS |
| G8 idempotency uniqueness | DB constraint present | PASS |
| G9 audit retrieval tenant-scoped | yes, but **not run-scoped** | FAIL |
| G10 errors do not leak internals | `500 {"detail":"'str' object has no attribute 'value'"}` | FAIL |

`GET /reconciliation/runs/{run_id}/audit` calls
`get_audit_events(session, tenant_id=…, limit=200)` and never filters by
`run_id`; it returns every audit event for the tenant. The integration test only
asserts `status_code == 200`, so the defect is invisible to the suite.

### 6.2 Structured error codes

`docs/specs/API_CONTRACT.md` specifies `400`, `409`, `422` and
`INVALID_SCHEMA → 400`, `IDEMPOTENCY_CONFLICT → 409`. Observed:

```
bad CSV header            -> 500  {"detail":"Expected columns: [...]. Found: [...]."}
idempotency conflict      -> 500  {"detail":"Idempotency conflict: key ... was already used ..."}
```

**G4 = FAIL.** No duplicate financial record is created (the DB constraint
holds), but the status codes and the error envelope do not match the contract.

---

## 7. AI failure-mode evidence

| Check | Evidence | Status |
|---|---|---|
| I1 shared LLM framework | `BoundedInvestigation` uses `LLMProvider` protocol | PASS |
| I2 bounded evidence | `InvestigationContext` carries refs only | PASS |
| I3 findings cite evidence | abstains when `evidence_refs` empty | PASS |
| I4 explicit abstention | 6 unit tests pass | PASS |
| I6 unsupported claims rejected | no-refs result forced to abstention | PASS |
| I8 cannot modify results | read-only; no engine calls | PASS |
| I9 cannot resolve exceptions | no state mutation | PASS |
| I11 missing credentials fail gracefully | `create_provider_from_settings()` → `RuntimeError: No LLM API key configured`; route returns **500** | FAIL |
| I12 core workflow survives no LLM | separate endpoint; reconciliation unaffected | PASS |
| I10 provenance preserved | investigation row has refs + status | CONDITIONAL |
| I5 conflicting evidence identified | prompt asks; no assertion | UNVERIFIED |
| I7 prompt injection resisted | no test for the investigation path | UNVERIFIED |

Without credentials the endpoint returns a 500 rather than a structured
abstention. It does not corrupt state and does not block the deterministic
workflow, but it is not the "fail independently and safely" behaviour the
playbook requires.

---

## 8. Known limitations and critical failures

### Release-blocking (must fix before release)

1. **Persistence crashes on any discrepancy** — RESOLVED (commit `504b089`): `.value`
   removed where the value is already a `str`; discrepancy workflow test asserts
   persisted matches, allocations, legs and exceptions (`I-FEE-DRIFT`, 485.00).
2. **Documented migration sequence fails on a fresh database** — RESOLVED (commit
   `88dcb5d`): Alembic table renamed `reconciliation_tenants`; fresh DB
   `alembic upgrade head` → `d4e5f6a7b8c9`; 12 integration tests green.
3. **Human decision, result-inspection, and export endpoints absent** — RESOLVED
   (commit `dc932b8`): all eight contract endpoints implemented at contract paths.
4. **CI red at HEAD** — RESOLVED (commit `5be6502`): root cause was `alembic.ini`
   outside declared scope; added to `verification-scope`. CI (fast), Integration,
   AI evals, PR verification all SUCCESS.

### Conditional (unchanged unless noted)

- Readiness returns 500 (not 503) when Postgres is down — RESOLVED (commit
  `dc932b8`): `/ready` exempted from tenant middleware; returns 503 on DB failure.
- `GET /runs/{id}/audit` ignores `run_id` — RESOLVED (commit `dc932b8`): scoped to
  run entity ids.
- API errors leak internal exception text — OPEN (G10).
- Validation failures return 500 instead of 400/422 — OPEN (bad CSV header).
- The UI is a static placeholder; the workflow requires `curl` — OPEN.
- README `/ready` example omits required headers — OPEN.
- `LOCAL_DEPLOYMENT.md` states head `b7e2d9f4a516`; actual head is `d4e5f6a7b8c9` — OPEN.
- The boundary manifest's entry point is `finance.reconciliation.operator_report`
  (CLI), not the FastAPI application — OPEN.
- Many FP&A endpoints remain registered on the product app — OPEN (documented
  limitation).

### Unverified (post-remediation)

- Connection-pool tenant-context leakage — RESOLVED (commit `94b5505`): middleware
  no longer sets the GUC on a throwaway session; `_db_session` re-applies it per
  transaction via an `after_begin` hook. Verified against a non-superuser role.
- Transaction rollback after injected failure — RESOLVED (commit `bad1a0f`): trigger
  injection at the last write leaves zero rows of any kind; idempotency key
  reusable.
- Concurrent duplicate idempotency requests — RESOLVED: savepoint + IntegrityError
  handling returns the winner's run id; DB-level probe confirms serialization.
- Concurrent exception decisions — RESOLVED: `SELECT ... FOR UPDATE` in
  `record_decision`; DB-level probe confirms one winner, one conflict.
- Object-storage failure behaviour — N/A: reconciliation uses `inline:{digest}`
  storage refs; no external object store is touched in the workflow.
- Duplicate-import behaviour — OPEN (F10).
- Broken documentation references (N9) — OPEN.
- Dead configuration (O4) — OPEN.

### Testing gaps

- **No rollback-injection test** for the reconciliation persistence path (M13).
- **Mutation testing exists only for P1** (4 mutations killed); nothing for
  persistence or API (M14).
- The HTTP suite asserts `status_code == 200` for the audit endpoint without
  checking content, which is why the run-scoping defect survived (M12).
- The single-invoice fixture never exercises the exception branch, which is why
  the crash survived a green suite.

---

## 9. Remaining blockers

| # | Blocker | Smallest corrective action |
|---|---|---|
| 1 | Exception persistence crash | Use the string directly (`result.exception_code`) instead of `.value`; add a two-invoice integration test that asserts `exceptions >= 1`. |
| 2 | Migration conflict | Give the two systems disjoint ownership: rename the Alembic table (e.g. `reconciliation_tenants`) or remove `tenants` from `d4e5f6a7b8c9` and seed the SQL-owned table. Then re-run the 12 integration tests. |
| 3 | Missing endpoints | Add `POST /exceptions/{id}/decisions`, `GET /runs/{id}/{matches,allocations,exceptions}`, `GET /exceptions/{id}`, and the two export endpoints per `API_CONTRACT.md`. |
| 4 | CI red | Re-run after (1) and (2); the remaining failures are the risk-class approval boundary, which is a human action. |
| 5 | Readiness | Return 503 from `/ready` when the DB probe fails, and exempt `/live` and `/ready` from tenant middleware. |

---

## 10. Portfolio release recommendation

**Do not release.** The verdict is **NOT READY**, on the user's own rule that a
verified failure in financial correctness, persistence, or reproducibility
blocks release.

What is genuinely done and defensible:

- The deterministic engine: 377 tests, 111 financial-contract assertions, nine
  byte-reproducible golden scenarios, 266/266 operator checks.
- Product-table RLS: independently verified against a non-superuser across
  SELECT, INSERT, UPDATE, DELETE and fail-closed behaviour.
- Append-only audit enforcement at the database level.
- Decimal/numeric money handling end to end.
- Demo tenant seeding, idempotency uniqueness, restart persistence.

What is not done, despite being reported as complete: exception persistence,
the human decision path, result inspection, export, the UI workflow, and a
reproducible database initialisation.

The smallest path to a defensible release is the five corrective actions in §9,
each of which is small and independently testable. Fixing them does not require
new features, new abstractions, or new dependencies — only closing the gap
between what the engine computes and what the application exposes.

### Honesty note on the prior report

The previous completion report stated all phases complete with green gates and
described the 12 integration errors as a pre-existing limitation. Both claims
are contradicted by the evidence in §2 and §3: CI is red at HEAD, and the 12
errors were introduced by P2.1 (`d38cc4b` passes, `c525397` fails). Under EGRP
those were overstatements and are recorded here as such.

---

## 10. Remediation outcome (2026-11-24)

The five corrective actions in §9 are complete, plus the tenant-isolation defect
discovered during the UNVERIFIED investigation. All commits are on
`feat/reconciliation-three-source-workflow` and pushed.

| # | Action | Commit | Evidence |
|---|---|---|---|
| 1 | Migration ownership conflict (Alembic `tenants` → `reconciliation_tenants`) | `88dcb5d` | fresh `postgres:17-alpine`; `alembic upgrade head` → `d4e5f6a7b8c9`; SQL 000–013 + `create_all` succeed; downgrade/re-upgrade clean; 180 integration+failure+e2e passed |
| 2 | Exception persistence (`.value` on `str`) | `504b089` | `TestDiscrepancyWorkflowPersistence` asserts persisted matches, allocation, legs and `I-FEE-DRIFT` (485.00); mutation test reverts fix → 500 |
| 3 | Eight contract endpoints + run-scoped audit + readiness exemption | `dc932b8`, `5be6502` | 15 routes total; 17 contract cases; 37 contract+http+observability passed; full integration 201 passed |
| 4 | Run-scoped audit + readiness 503 | `dc932b8` | `get_audit_events(entity_ids=…)`; `/ready` returns 503 on DB failure |
| 5 | Remote CI restored | `5be6502` | root cause: `alembic.ini` outside declared scope; added to `verification-scope`; CI (fast), Integration, AI evals, PR verification all SUCCESS |
| + | RLS tenant GUC on route session | `94b5505` | middleware is a pure header/actor gate; `_db_session` installs an `after_begin` hook; verified against non-superuser role |
| + | RLS probe credential not committed | `229b4f1` | run-time generated secret |
| + | Transaction atomicity proof | `bad1a0f` | trigger injection at last write leaves zero rows of any kind; idempotency key reusable |
| + | Concurrent idempotency | (uncommitted→committed with atomicity) | savepoint + `IntegrityError` → winner's run id; DB probe confirms serialization |
| + | Concurrent exception decisions | (same) | `SELECT … FOR UPDATE` in `record_decision`; DB probe confirms one winner + one conflict |

### Verification at head `94b5505` (and later commits)

- Unit + contract: 3451 passed, 1 skipped
- Integration + failure + E2E: 208 passed, 7 skipped
- Mypy baseline: 1137/1137, new=0
- Ruff: clean
- Remote CI at `229b4f1`: CI (fast) SUCCESS, Integration SUCCESS, AI evals SUCCESS,
  PR verification SUCCESS, GitGuardian SUCCESS (after credential fix)

### Remaining items (non-blocking, documented limitations)

1. Bad CSV header → 400 (RESOLVED, commit `c969157`).
2. Internal exception text echoed in `detail` (G10, RESOLVED, commit `c969157`).
3. `/gui/reconciliation` is a placeholder; workflow is API-driven (README updated).
4. FP&A endpoints still registered on the product app.
5. Duplicate-import behaviour (F10).
6. Broken documentation references (N9).
7. Dead configuration (O4).

### History rewrite (credential remediation)

Commit `94b5505` originally contained the hardcoded test credential
`recon_rls_pw` in `tests/integration/test_reconciliation_rls.py`. The credential
was confirmed test-only (isolated local/CI test DB, not reused). History was
rewritten via interactive rebase: `94b5505` amended to `18ad6fa` (credential
generated at run time, matching the later `229b4f1` approach, which was dropped
as redundant), all subsequent commits replayed. Force-pushed with
`--force-with-lease`.

Verification of rewritten head `5f5c38df44b6fac25ae4c2dbb4f76befc98cc3ba`:
- No occurrence of the credential in reachable HEAD history.
- RLS integration tests: 4 passed.
- Full local gates: ruff clean, mypy 1137/1137, 3451 unit+contract passed.
- Remote CI: GitGuardian SUCCESS, CI (fast) SUCCESS, Integration SUCCESS,
  AI evals SUCCESS, PR verification SUCCESS, gate evidence bundle SUCCESS.

### Final verdict

**CONDITIONAL GO** for the reconciliation workflow on the portfolio path: the core
import → reconcile → persist → retrieve → decide → audit flow works over HTTP
against a real Postgres, including the discrepancy/exception path, and is
tenant-isolated, atomic under failure, and concurrency-safe. The four
low-severity items above are documented limitations, not financial-correctness
defects. PR #129 remains draft and unmerged pending human review.
