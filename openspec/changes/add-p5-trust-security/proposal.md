# Proposal: P5 Trust, Security, Grounding & Agent Evaluation

## Why

FinSight P4 + MiniStack/S3 (tag `finsight-p4-ministack-s3` at `594c60c`, P4 `1d0005b` + MiniStack `e1a839a` via PR #31) proves bounded cognition (LLM typed candidates only, deterministic gates own financial truth) and a single justified S3 artifact seam (tenant-prefixed, hash-checked, `FakeS3` + `S3Adapter` via `shared/aws/config.py`, `pytest -m ministack`). What is not yet proven is the **trust boundary itself**: can the system reason over heterogeneous, partially untrusted evidence (Gmail/Sheets/Slack/legacy free text, tool-result free text, provider metadata, S3 objects) while never becoming the authority over financial state, tenant access, credentials, or policy? `docs/architecture/P5_TRUST_SECURITY_GAP_ANALYSIS.md` (19 sections, repo-grounded) shows missing controls for tenant isolation beyond webhook/middleware, context assembly, prompt/ indirect prompt injection, grounding ladder, PII/secret pipeline, and agent trajectory observability.

## What Changes

- **No new financial path, no LLM authority, no P3/P4 invariant weakened.** PostgreSQL remains financial/idempotency authority; `P4 adds cognition without changing P3 control semantics`; `LLM produces typed candidates, deterministic software decides admissibility`.
- Adds 5 capability deltas: `trust-security` (trust boundaries, tenant isolation, PII/secret policy, security invariants, context contract, prompt-injection behavior), `grounding` (evidence model, claim verification, provenance), `observability` (tracing seam + trajectory contract + correlation), `legacy-protocol` (file/batch identity, sequence, control total, duplicate/partial/result semantics, no HTTP), `evaluation` (golden datasets, dimensions, property-based tests).
- Introduces no new AWS service: MiniStack S3 is reused as `evidence artifacts / legacy outbound+result files` (transport only); `SQS` stays closed until queue gate fires.
- Reuses existing primitives: `finance/evidence/models.py:EvidenceItem`, `finance/object_store/port.py:ObjectMeta`, `shared/aws/config.py`, `shared/tracing/*`, `shared/llm/*` (`LLMProvider` thin SDKs, `Fake`/`Replay`, 3-call budget), `agents/investigation/*` (allowlist, bounded prompt), `agents/capabilities/*`, `agents/verification/verifier.py`, `apps/api/{middleware,webhooks}.py` (HMAC, RLS, `_audit`), `pyproject.toml` markers (`live_llm/evals/integration/ministack`).

## Impact

- **Affected specs (ADDED):** `trust-security`, `grounding`, `observability`, `legacy-protocol`, `evaluation`.
- **Affected code (future, after approval, one issue at a time):** `agents/investigation/request.py` (context assembly boundary), `finance/evidence/`, `finance/object_store/`, `agents/capabilities/executor.py`, `agents/verification/verifier.py`, `shared/tracing/`, new `shared/harness` or `agents/trajectory/`, `docs/architecture/LEGACY_BATCH_PROTOCOL.md`, `tests/{unit,ministack,integration}/`, `tests/fixtures/security/prompt_injection/`, `tests/evals/p5/` golden datasets, `pyproject.toml` `hypothesis` already in `dev`.
- **Non-goals in first slice:** Full COBOL bridge, `SQS`/`SNS`/`EventBridge`/`DynamoDB`, `Langfuse` as core dependency, generic chatbot/AI CFO/swarm, moving financial truth into S3.
