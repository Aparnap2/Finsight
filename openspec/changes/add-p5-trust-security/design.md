# Design: P5 Trust, Security, Grounding & Agent Evaluation

## Context

P4 `1d0005b` (deterministic financial core, bounded cognition, `LLMProvider` thin SDKs, 5-tool allowlist, `InvestigationPlan` typed, `Verifier` 6 stages, `CapabilityExecutor` re-checks, `Policy` 7-gate pure, `ExceptionAggregate` CAS, sandbox+post-verify) + MiniStack/S3 `e1a839a` (tenant-prefixed `finance/object_store` with `FakeS3`+`S3Adapter` via `shared/aws/config.py` host `localhost:4566` vs container `ministack:4566`, `docker-compose.ministack.yml` `localstack:3.8 SERVICES=s3`, `pytest -m ministack`). `P5_TRUST_SECURITY_GAP_ANALYSIS.md` shows missing trust boundary, context assembly, grounding ladder, prompt-injection corpus, PII/secret pipeline, trajectory harness, observability correlation.

## Goals / Non-Goals

**Goals:** Make the trust boundary explicit, testable, observable, and adversarially resistant while preserving `Deterministic system decides, Agent reasons, External systems remain authoritative, Human remains accountable` and `UNTRUSTED INPUT → VALIDATION → CANONICAL → DETERMINISTIC POLICY → AUTHORIZED CAPABILITY` (never `UNTRUSTED → LLM → EXECUTE`). Every material claim traceable, failures recoverable, trajectory observable.

**Non-Goals:** No generic chatbot/swarm/autonomous finance, no `SQS`/`SNS`/`EventBridge`/`DynamoDB` until queue gate, no full COBOL bridge in first slice (protocol only), no `Langfuse` as core dependency, no financial truth into S3.

## Decisions

**Decision 1 — Context assembly is the deterministic trust boundary, not the prompt.**
*Why:* `agents/investigation/request.py` already enforces `exception_id`, `evidence_ids` (unique/bounded), `capability_allowlist` (duplicate-free subset of frozen allowlist), `MAX_CONTEXT_CHARS=4000` truncation. P5 adds required `tenant_id`/`actor` and per-tenant evidence scope plus provenance-preserving `allowlisted evidence` (bounded text, `tenant_id` from `TenantAuthMiddleware`/`resolve_tenant()` trusted server-side state, never LLM/body-chosen). Alternative `apps/api/middleware.py` alone rejected — evidence retrieval and LLM context also need tenant binding.

**Decision 2 — Reuse existing primitives, harden them.**
*Why:* `finance/evidence/models.py:EvidenceItem`, `finance/object_store/port.py:ObjectMeta` (hash), `agents/verification/verifier.py` (pure, total), `agents/capabilities/executor.py` (allowlist, bounded args, dedup), `shared/tracing/*` (`TracerProtocol` credential-safe, `NoOp`/`Langfuse` lazy), `shared/llm/*` (3-call budget, `Bearer redacted`), `apps/api/webhooks.py:_audit` already exist — duplication would create second sources of truth. Hardening path: add `tenant/case scope/argument schema/input-output size/timeout/credential/resource identity` checks to `CapabilityExecutor`, ladder tests to `Verifier`, `retained/redacted/hashed/excluded` matrix to `provider → ... → audit` trace.

**Decision 3 — Prompt injection via corpus, not system prompt.**
*Why:* `rg -n "prompt injection"` is 0 today; `agents/investigation/plan.py` already treats `evidence_required` as DATA. Corpus `tests/fixtures/security/prompt_injection/` (Gmail/Sheets/legacy/tool results/S3/case notes, `ignore prior instructions/...`) verified as *preserved as evidence, never executed, never alters authorization/policy/state* — deterministic gate, not prompt.

**Decision 4 — Observability abstraction before Langfuse.**
*Why:* `shared/tracing/` seam already exists (`protocol.py` credential-safe, `langfuse_tracer.py` lazy + `_truncate`). Evaluate whether `case → context → planner → LLM → verifier → capability → result → replan → policy → approval → execution → verification` with `correlation_id`/`tenant-safe`/`case`/`timestamp`/`latency`/`status` can be satisfied by wiring `TracerProtocol` through `Planner`+`Executor`+`Verifier`; if gaps, add adapter `FinSight orchestration → observability abstraction → Langfuse adapter` (optional), never `Langfuse → authorization → execution`.

**Decision 5 — Legacy protocol first, via S3 buckets.**
*Why:* MiniStack S3 buckets `finsight-legacy-outbound-test`/`result-test` already exist as `OUTBOUND → legacy processing → RESULT` without HTTP. `docs/architecture/LEGACY_BATCH_PROTOCOL.md` defines `file/batch identity, schema, field positions, version, sequence, control total, checksum/hash, accepted/rejected, partial, duplicate, result/retry/timeout` before any COBOL — protocol is the contract, S3 is transport, PostgreSQL remains authority.

**Decision 6 — Evaluation as first-class harness.**
*Why:* `shared/harness` or `agents/trajectory/` with `Fake`/`Replay`/`Live`/`E2E` (FakeLLM+Fake evidence+Fake capabilities; recorded `LLM responses`+real verifier/capabilities; real Groq+real guardrails; real app+postgres+MiniStack) and journal `INPUT → MODEL OUTPUT → VERIFIER → TOOL → RESULT → NEXT OUTPUT → FINAL` makes grounding/investigation/security/control/financial/reliability dimensions measurable without putting `live_llm` in normal CI (`pytest -m "not live_llm"` default, `FINSIGHT_ALLOW_LIVE_LLM=1` gated).

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Over-scoping P5 (swarm, SQS, full legacy) | `Explicit non-goals` + `reuse existing primitives` + queue gate; COBOL deferred to protocol |
| Tenant leakage via LLM context | `InvestigationRequest` tenant-required + `evidence retrieval` tenant-filtered + `ObjectStorePort` prefix + `Verifier` tenant-owned check + `positive/negative/adversarial` matrix |
| Credential/PII in traces/logs/audit/LLM | `retained/redacted/hashed/excluded` matrix + `rg` gate + `Bearer redacted` already + `observability payload discipline` test (no unrestricted `Gmail body`/`Sheets free text` in spans) |
| Prompt injection via tool-result | Corpus includes `tool results`/`provider metadata`/`S3 objects`; `CapabilityExecutor` preserves as data, no new tool call |
| Langfuse becomes authority | `observability abstraction` decision: Langfuse adapter optional, never `Langfuse → execution`; evaluate `shared/tracing/` first |
| Golden dataset drift | `evaluation` spec seeds from `docs/08-evaluation/Golden Datasets.md` + P5 cases `happy/timing/fee/duplicate/legacy rejection/ambiguous/conflicting/prompt injection/cross-tenant/malformed/partial/timeout/UNKNOWN` with `input/expected evidence/safe/prohibited/terminal` |

## Migration Plan

1. Merge architecture checkpoint (gap analysis + this delta, no behavioral change) after `openspec validate --strict` + `ruff`/`mypy` on touched + `pytest -m "not live_llm"` (`1870 passed`) + `pytest -m ministack` (1 passed 10 skipped when down, not pass).
2. Implement `P5-02` (`context boundary`) first — it gates all others; then `P5-03` (tenant isolation), `P5-04` (grounding), `P5-05` (prompt-injection), `P5-06` (PII/secret), `P5-07` (trajectory), `P5-08` (observability), `P5-09` (Langfuse decision), `P5-10` (legacy protocol), `P5-11` (MiniStack artifacts), `P5-12` (security regression) — one issue per PR, TDD, `openspec validate --strict` green.
3. Rollback is `git revert` of issue commits; no DB migration in checkpoint (next issues add `tenant`/`evidence` fields only via additive migrations).
