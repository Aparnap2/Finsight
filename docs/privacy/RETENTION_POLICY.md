# RETENTION_POLICY.md (P10-05)

Explicit disposition per persisted surface. TTL day counts are policy
inputs defined in `shared/privacy/retention.py` — adjust per counsel,
not per incident. Label: hardened, not compliant.

## webhook_events

Raw provider payloads anonymize after 90 days: the envelope (ids,
type, fingerprint, tenant) stays for audit joins; `raw` becomes the
tombstone `{"anonymized": true}`. No schema migration is required.
Idempotent (already-tombstoned rows skipped and uncounted). Wrong-kind
operations (purge on this table) are refused loudly.

## exceptions

KEEP. Authoritative financial lifecycle truth. Purge attempts raise
`RetentionRefusedError` instead of deleting, even for ancient rows.

## exception_audits

KEEP. Append-only accountability trail. Purge attempts raise
`RetentionRefusedError`.

## executions

KEEP. Authoritative execution ledger; replay depends on it. Purge
attempts raise `RetentionRefusedError`.

## idempotency_keys

EXPIRE_AFTER 90 days. Bindings bound table growth; late retries stay
safe because the execution state machine backstops them (terminal rows
replay, crashed intents resume-or-conflict, never-executed work runs
fresh exactly once). Expiry can only remove replay history, never
resurrect a settled financial action. Purge is idempotent and
tenant-scopable.

## telemetry_files

File expiry after 30 days by mtime. Debug-only artifacts; missing
sweep directories raise instead of silently misconfiguring. Tenant
partitioning of trace files is unestablished (known gap).

## eval_fixtures

KEEP. Versioned benchmark source in git, not data at rest.

## eval_reports

File expiry after 90 days. Derived and reproducible from fixtures plus
code version.

## Exceptions requiring longer retention

None currently defined beyond KEEP surfaces (which are indefinite).
Adding one means a new rule with rationale, TTL, and a test — not an
ad-hoc hold.
