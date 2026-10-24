# Proposal: Ambiguous Write Recovery for Financial Provider Calls

## Why

`finance/execution/executor.py:_bounded_write` retries any `TransientError` up to `_MAX_ADAPTER_WRITES` (3) times on the same idempotency key. Its safety rests entirely on the sandbox fake's promise that a transient failure is raised *before* any record is created:

```
TransientError: "No record is created and the key is not reserved, so the
retry path cannot duplicate."                       — finance/accounting/errors.py
```

That promise is about the *fake*, not about a provider. For a real financial provider, a request that times out after transmission may have committed. Retrying then duplicates a financial action, and `_bounded_write` cannot tell the two apart because:

1. `TransientError` does not distinguish *not sent* from *sent, outcome lost*.
2. `AccountingAdapter` has no lookup by idempotency key — only `get_entry(entry_id)`, and on the ambiguous path no `entry_id` was ever received (`external_reference` is persisted only *after* a successful return, `executor.py:320`).
3. The only existing recovery mechanism, `_scan_adapter_calls` (`executor.py:587`), reads `self._adapter.calls` — an in-process attribute of the mock. It is not a provider capability and does not survive a process restart.
4. `_bounded_write` returns `None` on exhaustion, which `_mark_failed` records as `FAILED`. `FAILED` is a claim that the write did not happen, which an ambiguous outcome cannot support.

Today the code is safe only because the only adapter is the fake. The moment a live adapter exists, the retry path is a duplicate-write hazard. This is a production correctness gap, not a missing test.

## What Changes

- **Introduces a three-valued write outcome**: `CONFIRMED_SUCCESS`, `CONFIRMED_ABSENT`, `UNKNOWN`. `UNKNOWN` is neither a failure nor permission to retry.
- **Adds lookup by idempotency key** to the adapter contract, itself three-valued (`FOUND`, `CONFIRMED_ABSENT`, `UNAVAILABLE`) so that a failed lookup can never be mistaken for evidence of absence.
- **Adds declared recovery capabilities** (`WriteRecoveryCapabilities`). Whether `CONFIRMED_ABSENT` authorizes a retry is derived from the adapter's declared consistency and key-retention guarantees, never assumed by the executor.
- **Splits the write failure taxonomy**: `WriteNotSentError` (provably not transmitted, retry safe) vs `AmbiguousWriteError` (transmitted, outcome unknown, must resolve by lookup). `TransientError` is narrowed to the pre-send case.
- **Replaces the in-memory call-log scan** as the recovery mechanism with durable key lookup.
- **Adds `ExecutionResultStatus.PENDING_RECONCILIATION`** and keeps the aggregate in `EXECUTING` for unknown outcomes. No new `ExceptionState` is introduced; the frozen SM-1 vocabulary is unchanged.
- **Extends the failure-injection fake** so it can commit a write and then raise a timeout, and can make lookup unavailable — the two conditions the current fake cannot express.

## Impact

- **Affected specs (ADDED):** `accounting-write-recovery`.
- **Affected code (after approval):** `finance/accounting/errors.py`, `finance/accounting/adapter.py`, `finance/accounting/mock.py`, `finance/execution/executor.py`, `finance/execution/execution_result.py`, `tests/unit/test_finance/`, `docs/testing/test-accounting.json`, `docs/decisions.md`.
- **Unaffected:** approval, policy, guard, triple-hash integrity, tenant isolation, post-verification tolerance, the idempotency claim store's `(tenant, key)` scope.

## Non-Goals

- No live provider integration; no credentials, no network writes.
- No change to the 3-attempt budget, and no new retry budget.
- No automatic reconciliation sweeper. `PENDING_RECONCILIATION` is a durable handoff; a re-invocation with the same key is the existing safe recovery trigger.
- No change to the frozen `ExceptionState` vocabulary.
- No rollback of already-booked entries; that is a separate compensating-entry concern.

## Approval Required

`finance/execution/execution_result.py` and `finance/accounting/adapter.py` are contract surfaces consumed by tests that assert current terminal verdicts. Adding `PENDING_RECONCILIATION` changes the set of legal results. Implementation SHALL NOT begin until this contract is ratified.
