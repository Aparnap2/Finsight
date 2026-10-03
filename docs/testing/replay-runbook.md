# Replay Runbook

How to re-drive any execution and what to expect. The replay key is
always the original `(tenant_id, idempotency_key)` pair.

## 1. Terminal replay (completed execution)

Same tenant, same key, any payload:

1. `_load_row` finds the terminal row (`result` + `post_verify` set).
2. The prior `ExecutionResult` is returned; **no adapter call, no row
   write, no state transition**.

Expect: identical `execution_id`, adapter `create_correcting_entry`
count unchanged.

## 2. In-flight recovery (crashed owner)

Same tenant, same key, same payload; intent row exists with null
outcome; exception at `EXECUTING` (or `POST_VERIFYING`):

1. Store hash must match (else `REJECTED` as conflict).
2. Recovery scans adapter calls by key: booked `SUCCESS` is reused —
   **no second write**.
3. Only when no entry exists is `_bounded_write` called (same key, so
   the adapter dedupes).
4. `external_reference` is persisted, state advances, verification
   runs, terminal outcome lands.

Expect: exactly one `create_correcting_entry` across crash + retry;
exception reaches `CLOSED` (or terminal `FAILED`/`ESCALATED` on a real
break). Verified by `test_local_persist_failure_after_adapter_write…`
and `test_crash_after_ref_before_verify…`.

## 3. Conflict (same key, different payload)

Same tenant: `REJECTED`, zero writes, zero state change.
Cross-tenant: independent ledgers — no conflict, no observation.
Tenant B can neither replay, retrieve, recover, nor mutate tenant A's
execution, nor infer it through conflict behavior.

## 4. What replay never does

- Never mutates canonical fixtures or seeds.
- Never converts a failure into success: `FAILED` replays as `FAILED`.
- Never advances another tenant's row.
- Never treats `PersistenceError` as an outcome: the call returns
  `REJECTED` and the next same-key delivery resumes from the DB.
