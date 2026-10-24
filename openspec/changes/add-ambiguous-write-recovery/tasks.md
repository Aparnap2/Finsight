# Tasks: Ambiguous Write Recovery

Status: **contract only — no implementation authorized yet.**
Each task is one reviewable iteration; gates are `uv run ruff check . && uv run mypy . && python -m pytest`.

## Phase 0 — Ratification (blocking)

### Task 0.1 — Ratify contract decisions — ✅ DONE (2026-10-24)
- **Scope:** Resolve D1–D5 in `design.md`; confirm `UNKNOWN → EXECUTING + PENDING_RECONCILIATION` and the `TransientError` narrowing.
- **Acceptance:** Each decision marked accepted or replaced; no open question remains that changes the state table.
- **Test phase:** none (review artifact).
- **Outcome:** All five accepted with conditions recorded in `design.md` §10. D1 adds §5.1 (resolve-before-write on re-invocation). D3 adds §5.3 (durable budget). D4 adds §5.2 (pending row diagnostics). D5 corrects §4.3: `absence_is_authoritative` is derived and never a declared input.

### Task 0.2 — Confirm no live provider is in scope — ✅ DONE (2026-10-24)
- **Scope:** Verify the claim that `finance/accounting/*` is the only write surface and that Razorpay/Stripe are read-side only.
- **Acceptance:** Written confirmation in the change; any live client found is named and scoped before Task 1.1.
- **Test phase:** none (audit).
- **Outcome:** Confirmed in `design.md` §6. `AccountingAdapter` is satisfied only by `MockAccountingAdapter`; Razorpay is an inbound webhook source type; `finance/stripe/adapter.py` normalises inbound events; `.env.example` holds no outbound payment credentials. No live write client exists, so no live provider guarantee is in scope.

## Phase 1 — Contract types (no behaviour change)

### Task 1.1 — Add write error taxonomy
- **Scope:** `finance/accounting/errors.py` — `WriteNotSentError`, `AmbiguousWriteError`, `LookupUnavailableError`; `TransientError` deprecated as pre-send alias; correct the "no record is created" docstring to state it is an adapter obligation.
- **Acceptance:** Existing `TransientError` call sites unchanged and green; new errors are `AccountingError` subclasses; docstrings state the send-boundary rule.
- **Test phase:** Unit.

### Task 1.2 — Add lookup and capability types
- **Scope:** `finance/accounting/adapter.py` — `LookupOutcome`, `EntryLookup` (three-valued), `WriteRecoveryCapabilities`, `get_entry_by_key`, `describe_recovery_capabilities`; update the `AccountingAdapter` Protocol.
- **Acceptance:** `absence_is_authoritative` is a derived property, not a settable field; the type cannot represent a binary present/absent lookup.
- **Test phase:** Unit.

### Task 1.3 — Durable intent lookup and recovery fields
- **Scope:** durable store — `find_intent_by_key(tenant_id, key)`; persisted `recovery_reason`, `adapter_write_attempts`, `recovery_started_at` on the intent row.
- **Acceptance:** A row can be found by `(tenant_id, key)` after restart; the three recovery fields round-trip; `adapter_write_attempts` defaults to 0 and is monotonic.
- **Test phase:** Unit.

### Task 1.4 — Add pending result status
- **Scope:** `finance/execution/execution_result.py` — `ExecutionResultStatus.PENDING_RECONCILIATION`; document that it is non-terminal and never closes a case.
- **Acceptance:** No `ExceptionState` member added; `CLOSED` remains reachable only from `SUCCEEDED` + `MATCHED`.
- **Test phase:** Unit.

## Phase 2 — Fake fidelity

### Task 2.1 — Key lookup over durable-capable state
- **Scope:** `finance/accounting/mock.py` — implement `get_entry_by_key`; allow injection of shared state so two instances model a restart.
- **Acceptance:** Tenant-scoped lookup; a second instance over shared state returns `FOUND`; without shared state it does not, and that difference is asserted.
- **Test phase:** Unit.

### Task 2.2 — Commit-then-timeout and lookup scripts
- **Scope:** `mock.py` — `commit_then_timeout`, `lookup_unavailable`, rename/clarify `visibility_lag_reads`; record `AdapterCall` with an ambiguous outcome carrying `entry_id`.
- **Acceptance:** `commit_then_timeout=1` yields exactly one entry plus one ambiguous call; no existing script changes meaning.
- **Test phase:** Unit.

### Task 2.3 — Capability declaration on the fake
- **Scope:** `mock.py` — `describe_recovery_capabilities`; the fixture may declare the capability **inputs** (`lookup_by_key`, `lookup_consistency`, `key_retention_seconds`, `max_recovery_lookups`, `duplicate_write_semantics`), defaulting to non-authoritative absence.
- **Acceptance:** Default fake derives `absence_is_authoritative = false`. A fixture that needs it true declares strong consistency plus sufficient retention and the value follows. Supplying `absence_is_authoritative` directly is rejected, and a test asserts the type cannot be constructed with it.
- **Test phase:** Unit.

## Phase 3 — Executor recovery

### Task 3.1 — Split pre-send retry from recovery
- **Scope:** `executor.py` — replace `_bounded_write` with `_write_with_recovery`; `WriteNotSentError` keeps retry T1, `AmbiguousWriteError` enters T3.
- **Acceptance:** No retry path exists for ambiguous outcomes; T1 behaviour byte-identical for existing tests.
- **Test phase:** Unit.

### Task 3.2 — Resolve ambiguity by key lookup
- **Scope:** `executor.py` — implement T4–T8 using `get_entry_by_key`; map `FOUND` to adopt-and-verify; map `UNAVAILABLE`/non-authoritative/conflict to pending.
- **Acceptance:** Every ambiguous branch terminates in adoption or `PENDING_RECONCILIATION`; none reaches `FAILED`.
- **Test phase:** Unit.

### Task 3.3 — Remove call-log authority
- **Scope:** `executor.py` — demote `_scan_adapter_calls` to a diagnostic hint; recovery decides from the durable row plus lookup.
- **Acceptance:** Recovery succeeds with the attribute absent; a test asserts the decision is unchanged when it is removed.
- **Test phase:** Unit.

### Task 3.4 — Persist pending without terminal failure
- **Scope:** `executor.py` — write the pending row before returning; ensure `_mark_failed` is unreachable for unknown outcomes.
- **Acceptance:** Row is `EXECUTING` with `PENDING_RECONCILIATION`; `FAILED` requires established absence.
- **Test phase:** Unit.

### Task 3.5 — Resolve unresolved intent on re-invocation (D1)
- **Scope:** `executor.py` — on `IdempotencyStore` `REPLAY`, load the intent via `find_intent_by_key` and branch on persisted state: terminal → replay result; `EXECUTING` with no result → recovery via lookup; missing row → fail closed to pending. No write while a non-terminal intent exists.
- **Acceptance:** Re-invocation of an unresolved intent performs 0 writes and ≥1 lookup; a completed intent replays with 0 writes and 0 lookups. A test asserts no `create_entry` call occurs before the first lookup when the intent is non-terminal.
- **Test phase:** Unit.

### Task 3.6 — Persist the write-attempt budget (D3)
- **Scope:** `executor.py` — increment `adapter_write_attempts` before each write; cap the combined total at 3 across T1 and T5; never reset on restart or re-invocation.
- **Acceptance:** A restart between attempts does not restore budget; a pre-send retry plus a post-absence retry cannot exceed 3 in total.
- **Test phase:** Unit.

### Task 3.7 — Persist pending diagnostics (D4)
- **Scope:** `executor.py` — write `recovery_reason` (T6/T7/T8) and `recovery_started_at` when returning `PENDING_RECONCILIATION`.
- **Acceptance:** The three pending reasons are distinguishable from the row alone; a pending row is distinguishable from a crashed `EXECUTING` row with no reason.
- **Test phase:** Unit.

## Phase 4 — Acceptance

### Task 4.1 — A1–A5 (send boundary and lookup outcomes)
- **Scope:** `tests/unit/test_finance/test_write_recovery.py` — timeout before send, timeout after commit, authoritative absence, unavailable lookup, non-authoritative absence.
- **Acceptance:** Entry and write counts asserted; A2 and A4 each prove exactly one entry.
- **Test phase:** Unit.

### Task 4.2 — A6–A9 (duplicates, conflicts, restart)
- **Scope:** same file — duplicate delivery, conflicting payload, restart with shared state, found-with-differing-payload.
- **Acceptance:** A8 passes with no call log; A7 and A9 write nothing.
- **Test phase:** Unit.

### Task 4.3 — Negative controls NC1–NC4
- **Scope:** documented revert checks, executed manually once and recorded in the PR body.
- **Acceptance:** Each revert produces the expected red test; results pasted into the PR.
- **Test phase:** Unit.

### Task 4.4 — Register tests and decisions
- **Scope:** `docs/testing/test-accounting.json`, `docs/decisions.md`, README test counts.
- **Acceptance:** Manifest lists the new tests; decision record captures D1–D5; counts match collected.
- **Test phase:** none (docs).

### Task 4.5 — A10–A12 (re-invocation, replay, durable budget)
- **Scope:** same file — re-invocation of a pending intent, replay of a completed intent, budget surviving restart.
- **Acceptance:** A10 asserts 0 writes and ≥1 lookup; A11 asserts 0 writes and 0 lookups; A12 asserts the remaining budget is unchanged after restart.
- **Test phase:** Unit.

## Phase 5 — Follow-on (explicitly out of scope here)

- Reconciliation sweeper for long-lived `PENDING_RECONCILIATION` rows.
- Compensating-entry path for the `FOUND`-with-conflicting-payload case.
- Live adapter implementing and proving the capability declaration.
- Provider-specific retention and consistency verification.
