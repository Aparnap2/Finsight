## ADDED Requirements

### Requirement: Three-Valued Write Outcome

The system SHALL classify every adapter write attempt into exactly one of `CONFIRMED_SUCCESS`, `CONFIRMED_ABSENT`, or `UNKNOWN`. `CONFIRMED_SUCCESS` SHALL carry the committed entry. `UNKNOWN` SHALL NOT be treated as failure and SHALL NOT authorize a retry. Only `CONFIRMED_ABSENT` under the conditions of Requirement: Authoritative Absence SHALL authorize a retry.

#### Scenario: Ambiguous outcome is not recorded as failure

- **WHEN** a write is transmitted and the adapter raises `AmbiguousWriteError`
- **THEN** the outcome is `UNKNOWN`, the execution result is `PENDING_RECONCILIATION`, no entry is recorded as `FAILED`, and no additional write is attempted in that run

#### Scenario: Confirmed absence is the only retry gate

- **WHEN** the adapter reports `CONFIRMED_ABSENT` and declares authoritative absence
- **THEN** the executor may retry the same idempotency key; when the adapter does not declare authoritative absence, the outcome remains `UNKNOWN`

### Requirement: Write Failure Classification

The accounting adapter SHALL classify write failures by whether the request was transmitted, not by HTTP status class. A failure that provably occurred before transmission SHALL raise `WriteNotSentError`. A failure where the request may have been transmitted without a usable response SHALL raise `AmbiguousWriteError`. `TransientError` SHALL be retained only as a deprecated alias of `WriteNotSentError` and SHALL NOT be raised for a post-send failure. An adapter unable to classify SHALL raise `AmbiguousWriteError`.

#### Scenario: Read timeout after send is ambiguous

- **WHEN** an adapter sends a create-entry request and the read timeout elapses before a response
- **THEN** it raises `AmbiguousWriteError`, and the executor enters recovery instead of retrying

#### Scenario: Connection refused is safely retryable

- **WHEN** the adapter cannot establish a connection and raises `WriteNotSentError`
- **THEN** the executor may retry the same key up to the existing budget without risk of duplication

### Requirement: Lookup By Idempotency Key

The accounting adapter SHALL expose `get_entry_by_key(idempotency_key)` returning a three-valued lookup: `FOUND(entry)`, `CONFIRMED_ABSENT`, or `UNAVAILABLE(reason)`. The result SHALL NOT be modelled as an optional entry. A lookup timeout, transport error, server error, or unsupported operation SHALL be `UNAVAILABLE` and SHALL NOT be reported as `CONFIRMED_ABSENT`.

#### Scenario: Lookup failure never becomes evidence of absence

- **WHEN** `get_entry_by_key` times out while resolving an ambiguous write
- **THEN** the lookup result is `UNAVAILABLE`, the write outcome remains `UNKNOWN`, and no retry occurs

#### Scenario: Found entry is adopted without a second write

- **WHEN** `get_entry_by_key` returns `FOUND(entry)` for a key whose write timed out
- **THEN** the executor adopts that entry, performs post-verification, makes no additional write, and the result is `SUCCEEDED` only if verification reports `MATCHED`

### Requirement: Declared Recovery Capabilities

Each adapter SHALL declare its recovery capabilities through `describe_recovery_capabilities()`, covering lookup availability, lookup consistency, duplicate-write semantics, key retention window, and lookup budget. The executor SHALL derive recovery behaviour exclusively from these declarations and SHALL NOT assume provider guarantees. `absence_is_authoritative` SHALL be derived as true only when lookup is supported, consistency is strong, and key retention covers the recovery window.

#### Scenario: Undeclared guarantees forbid retry

- **WHEN** an adapter declares `absence_is_authoritative = false`
- **THEN** a `CONFIRMED_ABSENT` lookup does not authorize any retry and the outcome remains `UNKNOWN`

#### Scenario: Retention shorter than the recovery window

- **WHEN** an adapter declares `key_retention_seconds` shorter than the executor's recovery window
- **THEN** `absence_is_authoritative` evaluates to false regardless of the declared consistency

### Requirement: Executor Recovery Transitions

The executor SHALL implement recovery so that exactly two paths may write (pre-send retry, and retry after authoritative absence) and no other path may write. On `AmbiguousWriteError` the executor SHALL resolve through `get_entry_by_key` before deciding. Exhausting the lookup budget SHALL end in `PENDING_RECONCILIATION`, not `FAILED`.

#### Scenario: Bounded lookup budget ends pending

- **WHEN** every recovery lookup returns `UNAVAILABLE` up to `max_recovery_lookups`
- **THEN** exactly one entry exists for the key, no retry is attempted, and the result is `PENDING_RECONCILIATION`

#### Scenario: Found entry with conflicting payload is not overwritten

- **WHEN** recovery finds an entry under the key whose payload differs from the presented command
- **THEN** the executor performs no write and reports `PENDING_RECONCILIATION` for human adjudication

### Requirement: Unknown Is Durable And Is Not Failure

An unknown outcome SHALL be persisted durably before the call returns. The aggregate SHALL remain in `EXECUTING` and the execution result SHALL be `PENDING_RECONCILIATION`; no terminal `FAILED` verdict SHALL be recorded unless absence has been established. The system SHALL NOT introduce new states into the frozen `ExceptionState` vocabulary.

#### Scenario: Process crash during ambiguity leaves a recoverable row

- **WHEN** the process terminates after an ambiguous write and before resolution
- **THEN** the persisted intent remains `EXECUTING` with a `PENDING_RECONCILIATION` result, and a later invocation with the same key resolves it without a duplicate write

### Requirement: Key Scope, Durability And Conflict

Idempotency keys SHALL be scoped to `(tenant_id, key)` and SHALL survive process restarts. A repeat write under the same key SHALL either replay the original entry or be rejected as a conflict, as declared by the adapter. A differing payload under an existing key SHALL be rejected with no write and no key reuse.

#### Scenario: Cross-tenant key collision is impossible

- **WHEN** tenant A and tenant B submit the same literal idempotency key
- **THEN** each resolves within its own tenant scope and neither observes the other's entry

#### Scenario: Conflicting payload under one key is rejected

- **WHEN** a second execution presents a different payload hash for an already-claimed key
- **THEN** the request is `REJECTED`, no adapter write occurs, and the original entry is unchanged

### Requirement: No In-Process Call-Log Authority

Recovery decisions SHALL NOT depend on an adapter's in-process call history. Any in-memory call log MAY inform diagnostics or a non-authoritative hint, but the authority for retry SHALL be the durable intent plus `get_entry_by_key`.

#### Scenario: Recovery works on an adapter without a call log

- **WHEN** an adapter exposes no call-history attribute
- **THEN** recovery still resolves the ambiguous write through durable key lookup rather than falling through to a blind retry

#### Scenario: Recovery after restart ignores lost in-memory state

- **WHEN** a new executor instance resolves a prior ambiguous write
- **THEN** the decision uses the durable store and provider lookup, and the in-memory call log is absent without changing the outcome

### Requirement: Failure Injection Contract

The sandbox adapter SHALL be able to express outcomes that the current fake cannot: a write that commits and then times out, an unavailable lookup, and a lagging read. Injected ambiguous writes SHALL still record the committed entry and an adapter call marked with an ambiguous outcome carrying the entry identifier.

#### Scenario: Commit then timeout produces exactly one entry

- **WHEN** the fake is scripted to commit and then raise an ambiguous timeout once for a key
- **THEN** exactly one entry exists for that key, the adapter call is recorded as ambiguous with that entry identifier, and the executor resolves it by lookup

#### Scenario: Lookup unavailability is scriptable

- **WHEN** the fake is scripted to return `UNAVAILABLE` for a key
- **THEN** the executor observes `UNAVAILABLE` rather than absence and does not retry

### Requirement: Acceptance Verification

The change SHALL include acceptance tests covering timeout before send, timeout after commit, absent lookup, unavailable lookup, duplicate delivery, conflicting payload, and recovery after process restart. Each test SHALL assert entry counts and write counts in addition to status. Reverting the fix SHALL cause at least one assertion to fail.

#### Scenario: Duplicate delivery replays without a second write

- **WHEN** an execution is delivered twice for a terminal key
- **THEN** the stored result is replayed, exactly one entry exists, and no new write occurs

#### Scenario: Reverting to blind retry fails the suite

- **WHEN** the executor is changed to retry directly on an ambiguous write
- **THEN** the after-commit and restart acceptance tests fail on entry-count assertions
