# Design: MiniStack S3 Contract — LocalStack S3 for Evidence/Batch Artifacts

## Context

FinSight P4 is deterministic-financial-core + bounded agentic investigation (5 contracts, 3 exception types, 5-tool allowlist, 6-stage verifier, CAS aggregate, sandbox+post-verify). At `finsight-p4-complete` there is **0 actual AWS production seam** (no `boto3`, no S3/SQS client, `docker-compose.test.yml` comment: *no queue seam exists*). The mandatory rule for this phase is: *an emulator is justified only when a real seam needs contract testing*. The seam audit (`docs/architecture/MINISTACK_SEAM_AUDIT.md`) therefore classifies S3 as the single **PLANNED** seam (evidence/batch artifacts with `content_hash` integrity; `storage_path: str # local path or S3 URI` in `add-compute-runtime` design) and all other AWS services as `NOT REQUIRED` until gated.

## Goals / Non-Goals

**Goals:** Prove the single S3 infrastructure contract via MiniStack without moving financial truth into S3, without giving the LLM arbitrary S3 access, and without weakening P3/P4 invariants (`P4 adds cognition without changing P3 control semantics`). Keep `ci.yml` fast; `integration.yml` carries the postgres-gated and now ministack-gated suites; `pytest -m ministack` is the only Docker-requiring command.

**Non-Goals:** No `SQS`/`SNS`/`EventBridge`/`DynamoDB`/`StepFunctions`/`SecretsManager`/`CloudWatch` adapter or test in this change. No production `boto3` default dep (test-only `ministack` group, gated). No agent/LLM/persistence redesign. No legacy COBOL yet — S3 buckets are for future batch exchange only.

## Decisions

**Decision 1 — Endpoint abstraction in `shared/aws/config.py`, not scattered literals.**
*Why:* host (`http://localhost:4566`) vs container (`http://ministack:4566`) endpoints are a single config seam; tests and compose both read `AwsSettings.aws_endpoint_url`. `is_ministack`/`container_endpoint()`/`host_endpoint()` make the choice explicit and testable. Test creds `test/test` in `us-east-1` never use real secrets.

**Decision 2 — Domain port in `finance/object_store` with tenant-prefix isolation before network.**
*Why:* `ObjectStorePort` with `FakeS3` (in-memory dict, hash-checked) + `S3Adapter` (boto3 via `AwsSettings`) share the exact `put/get/exists/delete` contract plus `ObjectMeta(content_hash=sha256, content_length, tenant_id)`. Tenant isolation (`{tenant_id}/...` prefix) is enforced before any boto3 call — wrong-tenant attempts raise `TenantIsolationError` without touching the backing store, matching `TenantAuthMiddleware` + RLS expectations.

**Decision 3 — LocalStack `localstack/localstack:3.8` pinned, `SERVICES=s3` only.**
*Why:* Pinned image (not `:latest`) with minimal `SERVICES=s3` keeps the contract surface auditable and the docker topology `postgres + ministack` (plus `postgres + app + test` in `docker-compose.test.yml`). No redis/qdrant/redpanda in ministack compose.

**Decision 4 — `Fake` contract is the fast gate; `MiniStack` contract is the infrastructure gate.**
*Why:* `tests/unit/object_store/test_s3_contract_fake.py` (11 tests, zero-network, fast) proves basic/integrity/idempotency/tenant-isolation/failure/correlation/batch-idempotency. `tests/ministack/test_s3_ministack.py` (gated `pytest -m ministack`) re-proves the same contract against real LocalStack plus wrong-bucket, invalid-credential (xfail for LocalStack permissiveness), crash-after-commit, at-least-once duplicate, and host-vs-container config. Skipped when `not _ministack_reachable()` — never counted as pass.

**Decision 5 — Idempotent bucket init via `scripts/ministack_init.py`.**
*Why:* `head_bucket` then `create_bucket` (with `us-east-1` special case and `BucketAlreadyOwnedByYou` race handling) makes init safe to run twice without duplicating resources.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Over-scoping MiniStack (SQS/SNS added without a seam) | Seam audit gates every service as `NOT REQUIRED`; this change explicitly omits them; queue gate remains `p99 latency OR crash-after-commit leaves RECEIVED OR poison→DLQ` |
| MiniStack unavailable treated as pass | `pytest -m ministack` healthcheck + `init` + explicit skip reason; CI job requires both postgres and localstack healthchecks before running tests |
| S3 becomes source of truth | Port docs and spec state *PostgreSQL remains the financial/idempotency authority; S3 is transport/artifact only*; no LLM path retrieves arbitrary S3 objects |
| Credential leakage | `shared/aws/config.py` test-only creds; adapter errors never include `AWS`/`secret`/`access` literals; `test_security_no_credential_leak_in_exception` proves it |
| Unpinned LocalStack image drift | `localstack/localstack:3.8` pinned in both `docker-compose.ministack.yml` and `integration.yml` (update only via PR) |

## Migration Plan

1. Merge this change (seam audit + lifecycle + port + Fake + adapter + contracts + CI job) after `openspec validate --strict` + `ruff`/`mypy` + `pytest -m "not live_llm"` + Docker-checked `pytest -m ministack` when compose is up.
2. Buckets are `-test` suffixed and test-only; no production bucket migration.
3. Rollback is `git revert` of the `finance/object_store` + `shared/aws` + compose/init/test/CI commits; no DB migration to revert.

## Open Questions

- Future legacy batch bridge: one outbound + one result bucket per tenant is sufficient for this phase; do we later need a separate `S3Adapter` bucket per case type?
- SQS queue seam: which future test will first demonstrate the queue gate (p99/RECEIVED-poison) that justifies `QueuePort` + `boto3` as a prod dep?
