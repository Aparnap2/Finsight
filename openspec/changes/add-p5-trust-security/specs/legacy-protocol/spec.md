## ADDED Requirements

### Requirement: Legacy Batch Protocol

The system SHALL define `docs/architecture/LEGACY_BATCH_PROTOCOL.md` specifying `file identity`, `batch identity`, `schema`, `field positions`, `version`, `sequence`, `control total`, `checksum/hash`, `accepted record`, `rejected record`, `partial processing`, `duplicate detection`, `result semantics`, `retry semantics`, `timeout semantics`, and `OUTBOUND → legacy processing → RESULT` without HTTP, via `finance/object_store` buckets `finsight-legacy-outbound-test` / `finsight-legacy-result-test` per tenant (S3 transport only, PostgreSQL remains authority).

#### Scenario: Protocol distinguishes accepted vs partial vs duplicate

- **WHEN** an outbound file `tenant-a/batch-123.csv` (control total `35000.00`, 10 records) is processed and the legacy result contains `7 accepted, 3 rejected, duplicate batch-123 detected on retry`
- **THEN** the ingestion layer records `partial processing` with `accepted` set, `rejected` set, `duplicate detection` on second submit as `one effect`, and `control total` mismatch fails closed

### Requirement: MiniStack S3 as Legacy Transport

The system SHALL use existing MiniStack S3 (`docker-compose.ministack.yml` `localstack:3.8 SERVICES=s3`, `shared/aws/config.py` host vs container endpoint, `scripts/ministack_init.py` idempotent buckets) for `evidence artifacts`, `legacy outbound files`, and `legacy result files`, not as substitute for PostgreSQL financial state. `SQS` SHALL remain closed unless queue gate (`p99 latency requires async ack OR crash-after-commit leaves RECEIVED OR poison→DLQ`) is triggered by a failing test.

#### Scenario: S3 transport does not become source of truth

- **WHEN** an S3 legacy result file `tenant-a/batch-123/result.json` is written
- **THEN** the case is not `VERIFIED` until deterministic `finance/evidence` + `post-execution verification` re-reads the file, checks `checksum/hash` and `control total`, and reconciles via PostgreSQL transaction
