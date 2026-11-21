# FinSight — canonical product specification

This is the single normative description of what FinSight is. Every other
product document in this repository is either an implementation note for this
scope or archived history (see `docs/archive/README.md`).

If code and this document disagree, that is a defect in one of them. Fix the
disagreement; do not add a third description.

---

## 1. Identity

**FinSight is a payment-reconciliation application for B2B finance teams.**

Three independent records describe the same money: what was invoiced, what the
payment processor charged, and what actually landed in the bank. FinSight
reconciles those three deterministically, explains every difference it can
prove, escalates what it cannot, and never invents a match.

One sentence: *invoice → charge → deposit, reconciled to the cent, with an
auditable reason for every difference.*

FinSight is **not** an FP&A platform, a commentary generator, a generic finance
agent framework, or a multi-agent product. The FP&A application that still runs
from `apps/` is a previous product generation being replaced by the
reconciliation surface; it is not the product.

---

## 2. Users and job

| User | Job |
|---|---|
| Payments / AR analyst | "Which invoices are actually settled, and which deposits do not add up?" |
| Finance manager | "Show me why this deposit is 29.00 short and what evidence supports that." |
| Reviewer / auditor | "Prove the number came from the source records and the engine, not from a model." |

The demo user is a single analyst at a B2B company that invoices in one
currency, collects through Stripe, and reconciles against a bank statement.

---

## 3. Scope

### In scope (P0)

1. **CSV ingestion** of three sources: invoice register, processor export,
   bank statement.
2. **Normalization** into typed records (`PaymentRecord`, `BankDepositRecord`)
   with Decimal money and no float.
3. **Deterministic three-source reconciliation**: invoice ↔ charge,
   charge ↔ deposit, and the derived invoice ↔ deposit comparison.
4. **Payout allocation**: one deposit → many charges, including fees, refunds,
   partial payments, duplicates, and ambiguity.
5. **Exception engine**: typed codes and reasons for every non-match.
6. **Persistence**: sources, runs, results, exceptions, and decisions survive a
   restart in PostgreSQL.
7. **HTTP API**: import, run, read results, read exceptions.
8. **Operator UI**: perform the whole workflow in a browser; no CLI or SQL.
9. **Evidence-grounded AI investigation**: the model reads stored evidence and
   writes an explanation. It never computes or changes a financial result.
10. **CSV report export** of a run.

### Explicitly out of scope

- Tally, Zoho Books, QuickBooks, or any accounting-system integration.
- GST/TDS or other tax computation.
- OCR or document extraction; inputs are structured CSV.
- Purchase orders, GRNs, or three-way matching beyond invoice/charge/deposit.
- GL categorization, journal posting, or autonomous money movement.
- A generic multi-agent framework, plugin platform, or workflow builder.
- Kafka, Redis, or Kubernetes without a demonstrated requirement.
- Replacing the current UI framework for technology aesthetics.

Anything on this list is a **new product decision**, not a refactor. It needs an
explicit request and a new spec entry.

---

## 4. The workflow

```
CSV: invoices ─┐
CSV: Stripe   ─┼─> normalize ─> reconcile (deterministic) ─> results + exceptions
CSV: bank     ─┘                        │                          │
                                        │                          ├─> operator UI
                                        │                          ├─> AI explanation
                                        │                          │   (evidence only)
                                        └─ fingerprint + evidence  └─> CSV export
```

1. **Import** three files for one period and tenant.
2. **Run** reconciliation. The run is deterministic: same inputs, same
   fingerprints, same result.
3. **Inspect** each scenario: `reconciled`, `exception`, `pending_evidence`, or
   `ambiguous`.
4. **Investigate** an exception: read the stored evidence, request an
   explanation, record a human decision.
5. **Export** the run as CSV.

The current implementation stops after step 3 and does it from the CLI. Steps
1, 2, 4, and 5 are the build target; see §5.

---

## 5. Implementation status

Status is measured against the code, not the intention. Keep this table honest:
a row moves to *Implemented* only when a test proves it.

| Capability | Status | Evidence |
|---|---|---|
| Deterministic two-leg reconciliation | **Implemented** | `finance/reconciliation/reconciler.py`, `matcher.py`, 241 unit tests |
| Payout allocation (fees, refunds, partials, duplicates, ambiguity) | **Implemented** | `finance/reconciliation/allocation.py` |
| Three-source composition (invoice + processor + bank) | **Implemented** | `finance/reconciliation/statement_workflow.py` |
| Operator report: Markdown + JSON + evidence record | **Implemented** | `python -m finance.reconciliation.operator_report` |
| Byte-reproducible golden evidence | **Implemented** | `docs/evidence/operator-run/`, `tests/unit/reconciliation/test_golden_evidence.py` |
| Runtime boundary manifest (what must survive cleanup) | **Implemented** | `docs/release/reconciliation-boundary.json` |
| CSV ingestion of the three sources | **Not implemented** | inputs are JSON fixtures / programmatic records |
| HTTP API for reconciliation | **Not implemented** | zero reconciliation routes in `apps/api` |
| Persistence of sources, runs, results, exceptions | **Not implemented** | no reconciliation tables in `database/migrations` |
| Operator UI for reconciliation | **Not implemented** | `/gui` serves the FP&A console, not reconciliation |
| Exception resolution and human decision record | **Not implemented** | — |
| Evidence-grounded AI investigation of exceptions | **Not implemented** | — |
| CSV report export | **Not implemented** | — |

The frozen behaviour is the nine-scenario triangle fixture
(`tests/fixtures/reconciliation/triangle/`) and the committed evidence bundle.
Everything above the engine is additive: it must call the engine, never
reimplement or adjust it.

---

## 6. Architecture

### Layers (one dependency direction)

```
apps/      HTTP + UI         may import everything below
  ↑
agents/    AI orchestration  may import finance/ and shared/
  ↑
finance/   domain + engine   may import shared/
  ↑
shared/    cross-cutting     imports nothing first-party
```

Reverse imports fail review. `shared/` importing `finance/` is a bug, not a
convenience.

### Target runtime

```
Browser
  │
  ├─ NiceGUI operator console  (apps/api/operator_console.py, mounted at /gui)
  │
  └─ FastAPI reconciliation API  (apps/api/, new routes)
        │
        ├─ finance/reconciliation  ← the frozen deterministic engine
        │     normalize → match → allocate → classify → fingerprint
        │
        ├─ agents/                 ← explanation only, reads stored evidence
        │
        └─ PostgreSQL
              sources · runs · results · exceptions · decisions
```

Deployment is Docker Compose: one API container, one PostgreSQL container. The
UI is served by the same application. There is no separate frontend service.

### What each layer owns

| Layer | Owns | Must never do |
|---|---|---|
| `finance/reconciliation` | every number: matching, allocation, fees, refunds, tolerances, outcome codes | call a model, read a clock, use float, touch the network |
| `agents/` | turning stored evidence into prose | compute an amount, choose a match, alter a result |
| `apps/` | HTTP contracts, persistence, rendering, export | contain reconciliation logic |
| `shared/` | config, models, logging, LLM client | import a layer above it |

---

## 7. Determinism boundary (non-negotiable)

The engine is the only source of financial truth.

- **Money is `decimal.Decimal`.** Never `float`, never a JSON number parsed as
  float, never a formatted string re-parsed.
- **No clock, randomness, network, or model call** on the reconciliation path.
- **No invented matches.** Linking is exact on currency and amount, with
  declared tolerances and a declared date window. Ties break by a documented,
  stable rule.
- **Ambiguity escalates.** If two allocations both reproduce a deposit, the
  result is `REQUIRES_HUMAN` with every candidate reported. The engine does not
  pick one.
- **Every result is fingerprinted** from canonical JSON, so a rerun is
  comparable.
- **AI explains, never decides.** A model may read evidence and write prose. It
  may not produce, modify, or override an amount, a match, or a status. If an
  explanation needs a number, that number comes from the run record.
- **No autonomous postings.** FinSight never writes to a ledger or moves money.

Breaking any of these requires an explicit product decision and a spec change —
not a refactor under task pressure.

---

## 8. Repository map

| Path | Contents |
|---|---|
| `finance/reconciliation/` | the engine and the three-source workflow (frozen) |
| `finance/` (other) | FP&A domain logic from the previous generation; see §5 |
| `agents/` | LangGraph orchestration from the previous generation; the reconciliation investigation agent is the intended survivor |
| `apps/api/` | FastAPI application, the NiceGUI console at `/gui`, schemas |
| `shared/` | config, base models, LLM client, validators |
| `database/migrations/` | SQL migrations, including row-level security |
| `tests/unit/reconciliation/` | engine, workflow, operator report, golden evidence, boundary |
| `tests/fixtures/reconciliation/triangle/` | the nine frozen scenarios |
| `docs/evidence/operator-run/` | committed, byte-reproducible report bundle |
| `docs/release/` | local deployment and the runtime boundary |
| `docs/archive/` | historical product documents, kept for reference only |

`docs/release/RECONCILIATION_BOUNDARY.md` records which modules must survive
repository cleanup, computed rather than asserted.

---

## 9. Verification

```bash
# the product demonstration
python -m finance.reconciliation.operator_report        # exit 0, Verdict: PASS

# gates
ruff check .
ruff format --check .
python scripts/mypy_baseline_check.py --baseline scripts/mypy-baseline.txt --report /tmp/mypy.txt
pytest tests/unit tests/contract

# runtime boundary
python scripts/reconciliation_boundary.py --check

# deployment (see docs/release/LOCAL_DEPLOYMENT.md for the full procedure)
docker compose -f docker-compose.staging.yml up -d --build   # API + PostgreSQL
docker compose -f docker-compose.test.yml up --exit-code-from test
```

Current baseline (recorded in `docs/release/RECONCILIATION_BOUNDARY.md`):
241 reconciliation tests, 3336 fast-suite tests, 206 compose integration tests,
mypy baseline 1137 with zero new errors.

A green CI run is **not** evidence the product works end to end. The evidence is
the operator demo, the byte-reproducible bundle, and — once built — the browser
workflow.
