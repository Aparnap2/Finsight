# ADR-008: Production State Ownership and Serverless Failure Design

**Status:** Proposed
**Date:** 2026-10-14
**Deciders:** Architecture Team
**Context:** FinSight's application controls are strong (P9/P10, UI-1, migration rehearsal), but production needs a durable execution protocol connecting committed inbound events to recoverable work. Serverless compute is disposable; financial state is not.

---

## 1. State inventory (what exists today)

| Category | Current owner | Durability | Gap |
|---|---|---|---|
| Financial situation + lifecycle | `ExceptionRow` / `ExceptionAuditRow` (`finance/exceptions/models.py`), guarded transitions | PostgreSQL, versioned | None at model level |
| Webhook inbox | `webhook_events` via `apps/api/webhooks.py` (verify → tenant → persist → ack) | PostgreSQL, deduplicated | Downstream explicitly out of scope — committed-but-never-processed window |
| Idempotency + execution ledger | `IdempotencyRow` (`shared/safety/idempotency.py`), `ExecutionRow` (`finance/execution/models.py`), guarded `Executor` | PostgreSQL **if an engine is passed** | Default is private in-memory SQLite (`idempotency.py:83`); production must never rely on the default |
| Runtime attempts | P8-02 lifecycle (`CREATED → RUNNING → SUCCEEDED \| FAILED \| EXHAUSTED`), P8-03 recovery semantics | Contract only — no chosen backend | Persistence/recovery backend unselected |
| Artifacts/evidence | S3 + DB references + hashes | Durable | Retention/purge rules unowned |
| Event dispatch (outbox) | — | **Does not exist** | Highest-risk gap: no inbox→work bridge |

## 2. Decision

**PostgreSQL is the system of record** for business decisions, approvals, idempotency, execution intents/receipts, and audit. **SQS is transport, never truth.** The workflow engine (Step Functions Standard, if AWS is the target — one orchestrator, never two) orchestrates continuation; it does not replace the ledger. Lambda memory, `/tmp`, and in-memory workflow context are never authoritative.

### 2.1 Close the inbox→work gap with a transactional outbox

Webhook commit and outbox-dispatch insert happen in **one PostgreSQL transaction** before acknowledgement. A separate leased publisher posts committed outbox rows to SQS; publish-then-crash duplicates are absorbed by consumer idempotency. No new business state machine — the outbox row carries `{tenant_id, exception_id, idempotency_key, payload_hash}` pointers, never duplicated domain state.

### 2.2 Wire production to durable stores — fail closed otherwise

Every production composition path must pass an explicit PostgreSQL engine to the idempotency/execution stores. Add a startup assertion: if the resolved store is in-memory while `APP_ENV != test`, refuse to serve execution traffic. Unit-test defaults stay in-memory.

### 2.3 Identity, intent, and concurrency rules (non-violable)

- One logical operation keeps one stable identity across retries; same key + same payload replays/resumes, same key + different payload conflicts with no mutation.
- Persist execution intent **before** the external side effect; use stable provider idempotency/correlation keys; persist receipts; verify external state; close only on verification.
- Ambiguous outcomes (timeout after a possible write) are recorded UNKNOWN and reconciled — never retried blindly.
- Competing workers resolve via PostgreSQL unique constraints + atomic conditional claim, never Python locks.
- RLS tenant context is set transaction-locally per request and never leaks across pooled connections (test concurrent cross-tenant reuse explicitly).

### 2.4 Frozen contracts stay frozen

P8-02 runtime states and P8-03 recovery semantics are not extended with queued/paused/suspended workflow states. Approvals, waiting, and continuation live at the orchestration/business layer; runtime attempts keep their terminal semantics. Human approval resumes in a new invocation from durable state.

### 2.5 Deployment and operations

- **Migrations run in a separate release job**, never at function startup. The tenant-key migration (`a3f6c1e8b2d4`) takes `ACCESS EXCLUSIVE` — quiesce writers, rehearse lock time, verify remap; its downgrade destroys the tenant boundary, so rollback is restore/forward-fix only. Prefer expand–migrate–contract going forward.
- **Cap worker concurrency** to PostgreSQL + provider capacity (pool math is a reliability control); one situation per message initially; partial-batch failures and DLQ redrive configured; visibility timeout ≥ 6× function timeout.
- **PII/raw payloads**: raw webhook bodies stay out of logs/traces; log correlation IDs, stable IDs, attempt numbers, outcome codes, evidence hashes (P8-03 already bans raw PII in run projections — extend the rule to the raw stores with retention/purge ownership).

## 3. Test oracle for this ADR

Not "the Lambda returned 200" but: **no duplicate financial effect, no lost committed work, no unauthorized transition, no silent abandonment, no closure without verified external state** — proven by crash-in-each-window fault injection, 20–50-way same-key races, cross-tenant connection-reuse races, poison/DLQ drills, and migration-with-writers rehearsal.

## 4. Consequences

- New work: outbox table + leased publisher + idempotent consumer (thin, transport-only), startup store assertion, concurrency/pool sizing, migration job, orchestrator prototype.
- Explicitly deferred: second orchestrator, FIFO ordering (unless a business requirement demands it), full DR program, LLM-observability platform (OTel contract already decided separately).
- This ADR constrains Slice 4/5 staging and deployment qualification: every gate must demonstrate the oracle above against real infrastructure.
