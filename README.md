# FinSight

**Payment reconciliation for B2B finance teams.** Invoice, processor, and bank
records describe the same money. FinSight reconciles the three deterministically,
proves every difference it can, escalates what it cannot, and never invents a
match.

One sentence: *invoice → charge → deposit, reconciled to the cent, with an
auditable reason for every difference.*

The canonical specification is [`docs/PRODUCT.md`](docs/PRODUCT.md). This README
is the entry point; the spec is normative.

---

## What works today

The deterministic engine and the operator demonstration are complete and frozen.

| Capability | Status |
|---|---|
| Two-leg reconciliation, tolerances, outcome codes | working |
| Payout allocation: fees, refunds, partials, duplicates, ambiguity | working |
| Three-source composition: invoice + processor + bank | working |
| Operator report: Markdown + JSON + evidence record, 266 checks | working |
| Byte-reproducible golden evidence | working |
| Runtime boundary manifest | working |
| CSV ingestion (source-independent, 3 schemas) | working |
| PostgreSQL persistence (13 tables, RLS, demo seed) | working |
| REST API (sessions, sources, validate, reconcile, results, audit) | working |
| Exception lifecycle and human decisions | working |
| AI investigation (evidence-grounded, bounded) | working |
| NiceGUI reconciliation page | minimal placeholder (API is the supported workflow) |
| HTTP workflow + restart recovery | verified (5 integration tests) |

Status is tracked in [`docs/PRODUCT.md`](docs/PRODUCT.md). Limitations and deferred
capabilities are documented in [`docs/release/PRODUCTION_READINESS.md`](docs/release/PRODUCTION_READINESS.md).

## See it run

No database, network, model, or API key is involved. Money is `Decimal`
throughout; the run is deterministic.

```bash
uv sync --all-extras
uv run python -m finance.reconciliation.operator_report
```

Exit code `0`, verdict `PASS`, 266 checks, 0 failed. The report is written to
`docs/evidence/operator-run/` and is asserted byte-for-byte by
`tests/unit/reconciliation/test_golden_evidence.py`.

The nine frozen scenarios:

| Scenario | Status | Outcome |
|---|---|---|
| `s1_exact_match` | reconciled | exact agreement on all three legs |
| `s2_fee_explained` | reconciled | 29.00 processor fee explained |
| `s3_many_to_one` | reconciled | one deposit settles three charges |
| `s4a_refund_folded` | reconciled | refund folded into net |
| `s4b_partial_payment` | pending evidence | deposit covers part of a charge |
| `s5_delayed` | reconciled | deposit arrives three days late |
| `s5b_missing_deposit` | pending evidence | charge with no bank line |
| `s6_duplicate` | exception | duplicate import with a drifted amount |
| `s7_ambiguous_allocation` | ambiguous | two allocations both reproduce the deposit |

`ambiguous` is a feature: the engine reports every candidate and refuses to
choose. `pending evidence` means the run cannot decide yet — do not book it as
settled.

## Run the HTTP workflow

```bash
# 1. Start Postgres
docker compose -f docker-compose.test.yml up -d postgres

# 2. Apply migrations
alembic upgrade head

# 3. Start the API
uvicorn apps.api.main:app --host 0.0.0.0 --port 8000

# 4. Create a session and upload three sources (demo tenant: acme-corp)
curl -X POST localhost:8000/api/v1/reconciliation/sessions \\
  -H "X-Tenant-ID: 7d6f8b65-5e40-55b5-967f-69b85912dd87" \\
  -H "X-User-ID: demo" -H "X-Role: cfo" \\
  -H "Content-Type: application/json" \\
  -d '{"period_start":"2026-01-01","period_end":"2026-01-31"}'

# Upload invoice, stripe, bank CSVs, validate, reconcile, retrieve results
# See tests/integration/test_reconciliation_http.py for the full sequence.
```

The NiceGUI console is at `http://localhost:8000/gui`.

## Deploy

```bash
cp .env.example .env                     # then edit the values you need
docker compose -f docker-compose.staging.yml up -d --build
curl -fsS localhost:8000/ready           # readiness, not just liveness
```

Full procedure, health-vs-readiness semantics, and the fresh-database migration
sequence: [`docs/release/LOCAL_DEPLOYMENT.md`](docs/release/LOCAL_DEPLOYMENT.md).

## Repository map

| Path | Contents |
|---|---|
| `finance/reconciliation/` | the deterministic engine and the three-source workflow |
| `apps/api/` | FastAPI application and the NiceGUI console at `/gui` |
| `agents/` | AI orchestration (explanation only; never arithmetic) |
| `shared/` | config, models, LLM client, validators |
| `database/migrations/` | SQL migrations, including row-level security |
| `tests/unit/reconciliation/` | engine, workflow, operator report, golden evidence, boundary |
| `tests/fixtures/reconciliation/triangle/` | the nine frozen scenarios |
| `docs/PRODUCT.md` | canonical product specification |
| `docs/release/` | local deployment and the reconciliation runtime boundary |
| `docs/archive/` | historical documents from previous product generations |

Dependency direction is one way only: `shared ← finance ← agents ← apps`.
Reverse imports fail review.

## Verification gates

```bash
uv run ruff check . && uv run ruff format --check .
uv run python scripts/mypy_baseline_check.py \
  --baseline scripts/mypy-baseline.txt --report /tmp/mypy.txt
uv run python -m pytest tests/unit tests/contract -q
uv run python scripts/reconciliation_boundary.py --check
uv run python -m pytest tests/unit/reconciliation -q
```

`make test` mirrors the CI fast gate; `make test-integration` runs the
PostgreSQL-gated tier; `make ci-local` runs the fast gate locally.

Current baseline: 241 reconciliation tests, 3336 fast-suite tests, 206 compose
integration tests, mypy baseline 1137 with zero new errors. Numbers and the
deletion log live in
[`docs/release/RECONCILIATION_BOUNDARY.md`](docs/release/RECONCILIATION_BOUNDARY.md).

CI green is not proof the product works end to end. The evidence is the operator
demo, the byte-reproducible bundle, and — once built — the browser workflow.

## Contributing

[`CONTRIBUTING.md`](CONTRIBUTING.md) covers coding standards, layering rules, and
the PR checklist. Product scope is fixed by
[`docs/PRODUCT.md`](docs/PRODUCT.md): adding an integration, a framework, or a
dashboard is a product decision, not a refactor.
