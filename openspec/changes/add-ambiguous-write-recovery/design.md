# Design: Ambiguous Write Recovery

## 1. The single invariant

> A financial write is retried only when the system can prove the previous attempt did not commit. Otherwise the write is left unresolved and reported as such.

Everything below follows from that sentence.

## 2. Why the current code cannot satisfy it

| Fact | Location | Consequence |
| --- | --- | --- |
| One `TransientError` covers all transient failures | `finance/accounting/errors.py` | A post-send timeout is indistinguishable from a pre-send connection failure |
| `TransientError` docstring asserts "No record is created and the key is not reserved" | `errors.py` | True of the fake; false as a provider guarantee |
| Adapter has no lookup by idempotency key | `finance/accounting/adapter.py` (3 methods) | Ambiguous outcome cannot be resolved |
| `external_reference` persisted only after a successful return | `executor.py:320` | On ambiguity there is no `entry_id` to call `get_entry` with |
| Recovery scans `self._adapter.calls` | `executor.py:587-608` | In-process mock attribute; absent on a real adapter; lost on restart |
| Exhausted retries → `_mark_failed` → `FAILED` | `executor.py:516-529` | Records "did not happen" for an outcome that may have happened |
| Mock raises transient failures before storing | `mock.py` `_consume_transient` | The fake cannot express "committed, then timed out" |

## 3. Outcome model

Three values, exhaustive, mutually exclusive:

| Value | Meaning | Permitted next action |
| --- | --- | --- |
| `CONFIRMED_SUCCESS(entry)` | The original write is known to have committed | Adopt entry; verify; never write again for this key |
| `CONFIRMED_ABSENT` | The original write is known not to have committed | Retry **iff** the adapter declares authoritative absence |
| `UNKNOWN(reason)` | The system cannot safely determine whether it committed | Do not retry; persist and report pending reconciliation |

`UNKNOWN` is not `FAILED`. `FAILED` asserts absence; `UNKNOWN` asserts ignorance. Collapsing them loses the only information that prevents a duplicate.

## 4. Adapter contract

### 4.1 Error taxonomy (split by *send* boundary, not by HTTP status)

| Error | Raised when | Retry semantics |
| --- | --- | --- |
| `WriteNotSentError` | The request provably never left the client (DNS, connect refused, TLS handshake, pre-flight rejection) | Safe to retry with the same key |
| `AmbiguousWriteError` | The request was transmitted but no usable response was received (read timeout, connection reset after send, gateway timeout) | Must resolve by lookup before any retry |
| `ValidationError` / `UnsupportedActionError` | Rejected before transmission | No retry; no record; key not reserved |
| `IdempotencyConflictError` | Same key, differing payload | No write; reject |

`TransientError` is retained as a deprecated alias of `WriteNotSentError` for existing callers, and MUST NOT be raised for a post-send failure.

**Classification is the adapter's obligation.** The executor cannot know whether bytes left the process, so an adapter that cannot classify MUST raise `AmbiguousWriteError` rather than optimistically claiming `WriteNotSentError`. Fail closed.

### 4.2 Lookup by idempotency key

```
get_entry_by_key(idempotency_key) -> EntryLookup
```

`EntryLookup` is three-valued. It is deliberately **not** `AccountingEntry | None`, because `None` conflates "not there" with "could not tell".

| Result | Meaning |
| --- | --- |
| `FOUND(entry)` | A write under this key exists and is visible |
| `CONFIRMED_ABSENT` | The provider authoritatively reports no write under this key |
| `UNAVAILABLE(reason)` | The lookup failed, timed out, or is not supported |

Rules:
- A lookup timeout, 5xx, or connection failure is `UNAVAILABLE`, never `CONFIRMED_ABSENT`.
- `CONFIRMED_ABSENT` is returned only when the adapter's declared consistency makes it reliable (see 4.3).
- `FOUND` returns the *original* entry so the executor can adopt it without writing.
- If the found entry's payload differs from the presented command, the executor MUST NOT write; see transition T8.

**Key scope:** `(tenant_id, idempotency_key)`. A key is never global. Implementations MUST scope lookups by tenant; a lookup MUST NOT return another tenant's entry.

**Durability:** keys MUST survive process restarts. The executor already satisfies this — `IdempotencyStore` is SQLAlchemy-backed (`shared/safety/idempotency.py`) and `ExecutionResult`/`execution_id` derive deterministically from `(tenant_id, key)`. The mock does not: `_create_keys` is an instance dict. The fake MUST be constructible over shared state so a restart can be modelled.

**Repeat write with the same key:** the adapter MUST either return the original entry (`REPLAY_ORIGINAL`) or reject with `IdempotencyConflictError` (`REJECT_CONFLICT`). Both are safe. Which one occurs is a declared capability, not an executor assumption.

### 4.3 Declared recovery capabilities

```
describe_recovery_capabilities() -> WriteRecoveryCapabilities
```

| Field | Type | Purpose |
| --- | --- | --- |
| `lookup_by_key` | `bool` | Whether `get_entry_by_key` is meaningful |
| `lookup_consistency` | `STRONG` \| `EVENTUAL` | Whether a miss can be trusted |
| `absence_is_authoritative` | `bool` | The executor's retry switch (see below) |
| `duplicate_write_semantics` | `REPLAY_ORIGINAL` \| `REJECT_CONFLICT` | Repeat-write behaviour |
| `key_retention_seconds` | `int` | How long the provider dedupes a key |
| `max_recovery_lookups` | `int` | Lookup poll budget before giving up to `UNKNOWN` |

Derivation, enforced in code, not documentation:

```
absence_is_authoritative == (
    lookup_by_key
    and lookup_consistency is STRONG
    and key_retention_seconds >= recovery_window_seconds
)
```

If the adapter declares `absence_is_authoritative = False`, `CONFIRMED_ABSENT` MUST NOT authorize a retry. The executor stays `UNKNOWN`. This is the user's stated constraint: an absent answer is safe evidence only when the provider's guarantees make it reliable.

## 5. Executor state-transition table

Precondition for all rows: an intent row exists at `EXECUTING` with the key claimed at `(tenant, key)` and `payload_hash` bound (`executor.py:236`, `:312`).

`PENDING` below means: row remains `EXECUTING`, `result = None`, `ExecutionResultStatus.PENDING_RECONCILIATION`, **no further adapter write**.

| # | Observation | Source | Decision | Adapter writes this run | Terminal result |
| --- | --- | --- | --- | --- | --- |
| T1 | `WriteNotSentError` | adapter | Retry same key, ≤3 total | 1–3, none can duplicate | `SUCCEEDED` / `FAILED` after budget |
| T2 | Entry returned (`SUCCESS` or `IDEMPOTENCY_REPLAY`) | adapter | Treat as committed → `POST_VERIFYING` | 1 | `SUCCEEDED` iff post-verify `MATCHED`, else `FAILED` |
| T3 | `AmbiguousWriteError` | adapter | Enter recovery; do **not** retry | 1 (the ambiguous one) | determined by T4–T8 |
| T4 | `get_entry_by_key` → `FOUND(entry)` | provider | Adopt entry; no second write → `POST_VERIFYING` | 0 additional | `SUCCEEDED` iff verified |
| T5 | `CONFIRMED_ABSENT` and `absence_is_authoritative` | provider | Controlled retry, same key, ≤3 | 1 additional | `SUCCEEDED` / `FAILED` |
| T6 | `CONFIRMED_ABSENT` and NOT authoritative | provider | No retry | 0 | `PENDING_RECONCILIATION` |
| T7 | `UNAVAILABLE` after `max_recovery_lookups` | provider | No retry | 0 | `PENDING_RECONCILIATION` |
| T8 | `FOUND` but payload ≠ command | provider | Conflict; no write; human required | 0 | `PENDING_RECONCILIATION` |
| T9 | Terminal row already exists | durable store | Replay stored result | 0 | original |
| T10 | Intent unresolved (crash/restart) | durable store | Resolve via `get_entry_by_key`, **not** `_adapter.calls` | 0 | T3–T8 |
| T11 | Same key, different `payload_hash` | claim store | Reject | 0 | `REJECTED` |

Notes:
- T3 is the only transition that may add a lookup; T1 and T5 are the only ones that may add a write.
- T6/T7/T8 all end in the same durable, retry-safe place, and all are distinguishable in the row's reason so an operator can tell "provider never answered" from "provider said no such write".
- T10 removes the dependency on `_scan_adapter_calls`. The in-memory scan may remain as a non-authoritative hint but MUST NOT be the basis for a retry decision.
- No row in this table maps to `FAILED` unless absence is established (T1 exhaustion, or T2 post-verify mismatch).

## 6. Provider capability inventory (as it actually is)

The repository has **no live outbound accounting/payment write client**:

- `finance/accounting/*` is sandbox-only; `AccountingAdapter` is satisfied solely by `MockAccountingAdapter`.
- Razorpay appears only as an inbound webhook *source type* (`finance/correlation/*`, `shared/privacy/inventory.py`) — read-side normalisation, no writes.
- `finance/stripe/adapter.py` normalises inbound events; it is not a write client.
- `.env.example` carries Stripe webhook secrets only; no Razorpay API credentials.

Therefore no provider guarantee exists to rely on today. The contract must be satisfied by declared capabilities, and any future live adapter must declare and prove them.

| Capability | Sandbox fake (today) | Live provider (today) | Required before live writes |
| --- | --- | --- | --- |
| Classify pre-send vs post-send failure | No — single `TransientError`, raised before write | None | Adapter MUST classify; else always `AmbiguousWriteError` |
| Lookup by idempotency key | No — protocol lacks it | None | MUST implement |
| Lookup consistency declared | N/A | None | MUST declare |
| Repeat write, same key | Replays original (`_create_keys`), in-memory | None | MUST declare durability |
| Differing payload, same key | `IdempotencyConflictError` | None | MUST declare |
| Key durable across restart | No — instance dict | None | Executor is durable; fake MUST be able to model provider durability |
| Key retention window | Process lifetime | None | MUST declare `key_retention_seconds` |
| Absence authoritative | Not expressible | None | Derived from the three guarantees above |

The honest reading: `absence_is_authoritative` is **false for every adapter that exists today**. Under this contract the executor's correct behaviour with the current fake is therefore to report `PENDING_RECONCILIATION` rather than retry — unless the fake is given a strong guarantee declaration, which is a deliberate test-only affordance and must be labelled as such.

## 7. Failure-injection contract

The fake gains scripted outcomes, expressed per key:

| Script | Behaviour |
| --- | --- |
| `not_sent={key: n}` | Raise `WriteNotSentError` `n` times, no record |
| `commit_then_timeout={key: n}` | **Store the entry**, then raise `AmbiguousWriteError` `n` times |
| `lookup_unavailable={key: n}` | `get_entry_by_key` returns `UNAVAILABLE` `n` times |
| `lookup_lag_reads=n` | `FOUND` not visible for `n` lookups, then visible (eventual consistency) |
| `capabilities=...` | Declared `WriteRecoveryCapabilities`, including `absence_is_authoritative` |
| `shared_state=` | Optional external store so a second instance models a restart |

`commit_then_timeout` is the load-bearing addition: it is the only way to create the ambiguous state the production code must survive.

Every injected call MUST still append an `AdapterCall` with a distinct outcome (`AMBIGUOUS_TIMEOUT`) carrying the committed `entry_id`, so tests can assert both "one entry exists" and "the executor learned its id".

## 8. Acceptance tests

Each test asserts entry-count and write-count, not just the returned status.

| ID | Scenario | Assertion |
| --- | --- | --- |
| A1 | Timeout before send | retry succeeds; exactly 1 entry; `SUCCEEDED` |
| A2 | Timeout after commit (`commit_then_timeout=1`) | lookup `FOUND`; **1 entry total**; 1 write attempt; `SUCCEEDED` |
| A3 | Lookup `CONFIRMED_ABSENT`, authoritative, provider dedupes | 1 entry; retry permitted; `SUCCEEDED` |
| A4 | Lookup `UNAVAILABLE` × `max_recovery_lookups` | **1 entry**; no retry; `PENDING_RECONCILIATION`; row remains `EXECUTING` |
| A5 | `CONFIRMED_ABSENT` but not authoritative | no retry; `PENDING_RECONCILIATION` |
| A6 | Duplicate delivery, terminal row | original result replayed; 1 entry; 0 new writes |
| A7 | Same key, differing payload | `REJECTED`; 1 entry; 0 new writes |
| A8 | Restart: second executor over the same durable store, `commit_then_timeout=1` | lookup resolves; **1 entry**; `SUCCEEDED`; proves no dependence on `_adapter.calls` |
| A9 | Lookup `FOUND` with differing payload | no write; `PENDING_RECONCILIATION` |

Negative controls (the suite must go red if the fix is reverted):

| Control | Revert | Expected failure |
| --- | --- | --- |
| NC1 | Restore blind retry on `AmbiguousWriteError` | A2/A8 report 2 entries |
| NC2 | Make `UNAVAILABLE` fall through to `CONFIRMED_ABSENT` | A4 reports 2 entries |
| NC3 | Point recovery at `_adapter.calls` only | A8 fails after restart |
| NC4 | Map `UNKNOWN` to `FAILED` | A4/A5/A9 report a false `FAILED` |

## 9. Smallest production change

1. `errors.py`: add `WriteNotSentError`, `AmbiguousWriteError`, `LookupUnavailableError`; narrow `TransientError`.
2. `adapter.py`: add `LookupOutcome`, `EntryLookup`, `WriteRecoveryCapabilities`, `get_entry_by_key`, `describe_recovery_capabilities`.
3. `mock.py`: implement key lookup over durable-capable state; add the four scripts and the capability declaration.
4. `executor.py`: replace `_bounded_write` with `_write_with_recovery` implementing T1–T8; replace `_scan_adapter_calls` as the decision source in the T10 path.
5. `execution_result.py`: add `PENDING_RECONCILIATION`.
6. Tests A1–A9 + NC1–NC4; register in `docs/testing/test-accounting.json`.

No change to approval, policy, guard, integrity, or post-verify logic.

## 10. Decisions requiring ratification

| # | Decision | Alternatives | Recommendation |
| --- | --- | --- | --- |
| D1 | `UNKNOWN` maps to `EXECUTING` + `PENDING_RECONCILIATION` | New `ExceptionState.RECONCILIATION_PENDING` | Keep SM-1 frozen; the result enum is the smaller surface |
| D2 | `TransientError` becomes a deprecated pre-send alias | Keep it generic and classify inside executor | Split at the adapter, which is the only place that knows |
| D3 | Retry budget stays 3, shared by pre-send and post-absence retries | Separate budgets | Shared is simpler and bounded; revisit if a provider needs more |
| D4 | No automatic sweeper in this slice | Add a background reconciler now | Out of scope; re-invocation with the same key is already the safe trigger |
| D5 | Fake may be told to declare strong absence for tests | Never allow it; A3 unprovable | Allow, but the declaration is a test fixture, never a production default |
