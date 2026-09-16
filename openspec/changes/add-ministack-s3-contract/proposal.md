# Proposal: MiniStack S3 Contract — LocalStack S3 for Evidence/Batch Artifacts

## Why

At `finsight-p4-complete` there is **0 actual AWS production seam**: no `boto3`, no `S3`/`SQS`/`SNS`/`EventBridge`/`DynamoDB` client, and no `QueuePort` in `apps/ shared/ finance/ agents/ tests/` (verified by `rg` over the repo and `pyproject.toml` with no `boto3` dep; `docker-compose.test.yml` comment: *no queue seam exists*). Per the mandatory rule *an emulator is justified only when a real seam needs contract testing*, adding a full AWS emulator suite would be decoration.

One seam is **PLANNED and minimal-justified**: S3 object-store for evidence/batch artifacts (`finance/evidence/models.py` immutable DB rows today; large JSON/Parquet artifacts and future legacy batch files are natural S3 objects with `content_hash` integrity — see `openspec/changes/add-compute-runtime/design.md:332` `storage_path: str # local path or S3 URI` and seam audit `docs/architecture/MINISTACK_SEAM_AUDIT.md`). This proposal introduces the single justified S3 contract via MiniStack/LocalStack, test-only, without moving financial truth into S3.

## What Changes

- **No new production financial path, no LLM authority change, no P3/P4 invariant weakened.** PostgreSQL remains the financial/idempotency authority; S3 is transport/artifact store only; the LLM never retrieves arbitrary S3 objects.
- Adds `finance/object_store` domain port (`FakeS3` in-memory + `S3Adapter` boto3 via `shared/aws/config.py` endpoint abstraction), `shared/aws/config.py` host-vs-container endpoint selection, `docker-compose.ministack.yml` (LocalStack `localstack/localstack:3.8`, `SERVICES=s3`, healthcheck), `scripts/ministack_init.py` idempotent bucket init (`finsight-evidence-test`, `finsight-legacy-outbound-test`, `finsight-legacy-result-test`), and `tests/unit/object_store` + `tests/ministack` contract suites.
- Adds `pytest` marker `ministack` (test-only, excluded from `ci.yml`/`pytest -m "not live_llm"`), `pyproject:dependency-groups.ministack` (`boto3`, `botocore`), `Makefile` targets `ministack-up/init/test/down`, and a `ministack` job in `.github/workflows/integration.yml` (postgres + localstack, `AWS_ENDPOINT_URL=http://localhost:4566`, init then `pytest -m ministack`).
- **Explicitly NOT added:** `QueuePort`/`boto3` as default prod dep, MiniStack `SQS`/`SNS`/`EventBridge`/`DynamoDB`/`StepFunctions`/`SecretsManager`/`CloudWatch`, Redis/Qdrant as MiniStack services — all classified `NOT REQUIRED` in the seam audit until a failing test proves the queue gate.

## Impact

- **Affected specs (ADDED):** `object-store` capability — S3 contract (basic/integrity/idempotency/tenant isolation/failure/crash/at-least-once/correlation).
- **Affected code:**
  - `finance/object_store/{port,errors,fake,s3_adapter}.py` — domain port + adapters (imports nothing from `apps/`; `finance` ← `shared` only).
  - `shared/aws/{config}.py` — endpoint abstraction (`http://localhost:4566` host vs `http://ministack:4566` container, test creds `test/test`, `us-east-1`).
  - `docker-compose.ministack.yml`, `scripts/ministack_init.py`, `tests/{unit/object_store,ministack}/`, `.github/workflows/integration.yml`, `Makefile`, `pyproject.toml`.
- **Non-goals:** No SQS, no queue seam, no production `boto3` unless gated; no financial truth moved into S3; no agent/LLM change.
