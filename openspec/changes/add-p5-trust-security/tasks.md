# Tasks: add-p5-trust-security

> Architecture checkpoint first, no behavioral production change. `openspec validate add-p5-trust-security --strict` green before merge.

## 0. Architecture checkpoint (this PR)

- [x] 0.1 Verify PR #31 merged (`finsight-p4-ministack-s3` at `594c60c`), branch `feat/finsight-p5-trust-security` from stable checkpoint
- [x] 0.2 Repository archaeology (`rg -n "tenant|auth|policy|evidence|claim|ground|audit|secret|credential|PII|redact|trace|observability|correlation|capability|tool|prompt"` + `rg -n "boto3|S3|AWS_ENDPOINT_URL|ObjectStorePort"`)
- [x] 0.3 Produce `docs/architecture/P5_TRUST_SECURITY_GAP_ANALYSIS.md` (19 sections, repo-grounded, reuse existing primitives)
- [x] 0.4 Add `openspec/changes/add-p5-trust-security/{proposal,tasks,design,specs/*}` with 5 capability deltas, `openspec validate --strict` green
- [x] 0.5 Create GitHub Issues P5-01..P5-12 from gap analysis, baseline regression `pytest -m "not live_llm"` + `pytest -m ministack` (skip when MiniStack down, not pass)

## 1. Implementation (one issue at a time, TDD, after approval)

- [ ] P5-01 trust model — `docs/architecture/TRUST_MODEL.md` + `finance/object_store` lineage `raw → hash → immutable ref → canonical → claim`
- [ ] P5-02 context boundary — deterministic `tenant_id/case/actor` assembly in `agents/investigation/request.py` (+ `shared/context/boundary.py` if needed), `MAX_CONTEXT_CHARS` + tenant-scoped `allowlisted evidence` bounded, no arbitrary DB/S3, unit-testable
- [ ] P5-03 tenant isolation — `HTTP → case lookup → evidence retrieval → capability execution → S3 → LLM context → proposal → execution → audit` proofs, `cross-tenant evidence/S3/capability/case` fail-closed
- [ ] P5-04 grounding hardening — `FACTUAL → must cite evidence → exists → belongs to tenant → provenance valid → supported → VERIFIED`, `HYPOTHESIS != FACT != VERIFIED`, `confidence != authority`
- [ ] P5-05 prompt-injection suite — `tests/fixtures/security/prompt_injection/` (Gmail/Sheets/legacy/provider metadata/tool results/S3/case notes) with `ignore prior instructions/execute refund/approve proposal/send credentials/change tenant/read another case/call unapproved tool/override policy`, preserved as evidence
- [ ] P5-06 PII/secret controls — `provider → adapter → canonical → evidence → context → LLM → traces → logs → audit` matrix `retained/redacted/hashed/excluded`, `rg` gate, `never LLM context/agent output/Langfuse/logs/audit`
- [ ] P5-07 trajectory harness — `shared/harness` or `agents/trajectory/` with `Fake/Replay/Live/E2E`, journal `INPUT → MODEL OUTPUT → VERIFIER → TOOL → RESULT → NEXT OUTPUT → FINAL`, `FINSIGHT_ALLOW_LIVE_LLM=1` gated
- [ ] P5-08 observability abstraction — `case → context assembly → planner → LLM generation → verifier → capability call → result → replan → final candidate → policy → approval → execution → verification` trace with `correlation_id/tenant-safe/case/timestamp/latency/status`, no unrestricted payload
- [ ] P5-09 Langfuse adapter decision — evaluate `shared/tracing/` vs required trace; if gaps, wrap as optional adapter (`FinSight orchestration → observability abstraction → Langfuse adapter`), not core
- [ ] P5-10 legacy protocol — `docs/architecture/LEGACY_BATCH_PROTOCOL.md` (`file/batch identity, schema, field positions, version, sequence, control total, checksum/hash, accepted/rejected, partial, duplicate, result/retry/timeout`, `OUTBOUND → RESULT` without HTTP) via `finance/object_store` buckets
- [ ] P5-11 MiniStack artifact tests — `evidence artifacts / legacy outbound+result files` via `finance/object_store` + `tests/ministack`, not PostgreSQL state, `pytest -m ministack` (postgres+localstack healthcheck)
- [ ] P5-12 security regression — adversarial matrix (§19) `cross-tenant/S3/prompt injection/tool injection/arbitrary SQL/URL/credential/PII leak/fake approval/proposal tampering/stale/state bypass/duplicate/provider UNKNOWN/legacy duplicate/invalid control total/partial/malicious tool/oversized context-output` with `positive/negative/adversarial`

## 2. Validation per issue

- [ ] RED → minimum change → GREEN → refactor → targeted tests → `pytest -m "not live_llm"` baseline (`1870 passed` + new) → `pytest -m ministack` when Docker (skip not pass) → `ruff check` on touched → `mypy` on touched → `openspec validate --strict`
