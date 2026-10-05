# Data-Operation Test Matrix

Every persistence boundary below raises `PersistenceError`
(`shared/safety/errors.py`) on SQL transport failure instead of
returning a domain-shaped value. `None`/`False` always means
authoritative "not found". Locks:
`tests/unit/exceptions/test_repository_persistence_error.py`,
`tests/unit/security/test_idempotency_claim.py`,
`tests/unit/execution/test_execution_boundary.py`,
`tests/unit/execution/test_execution_failure_injection.py`.

## Exception aggregate (`finance/exceptions/repository.py`)

| Operation | Transaction boundary | Tenant scope | Failure mapping | Test |
|---|---|---|---|---|
| `create` | row + `CREATED` audit, one commit | row carries `tenant_id` | duplicate → `IllegalTransitionError`; transport → `PersistenceError` | CAS suite + persistence-error suite |
| `get` / `get_for_tenant` | read-only | `get_for_tenant` filters `(tenant_id, exception_id)` | transport → `PersistenceError` | `test_get_on_broken_db…` |
| `apply` | CAS `UPDATE` + audit row, one commit | predicate includes `tenant_id` | 0 rows → `ConcurrencyConflictError`; transport → `PersistenceError` | rollback test (drop audit table → row unmutated) |
| `audit_trail` / `_audit_rejection` | single insert/select | filtered by `exception_id` | transport → `PersistenceError` | persistence-error suite |

Atomicity proof: dropping `exception_audits` makes `apply` fail and
leaves `state`/`state_version` untouched.

## Idempotency ledger (`shared/safety/idempotency.py`)

Identity is `(tenant_id, idempotency_key)` (composite PK).

| Operation | Semantics | Concurrency | Test |
|---|---|---|---|
| `seen` / `payload_hash_for` | strict `bool` / first hash or `None` | read-only | persistence-error suite |
| `record` | bind or refresh identical binding | `IntegrityError` on same-hash race → no-op replay; different hash re-raises | claim contract suite |
| `claim` | `FRESH` / `REPLAY` / `CONFLICT`, never overwrites | insert-wins; loser re-reads → `REPLAY`/`CONFLICT` | 4-thread race: exactly one `FRESH` |

## Execution boundary (`finance/execution/executor.py`)

`execution_id` is `exec_sha16(tenant_id|key)`; `ExecutionRow` PK is
`(tenant_id, idempotency_key)`. Order inside `run`:

1. terminal row (`result` + `post_verify` set) → replay, no writes;
2. store hash mismatch → `REJECTED`, no writes;
3. non-terminal intent row → **recovery** (scan adapter by key, write
   only if absent, advance, verify) — dispatched *before* the
   fresh-`APPROVED` gate so crashed owners are resumable;
4. fresh `APPROVED` gate → integrity → guard → policy → `claim`
   (`FRESH` binds, `REPLAY` passes through, `CONFLICT` rejects) →
   single-commit intent
   (`APPROVED→EXECUTING` + audit + row) → bounded same-key adapter
   writes → persist `external_reference` → `POST_VERIFYING` →
   verify → `CLOSED`, or `FAILED`/`MISMATCH` → `FAILED`→`ESCALATED`.

Typed mapping at `run`: `ConcurrencyConflictError`,
`IllegalTransitionError`, `PersistenceError` → `REJECTED` result;
the DB stays the source of truth and the next same-key delivery
resumes from persisted state.

## Alembic

`a3f6c1e8b2d4_tenant_scoped_execution_keys.py` (revises `c9d5e7f1a204`)
adds `tenant_id` and upgrades both PKs to `(tenant_id,
idempotency_key)`, backfilling `''`.
