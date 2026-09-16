# MiniStack Seam Audit — FinSight P4 Checkpoint

> **Scope:** Repository-grounded audit at `finsight-p4-complete` (`1d0005b`) on branch `feat/finsight-ministack-integration`.
> **Rule:** *An AWS emulator is justified only when the application has a real AWS integration seam that needs contract testing.*
> **Method:** `rg -n "boto3|botocore|S3|SQS|SNS|EventBridge|DynamoDB|StepFunctions|SecretsManager|CloudWatch|AWS_ENDPOINT_URL" .` over `apps/ shared/ finance/ agents/ tests/` (excluding `.venv`, `docs/agent-context`), plus `pyproject.toml`, `docker-compose*`, `.github/workflows/`, `Makefile`.

---

## Result summary

**Actual production AWS seams in current code: 0.**

No `boto3`/`botocore` import, no `AWS_ENDPOINT_URL`, no `S3`/`SQS`/`SNS`/`EventBridge`/`DynamoDB`/`StepFunctions`/`SecretsManager` client, and no `QueuePort`/`SQSAdapter`/`S3Adapter` domain port exists in `apps/`, `shared/`, `finance/`, `agents/`, `tests/` at this checkpoint. Evidence is in PostgreSQL.

**Planned seam (justified, minimal): S3 object-store for evidence/batch artifacts (1).**
All other AWS services are `NOT REQUIRED` at this checkpoint.

This is consistent with the repository's own statements:
- `docker-compose.test.yml:1-3` — *"No MiniStack services here: no redis, qdrant, kafka/redpanda, temporal, jaeger, or litellm (no queue seam exists). Do NOT extend this file with dev-stack services."*
- `Makefile:make test-integration` — gated compose runs only `postgres + app + test`; no MiniStack.
- `openspec/changes/add-finsight-v2-reconciliation/design.md:10` — MiniStack noted as *"only for AWS primitives (SQS/SNS/S3-equivalent webhook ingress and object artifacts)"* but with no implementation at P4 — design intent, not code.
- `pyproject.toml:dependencies` — no `boto3`, no `aioboto3`, no `moto`, no `localstack` declared.

Therefore MiniStack — if introduced — must be **TEST/CONTRACT ONLY, single-service, never a production replacement**.

---

## Classification per AWS service

| Service | Classification | Evidence | Justification for MiniStack |
|---------|----------------|----------|-----------------------------|
| **S3 (object store)** | **PLANNED PRODUCTION SEAM** | No S3 client in code today. Planned in `openspec/changes/add-compute-runtime/design.md:332` (`storage_path: str # local path or S3 URI`) and `docs/09-platform/compute-runtime.md:1656` (Export artifact → Configurable (S3, volume) per tenant). Evidence bundles today are immutable DB rows (`finance/evidence/models.py`), but large JSON/Parquet artifacts and future legacy batch files are natural S3 objects with content-hash integrity. | **Justified, minimal.** One S3 adapter with tenant-scoped keys, content-hash preservation, and `shared/config/aws.py`-style endpoint abstraction allows testing the *infrastructure contract* (bucket/key existence, tenant isolation, content-length/hash, idempotent put) without moving financial truth into S3. No other AWS service reaches this bar. |
| **SQS** | **NOT REQUIRED** | No `SQS`, `QueuePort`, `boto3` in `apps/ shared/ finance/ agents/ tests/`. `docker-compose.test.yml` comment explicitly says *no queue seam exists*. | Rejected per gate: `p99 latency requires async acknowledgement/reconciliation OR crash-after-commit leaves RECEIVED permanently OR poison messages require DLQ/redrive` — none demonstrated by a failing test at this checkpoint. Adding `boto3` + LocalStack SQS now would be decoration. `NO QueuePort / NO boto3 / NO MiniStack SQS` until gated. |
| **SNS** | **NOT REQUIRED** | Same as SQS — zero references in domain/test code. | Not justified; no pub/sub domain port exists. |
| **EventBridge** | **NOT REQUIRED** | Zero references. | Not justified; webhook ingress authenticates via HMAC in `apps/api/webhooks.py`, not via EventBridge. |
| **DynamoDB** | **NOT REQUIRED** | Zero references. PostgreSQL is the sole persistence seam (`finance/exceptions/models.py`, `shared/models/database.py`). | Not justified; no key-value seam exists. |
| **StepFunctions** | **NOT REQUIRED** | Zero references. Orchestration is deterministic Python (`agents/orchestrator/orchestrator.py`, `finance/exceptions/aggregate.py` CAS). | Not justified; would violate `P4 adds cognition without changing P3 control semantics`. |
| **SecretsManager** | **NOT REQUIRED** | No `SecretsManager` client. Secrets via `.env` + `pydantic-settings` (`shared/config.py:postgres_uri`, `shared/llm/config.py` api keys). | Not justified at this checkpoint; env-based secrets with no AWS retrieval seam. |
| **CloudWatch** | **NOT REQUIRED** | No `CloudWatch` client. Observability is `shared/tracing/` (NoOp/Langfuse) + `docs/09-platform/*` docs, not AWS metrics. | Not justified for contract testing. |

---

## What the audit found (verbatim search evidence)

```
# Host code (apps/ shared/ finance/ agents/ tests/) — 0 hits for boto3/botocore/AWS_ENDPOINT/SQS/S3Client
rg -n "boto3|botocore|AWS_ENDPOINT|SQS|S3Client|DynamoDB" apps/ shared/ finance/ agents/ tests/  → 0 lines

# Including docs/openspec — only hits are:
openspec/changes/add-finsight-v2-reconciliation/design.md:10  — MiniStack only AWS primitives (comment, not code)
openspec/changes/add-compute-runtime/design.md:332            — storage_path: str # local path or S3 URI (planned)
docs/09-platform/compute-runtime.md:1656                       — Export artifact | Configurable (S3, volume)
docs/12-database/security.md:310-315                            — boto3 example in docs, not app code
pyproject.toml                                                  — no boto3/aioboto3/moto/localstack

# Docker topology
docker-compose.yml        — postgres:17, redis:7, qdrant:v1.7, redpanda:v24.2 (no S3/SQS)
docker-compose.test.yml   — postgres:17 + app + test only; comment: "No MiniStack services here"
docker-compose.langfuse.yml — langfuse + postgres:17 (port 5433) — observability only
docker-compose.override.yml — dev override, no AWS
.github/workflows/*.yml  — postgres:17 service only; no LocalStack/MiniStack service
Makefile                  — test-integration → docker compose -f docker-compose.test.yml (postgres-gated only)
```

---

## Planned S3 seam — minimal contract shape

If S3 is introduced, its domain port and contract must be **this small and no larger**:

```
Domain port (finance/object_store/port.py)
    ├── Fake implementation (tests/fakes/fake_s3.py) — in-memory dict, hash-checked
    ├── MiniStack implementation (finance/object_store/s3_adapter.py) — boto3 via AWS_ENDPOINT_URL
    └── Real AWS implementation — same port, same boto3, real endpoint (staging only)

Contract (identical for Fake and MiniStack):
    put_object(key, bytes, content_type) -> etag/content_hash
    get_object(key) -> bytes + metadata
    exists(key) -> bool
    delete(key)  # cleanup only
    + tenant isolation: tenant A key prefix never readable as tenant B

Invariants proven by contract tests:
    - content hash preserved, content-length correct
    - metadata preserved
    - idempotent put with same key+bytes → same hash, single logical object
    - tenant A's prefix is invisible to tenant B (wrong bucket/key/tenant → 404/bounded error)
    - missing object → bounded failure (no silent fallback)
    - malformed content (if batch-file mode) → quarantined/bounded error
    - correlation ID (case id) preserved from put through retrieval
    - no LLM path retrieves arbitrary S3 objects (evidence retriever is allowlisted only)
```

Any second S3 bucket or prefix beyond `finsight-evidence-test` per tenant is out of scope for this audit.

---

## What is NOT justified (and therefore NOT created)

- `QueuePort` / `boto3` as a production dependency — until the queue gate fires.
- `MiniStack SQS` service in `docker-compose.ministack.yml` — no SQS seam.
- `SNS`/`EventBridge`/`DynamoDB`/`StepFunctions` adapters, resources, or tests.
- `SecretsManager`/`CloudWatch` emulators.
- Redis/Qdrant/Kafka as MiniStack services — they are real `docker-compose.yml` services, not AWS emulators.

---

## Implications for this phase

- The single justified MiniStack service is **LocalStack S3** (pinned `localstack/localstack:3.8.0` — latest stable at audit time; verify before pinning).
- All MiniStack artifacts must be `TEST-ONLY` (`-test` bucket suffixes, test credentials) and gated `pytest -m ministack` — never in `pytest -m "not live_llm"` or `ci.yml`.
- The legacy batch bridge (`S3 outbound bucket → transfer → COBOL → S3 result bucket`) is modeled as *one* outbound + *one* result bucket per tenant in tests, not as a separate AWS service set.
- SQS contract tests are explicitly `NOT REQUIRED` and must not be introduced in this phase; the failure matrix therefore omits SQS-specific rows until the queue gate fires.

---

*Evidence base: `rg` output above, `pyproject.toml:dependencies`, `docker-compose.yml`, `docker-compose.test.yml:1-3`, `docker-compose.langfuse.yml`, `.github/workflows/integration.yml`, `Makefile:test-integration`, `openSpec` deltas, `finance/evidence/models.py`, `apps/api/webhooks.py`, `shared/config.py`, `shared/llm/config.py`, `agents/orchestrator/orchestrator.py`.*
