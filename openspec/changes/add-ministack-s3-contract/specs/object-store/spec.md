## ADDED Requirements

### Requirement: Object-Store Port and Tenant Scoping

The system SHALL expose an `ObjectStorePort` with `put_object`, `get_object`, `exists`, `delete` operating on tenant-prefixed keys (`{tenant_id}/{case_or_batch_id}/{filename}`). The port SHALL reject wrong-tenant access with `TenantIsolationError` before any backing-store network call, and `ObjectMeta` SHALL carry `content_hash` (sha256 hex of raw bytes), `content_length`, and `tenant_id`. The port MAY be backed by `FakeS3` (in-memory) or `S3Adapter` (boto3 via `shared/aws/config.py`).

#### Scenario: Tenant-scoped put and get

- **WHEN** a caller stores bytes at a tenant-prefixed key and retrieves it as the same tenant
- **THEN** the returned bytes equal the stored bytes, `content_hash` equals `sha256(bytes)`, `content_length` equals `len(bytes)`, and `tenant_id` matches the caller

#### Scenario: Cross-tenant access rejected before store

- **WHEN** tenant A attempts to `put`, `get`, `exists`, or `delete` a key prefixed with tenant B
- **THEN** the call raises `TenantIsolationError` before any store interaction and the backing store is unmutated

### Requirement: S3 Contract — Basic, Integrity, Idempotency

The S3 contract SHALL satisfy: (1) basic lifecycle `put → exists → get → delete → not exists`; (2) integrity — `content_hash` and `content_length` preserved exactly; (3) idempotency — repeated `put` with same key+bytes yields same hash and a single logical object, while different bytes at the same key overwrite deterministically; (4) missing object → `ObjectNotFoundError` (bounded, not silent fallback).

#### Scenario: Contract holds for Fake and MiniStack

- **WHEN** the contract suite is run against `FakeS3` (zero-network) and against `S3Adapter` on MiniStack (`pytest -m ministack` with LocalStack)
- **THEN** both backings satisfy basic, integrity, idempotency, and missing-object behaviors identically

### Requirement: AWS Endpoint Configuration

The system SHALL centralize AWS endpoint selection in `shared/aws/config.py` (`AwsSettings`) with `aws_endpoint_url` default `http://localhost:4566` (host) and `http://ministack:4566` inside the compose network (`container_endpoint()`), region `us-east-1`, test credentials `test/test`, and `is_ministack` detection. No test or adapter SHALL scatter endpoint literals; production credentials SHALL NOT appear in this configuration, and bucket names SHALL be `-test` suffixed and deterministic (`finsight-evidence-test`, `finsight-legacy-outbound-test`, `finsight-legacy-result-test`).

#### Scenario: Host vs container endpoint resolve correctly

- **WHEN** `AwsSettings(aws_endpoint_url="http://localhost:4566").container_endpoint()` is called
- **THEN** it returns `http://ministack:4566`, and `AwsSettings(aws_endpoint_url="http://ministack:4566").host_endpoint()` returns `http://localhost:4566`

### Requirement: MiniStack Lifecycle and Resource Initialization

The system SHALL provide `docker-compose.ministack.yml` (LocalStack `localstack/localstack:3.8` pinned, `SERVICES=s3`, healthcheck, `postgres:17` alongside; no redis/qdrant/sqs) and an idempotent initializer `scripts/ministack_init.py` that creates required buckets if absent (`head_bucket` then `create_bucket`, race-safe for `BucketAlreadyOwnedByYou`, `us-east-1` special case). Running initialization twice SHALL not corrupt or duplicate resources. `Makefile` targets `ministack-up`/`ministack-init`/`ministack-test`/`ministack-down`/`test-ministack` SHALL compose the lifecycle.

#### Scenario: Idempotent initialization

- **WHEN** bucket initialization is executed twice against a reachable MiniStack
- **THEN** the second run completes without error and no duplicate bucket exists

### Requirement: Security and Failure-Matrix

The object-store contract SHALL enforce: wrong bucket → `BucketNotFoundError`; invalid/expired credential → fail-closed (bounded error, `xfail` for LocalStack permissiveness); missing object → `ObjectNotFoundError`; malformed key (non-tenant-prefixed) → `ValueError` before store; tenant/wrong-key and credential failures SHALL never leak `AWS`/`secret`/`access` literals in exception messages; correlation id (`case`/`batch` in key) SHALL survive `put→get`. The system SHALL remain *PostgreSQL is the financial/idempotency authority; S3 is transport/artifact only; the LLM never retrieves arbitrary S3 objects* — moving truth into S3 or opening an arbitrary S3 retriever SHALL be rejected by design and by test.

#### Scenario: Wrong bucket and credential are bounded failures

- **WHEN** a `put` targets a non-existent bucket or uses an invalid credential
- **THEN** the call raises a bounded typed error (`BucketNotFoundError` or fail-closed) and does not silently fall back to another bucket or tenant

### Requirement: Crash and At-Least-Once Delivery

The contract SHALL prove `crash-before-ack` (S3 put + DB commit succeed, acknowledgement lost, redelivery with same key+bytes) is idempotent — same hash, single logical object — and `at-least-once duplicate delivery` (same event/batch bytes delivered twice) yields one logical effect. The database SHALL remain the idempotency authority; SQS is transport-only — but since `SQS` has no seam at this checkpoint, the S3-level idempotency (same key+bytes same hash) is the contract that preserves *one logical state transition* under redelivery.

#### Scenario: Duplicate delivery is idempotent

- **WHEN** the same logical event bytes are delivered twice to the same key
- **THEN** the store holds exactly one object whose bytes equal the event, and both puts return the same `content_hash`
