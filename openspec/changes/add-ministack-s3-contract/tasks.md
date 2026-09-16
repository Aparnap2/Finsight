# Tasks: add-ministack-s3-contract

> Single justified AWS seam (S3). All MiniStack artifacts are TEST-ONLY and gated `pytest -m ministack`.

## 1. Seam audit + lifecycle (this change)

- [x] 1.1 Produce `docs/architecture/MINISTACK_SEAM_AUDIT.md` classifying every AWS service as ACTUAL/PLANNED/TEST-ONLY/NOT REQUIRED (rg over apps/shared/finance/agents/tests, pyproject, docker-compose, workflows, Makefile)
- [x] 1.2 Add `shared/aws/config.py` endpoint abstraction (host `http://localhost:4566` vs container `http://ministack:4566`, region `us-east-1`, creds `test/test`, test-only, `get_aws_settings()` cached, `is_ministack`/`container_endpoint()`/`host_endpoint()`)
- [x] 1.3 Add `docker-compose.ministack.yml` (LocalStack `localstack/localstack:3.8` pinned, `SERVICES=s3`, healthcheck, `postgres:17` alongside; no redis/qdrant/sqs)
- [x] 1.4 Add `scripts/ministack_init.py` idempotent bucket init (`finsight-evidence-test`, `finsight-legacy-outbound-test`, `finsight-legacy-result-test`)
- [x] 1.5 Add `pyproject.toml` `ministack` marker + `dependency-groups.ministack` (`boto3`, `botocore`)
- [x] 1.6 Add `Makefile` targets `ministack-up`/`ministack-init`/`ministack-test`/`ministack-down`/`test-ministack`

## 2. Domain port + adapters

- [x] 2.1 Add `finance/object_store/{port,errors}.py` — `ObjectStorePort` Protocol + `ObjectMeta` (key, content_hash sha256, content_length, tenant_id) + bounded errors (`ObjectNotFoundError`, `TenantIsolationError`, `BucketNotFoundError`, `AdapterUnavailableError`)
- [x] 2.2 Add `finance/object_store/fake.py` — `FakeS3` in-memory, tenant-prefix enforced before store, hash/length preserved, idempotent same-key+bytes
- [x] 2.3 Add `finance/object_store/s3_adapter.py` — `S3Adapter` boto3 via `shared/aws/config.py`, tenant isolation before network, hash-checked, typed errors, never leaks credentials

## 3. Contract + failure matrix

- [x] 3.1 Add `tests/unit/object_store/test_s3_contract_fake.py` — FakeS3 contract: basic put/get/exists/delete, integrity (hash+length), idempotency, tenant isolation (cross-tenant → `TenantIsolationError` before store), missing object (`ObjectNotFoundError`), malformed key, wrong tenant, credential-leak assertion, correlation-id, batch idempotency (11 tests, zero-network, fast)
- [x] 3.2 Add `tests/ministack/test_s3_ministack.py` — MiniStack S3 contract (gated `pytest -m ministack`): same contract against real LocalStack S3 plus wrong-bucket → `BucketNotFoundError`, invalid-credential → fail-closed (xfail for LocalStack permissiveness), crash-after-commit simulation, at-least-once duplicate delivery, correlation, host-vs-container endpoint config (skipped when `not _ministack_reachable()`; do not treat skip as pass)

## 4. CI separation

- [x] 4.1 Keep `ci.yml` fast and infrastructure-independent (lint/format/mypy/unit+contract only, no ministack)
- [x] 4.2 Extend `.github/workflows/integration.yml` with `ministack` job (postgres + localstack:3.8 services, healthchecks, `AWS_ENDPOINT_URL=http://localhost:4566`, `uv sync --group ministack`, wait for both, `scripts/ministack_init.py`, `pytest -m ministack`, artifact upload)
- [x] 4.3 Verify failure matrix is covered: ministack unavailable → explicit `AdapterUnavailableError`/skip; S3 unavailable → bounded adapter failure; duplicate event/file → idempotent (same key+bytes same hash); wrong tenant → `TenantIsolationError`; missing object → `ObjectNotFoundError`; timeout → retry/reconcile per port (future); crash-after-commit → idempotent redelivery; wrong control total remains legacy-layer concern (not S3)

## 5. Spec + validation

- [x] 5.1 Add `openspec/changes/add-ministack-s3-contract/specs/object-store/spec.md` — ADDED requirements with SHALL/MUST + Scenario per requirement
- [x] 5.2 Run `openspec validate add-ministack-s3-contract --strict` green before merge
- [x] 5.3 Run `uv run ruff check .` clean on touched, `uv run mypy shared/aws finance/object_store` clean, `uv run pytest tests/unit/object_store -q` green

## 6. Non-goals (must remain true)

- [x] 6.1 No `SQS`/`SNS`/`EventBridge`/`DynamoDB`/`StepFunctions` adapter, compose service, or test in this change (NOT REQUIRED until queue gate fires: `p99 latency requires async ack OR crash-after-commit leaves RECEIVED permanently OR poison messages require DLQ/redrive`)
- [x] 6.2 No production `boto3` default dep; ministack group is test-only, gated
- [x] 6.3 No financial truth moved into S3; no LLM path retrieves arbitrary S3 objects
