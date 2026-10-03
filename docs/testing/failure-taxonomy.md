# Failure Taxonomy

Closed vocabularies. Anything outside these is a bug in the mapping,
not a new category.

## Execution outcomes (`ExecutionResult`)

| `result` | `post_verify` | Exception state | Meaning |
|---|---|---|---|
| `SUCCEEDED` | `MATCHED` | `CLOSED` (via `EXECUTION_VERIFIED`) | independent verification matched |
| `FAILED` | `MISMATCH` | `FAILED` → `ESCALATED` | write/verification break; escalated, never retried blindly |
| `REJECTED` | `MISMATCH` | unchanged | pre-write refusal or typed infra/domain error; safe to retry same key |

`REJECTED` asserts *no authoritative mutation was claimed by this
call*; recovery state is read from the DB, never from the result.

## Typed errors (control plane)

| Error | Meaning | Caller-visible result |
|---|---|---|
| `PersistenceError` | storage failed; the answer is untrustworthy | `REJECTED` |
| `ConcurrencyConflictError` | concurrent mutation won a CAS race | `REJECTED` (same `execution_id`) |
| `IllegalTransitionError` | request violates the domain state machine | `REJECTED` |
| `None` / `False` from a read | record genuinely absent | n/a (not an error) |

Raw driver errors (`OperationalError`, `InterfaceError`) must never
reach callers; `IntegrityError` is reserved for the claim/insert-wins
path and is re-read, not leaked.

## Harness outcomes

`finalize` (success) vs `max_iterations_exhausted`, `missing_node`,
`node_error` (failures). See `harness-contract.md`.

## Idempotency outcomes

`FRESH` (first bind) / `REPLAY` (same key, same hash) / `CONFLICT`
(same key, different hash, no overwrite). All scoped to
`(tenant_id, key)`.

## Verification reads

`IncompleteRead` (missing or unreadable source — run incomplete, mint
nothing, zero-fill nothing). Never coerced into a financial value.
