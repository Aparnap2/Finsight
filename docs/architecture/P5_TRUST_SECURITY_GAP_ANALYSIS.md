# P5 Trust, Security, Grounding & Agent Evaluation — Gap Analysis

> Branch `feat/finsight-p5-trust-security` from `finsight-p4-ministack-s3` (`594c60c`, P4 `1d0005b` + MiniStack/S3 `e1a839a` via PR #31). Repo-grounded at P4+MiniStack checkpoint. Do not claim a control exists when `rg` and file reads prove otherwise. `P4 adds cognition without changing P3 control semantics` remains frozen.

---

## 1. Current trust model

**Authoritative (only these decide financial truth):** Provider-confirmed state (`finance/stripe/`, `finance/accounting/`, `finance/evidence/models.py` + deterministic `finance/reconciliation/`), Accounting-confirmed state (`finance/evidence/models.py`, `finance/policy/`), Verified legacy result (future — not yet code), Deterministic financial computation (`finance/reconciliation/reconciler.py` pure, no LLM; `Decimal` money in `finance/reconciliation/models.py`), PostgreSQL transaction state (`finance/exceptions/aggregate.py` CAS, `shared/models/database.py`, `shared/config/config.py:postgres_uri`), Policy decision (`finance/policy/execution_policy.py` 7-gate pure, no LLM), Human approval (`finance/exceptions/aggregate.py` single-terminal `ApprovalPin`, `finance/proposals/proposal.py:verify_hash`).

**Trusted execution infra:** Deterministic domain services (`finance/` no `apps`/`agents` import), Capability executor (`agents/capabilities/executor.py` re-checks shape, tenant, timeout before any adapter), Execution service (`finance/execution/executor.py` sandbox + post-verify), Verification service (`agents/verification/verifier.py` 6 stages, pure), Audit service (`apps/api/webhooks.py:_audit` + aggregate `state_version`).

**Conditionally trusted external sources:** Razorpay (webhook HMAC via `apps/api/webhooks.py:verify_stripe_signature`), QuickBooks (`finance/accounting/mock.py`), Google Sheets (`finance/ingestion/sheets_adapter.py`), Gmail (`search_gmail` capability), Slack, Legacy financial system (future file/batch, not HTTP), S3 (`finance/object_store/s3_adapter.py`, `shared/aws/config.py`) — each authoritative for particular facts (e.g., Stripe `provider_event_id`) but free text never trusted as instructions.

**Untrusted:** LLM output (`shared/llm/`, `agents/investigation/plan.py` typed candidates only), Gmail body, Sheets free text, Slack free text, Legacy rejection descriptions, retrieved documents, customer-provided strings, provider metadata, tool-result free text — all must be treated as DATA, never authority.

**Gap:** Trust taxonomy is implicit in code (e.g., `plan.py` never-authorize, `s3_adapter` tenant check before network) but not documented as an explicit `docs/architecture/TRUST_MODEL.md` with classification per data flow; free-text sources lack a unified "untrusted-content fence."

## 2. Existing tenant isolation

- **HTTP → case lookup → evidence retrieval → capability execution → S3 → LLM context → proposal → execution → audit** is partially isolated:
  - `apps/api/webhooks.py:resolve_tenant()` via trusted `STRIPE_TENANT_MAP` (`stripe_account -> tenant_id`, env-only, NO default tenant, unknown/ambiguous → quarantine, persisted under `wh___quarantine` with `idempotency_key` sha256). Verified + test `tests/integration/test_stripe_tenant_isolation.py`.
  - `apps/api/middleware.py:TenantAuthMiddleware` resolves `X-Tenant-ID`/`X-User-ID`/`X-Role`, validates against `finplatform.rbac.matrix.ROLE_PERMISSIONS`, attaches `request.state.actor`, sets `SELECT set_config('app.tenant_id', :tenant_id, true)` for RLS (DI `session_factory`, health excluded, webhooks use HMAC not headers).
  - `finance/exceptions/aggregate.py:ExceptionAggregate` carries `tenant_id` indexed column (`finance/exceptions/models.py:37,62`); `finance/policy` checks `tenant_id` on triple.
  - `finance/object_store/{fake,s3_adapter}.py` enforces `{tenant_id}/...` prefix before any store/network call → `TenantIsolationError` without touching backing store (`tests/unit/object_store` + `tests/ministack/test_s3_ministack.py` cross-tenant).
  - `agents/capabilities/executor.py:_TENANT_ARG_KEYS = frozenset({"tenant_id","tenant"})` re-checks tenant args per call, whole-run rejection, zero partial execution.

- **Missing:** Uniform tenant context assembly for LLM — `agents/investigation/request.py` (`InvestigationRequest` with `exception_id/exception_type/evidence_ids/context_window/capability_allowlist/round_budget`) validates `exception_id`, `evidence_ids` (unique, bounded, `MAX_EVIDENCE_ID_CHARS`), `capability_allowlist` subset of frozen `FROZEN_CAPABILITY_ALLOWLIST`, `MAX_CONTEXT_CHARS=4000` truncation, but does **not** carry `tenant_id` as required field nor enforce per-tenant evidence scope; evidence retrieval (`finance/evidence/`, `agents/capabilities/capabilities.py:AdapterBundle`) not yet proven tenant-filtered at the capability result level; S3 evidence artifact TenantIsolation is proven, but DB evidence (`Actual/BudgetLine`) tenant filtering not yet covered by a dedicated cross-tenant test.

## 3. Existing authorization

- `finplatform.rbac.matrix` + `TenantAuthMiddleware` for HTTP role gating; `apps/api/webhooks.py:resolve_tenant()` for webhook tenant; `finance/policy/execution_policy.py` for execution gate (terminal `APPROVED`, pinned triple, hash integrity, sandbox-bookable, amount ceiling, balanced legs, scope agreement).

- **Missing:** Case-scoped authorization (who may operate case `CASE-1027` — owner, approver, auditor), S3 object authorization beyond prefix (no bucket policy beyond tenant prefix), capability-level authorization per role (e.g., `search_gmail` requires `analyst` role), stale-tenant-context rejection (token expired, tenant reassigned).

## 4. Existing evidence model

- `finance/evidence/models.py:EvidenceItem` (`claim`, `source_type/id`, `source_value:Decimal|None`, `supporting_metrics`, `confidence`, `assumptions/limitations`) — used by `finance/analytics/diagnostic.py:EvidenceItem` bridge and `finance/llm/response_validator.py:validate_evidence()` (min_evidence). Immutability: evidence bundle is append-only via `ExceptionAggregate.evidence_ids` sealed after `EVIDENCE_VERIFIED`; `finance/evidence/engine.py` exists but not audited here.

- For S3 artifacts: `finance/object_store/port.py:ObjectMeta` (key, `content_hash=sha256`, `content_length`, `tenant_id`) with `FakeS3`/`S3Adapter` preserving hash/length; `shared/aws/config.py` bucket names `-test` deterministic.

- **Missing:** Unified evidence envelope with `source`, `source identifier`, `tenant`, `content hash`, `retrieval time`, `provenance` (which adapter, which endpoint, which correlation_id), `immutability` (cannot mutate after `EVIDENCE_VERIFIED`); canonical extraction `raw artifact → hash → immutable reference → canonical extraction → claim/evidence relationship` not yet formalized; evidence retention vs PII redaction policy not defined.

## 5. Existing claim verification

- `agents/investigation/plan.py:InvestigationPlan` requires `evidence_required` non-blank, bounded, unique, 1..32; `CapabilityCall` ordered, allowlisted, string-only bounded args; `agents/verification/verifier.py` 6 stages (schema, allowlist, grounding, claim classification, confidence cap `0.85`, bounds) — pure, total, no LLM, no proposals, no policy changes; `finance/llm/response_validator.py:validate_evidence` enforces `min_evidence`.

- **Missing:** Grounding ladder `FACTUAL → must cite evidence → evidence exists → belongs to tenant → provenance valid → supported → VERIFIED` as a single sequenced invariant; `HYPOTHESIS != FACT != VERIFIED` and `confidence != authority` as machine-testable; claim coverage (every material claim traceable, unsupported-claim rate measured) not yet evaluated.

## 6. Existing tool/capability security

- P4 frozen allowlist `FROZEN_CAPABILITY_ALLOWLIST = ("get_stripe_payment", "get_stripe_refunds", "get_qb_transaction", "get_expected_state", "search_gmail")` in `agents/investigation/plan.py:32`; `agents/capabilities/registry.py` closed vocabulary; `agents/investigation/request.py` validates `capability_allowlist` duplicate-free subset; `agents/capabilities/executor.py` re-checks shape, allowlist, string-only bounded args, call count `MAX_CAPABILITY_CALLS=8`/`MAX_ARGS_PER_CALL=8`/`MAX_ARG_KEY_CHARS=64`/`MAX_ARG_VALUE_CHARS=512`, timeout accounting, duplicate `(capability,args)` dedup (`Deduped=True`), adapter 5xx → bounded `CapabilityFailure` as zero-row `ToolResult`, whole-run rejection on fatal.

- `agents/investigation/planner.py:render_investigation_prompt()` deterministic, bounded, allowlist snapshot; `_SYSTEM_PROMPT` rules require capability from allowlist only; `Planner` posts to `LLMProvider.generate_structured(InvestigationPlan)`.

- **Missing:** Explicit per-call validation of `tenant`, `case scope`, `argument schema`, `input size`, `output size`, `timeout`, `credential context` (no `api_key` in args), `resource identity` (e.g., `payment_id` belongs to tenant), and denials for `arbitrary SQL/HTTP/URLs/filesystem/credential-containing args/cross-tenant identifiers/oversized output`; no test that `CapabilityCall.args` containing `_tenant_id` mismatched is rejected.

## 7. Existing secret handling

- `shared/llm/config.py`, `shared/config/config.py` load secrets from `.env` only (`Settings` with `postgres_uri`, `groq_api_key`, `stripe_webhook_secret` via `STRIPE_TENANT_MAP` JSON, `openai_api_key` placeholder, `langfuse_*`); `shared/llm/*` journals carry `model/cost` only, never secrets (`shared/llm/types.py:19 evidence_ids only`, `shared/llm/groq.py:119 Authorization: Bearer redacted`, `shared/llm/fake.py:71 credential-safe`); `shared/tracing/factory.py` strips env `LANGFUSE_*`; `scripts/ministack_init.py` uses `test/test` creds; `finance/object_store` errors never include `AWS`/`secret`/`access` literals (tested `test_security_no_credential_leak_in_exception`).

- **Missing:** End-to-end trace `provider → adapter → canonical → evidence → context builder → LLM → traces → logs → audit` with explicit `retained/redacted/hashed/excluded` matrix; no automated `rg -n "api_key|secret" --glob '!*.pyc'` gate in CI; `docs/12-database/security.md:310` shows `boto3` example with real creds in docs (not code) — doc hygiene.

## 8. Existing PII handling

- `shared/models/database.py` has `Actual`/`BudgetLine` with `entity_id`, `account_id`, `amount:Decimal`; no explicit PII fields today (amounts are financial, not PII). Evidence rows carry `claim` text. `agents/investigation/request.py:6` says *no amounts beyond allowlisted evidence, no credentials* — but PII not enumerated.

- **Missing:** PII inventory (what fields are PII — `customer email`, `vendor name`, `employee id`, `account holder`), classification (`internal`/`confidential`/`restricted`), retention policy, redaction/hashing/exclusion per hop (`evidence → context → LLM → traces → logs → audit`), and a test that PII never reaches `shared/tracing` payload or `apps/api/webhooks.py:_audit` message.

## 9. Existing observability

- `shared/tracing/` seam: `protocol.py:TraceContext(trace_id)` + `TracerProtocol(trace,generation,tool,guardrail,span,flush)` (credential-safe), `noop.py:NoOpTracer` singleton, `langfuse_tracer.py:60` lazy `langfuse` import, `_truncate` bounded payload, `factory.py:create_tracer()` env-driven. Verified by `rg trace|observability`.

- **Missing:** Agent trajectory observability — no `case → context assembly → planner → LLM generation → verifier → capability call → capability result → replan → final candidate → policy → approval → execution → verification` trace with `correlation_id`/`tenant-safe identifiers`/`case identifier`/`timestamp`/`latency`/`status` as a single `trace_id` per exception; sensitive payload restriction not yet tested as `observability payload discipline` (no unrestricted `Gmail body`/`Sheets free text`/`legacy rejection` in spans).

## 10. Existing auditability

- `apps/api/webhooks.py:_audit()` appends `wh_audit_` row (never masks webhook 202), `finance/exceptions/aggregate.py` CAS (`state_version` monotonic, `expected_state_version` guard, `ALLOWED_TRANSITIONS` 21 pairs, `BANNED_TRANSITIONS` 3, `P32_TARGETS`), `finance/policy/execution_policy.py` audit on denial, `agents/capabilities/executor.py` audit note on dedup, `finance/object_store` tenant isolation audit via exception.

- **Missing:** Unified audit spine (immutable, append-only, `case → evidence → claim → proposal → approval → execution` lineage), `correlation_id` propagation from webhook `idempotency_key`/`event_id` through S3 `ObjectMeta.key` through LLM context through execution `P5` — currently S3 `key` preserves `CASE-1027` but webhook `fingerprint`/`idempotency_key` not yet linked to `S3 key` in a single query.

## 11. Existing LLM safeguards

- `shared/llm/{config,provider,fake,openai_compatible,groq,replay,types,errors}.py` — `LLMProvider` Protocol (credential-safe, `model/cost` identity), `FakeLLM`/`ReplayProvider`, `GroqProvider` thin direct SDK, header redaction, 3-call budget guard (`guarded_llm_call` with `MAX_CALLS=3`, `/tmp/llm_debug_*.json`), `litellm` present but not in domain path (P4 uses `LLMProvider` thin SDKs only, per `openspec/changes/add-finsight-v2-reconciliation/specs/llm-boundary/spec.md` framework bypass rejected).

- `agents/investigation/planner.py` 5 allowed acts (semantic interpretation, hypothesis, investigation planning, capability selection from allowlist, evidence synthesis — each typed-candidate only, no state effect), formal handoff `typed LLM output → deterministic validation (schema → authz → capability execution → evidence verification → policy → P3 proposal/approval/execution)`, 14 never-prohibitions (amounts, financial calc, state change, provider mutations, approvals, transitions, CLOSED, policy/approval bypass, idempotency keys, VERIFIED declarations, authorization override, prod/sandbox mode).

- **Missing:** Live-provider safety harness — `pytest -m "not live_llm"` default already (`pyproject.toml` markers `live_llm/evals/integration/ministack`), but `FINSIGHT_ALLOW_LIVE_LLM=1` gate for `pytest -m live_llm` not yet standardized across `tests/evals/`, and trajectory recording `INPUT → MODEL OUTPUT → VERIFIER → TOOL → RESULT → NEXT OUTPUT → FINAL` not yet first-class (`shared/llm/replay.py` exists but not `agent trajectory harness`).

## 12. Existing evaluation harness

- `pyproject.toml` markers `live_llm`, `evals`, `integration`, `ministack`; `tests/evals/llm/test_groq_smoke.py` gated `live_llm` + `FINSIGHT_ALLOW_LIVE_LLM=1`; `shared/llm/fake.py` + `replay.py`; `docs/08-evaluation/{Benchmarks,Golden Datasets,Metrics,Regression}.md` (legacy FP&A golden datasets, 3 types — not yet P5 exception datasets); `tests/evals/llm/README.md` procedure.

- **Missing:** P5 golden datasets for `happy path, timing difference, fee mismatch, refund discrepancy, duplicate payment, legacy rejection, ambiguous evidence, conflicting evidence, prompt injection, cross-tenant attack, malformed provider data, partial legacy batch, provider timeout, execution UNKNOWN` with `input state, expected evidence, expected safe behavior, expected prohibited behavior, expected terminal state`; evaluation dimensions `grounding (citation correctness, unsupported-claim rate, coverage), investigation (tool-selection precision, unnecessary calls, replan efficiency), security (prompt-injection resistance, tenant boundary, credential-leak, unauthorized capability), control integrity (policy/approval/state bypass), financial correctness (exact amounts, reconciliation, proposal, verification), reliability (duplicate/timeout/retry/unknown/legacy partial/replay)`; property-based tests (`gross - fees - refunds - adjustments = net`, `refund <= refundable`, `duplicate event != duplicate financial effect`, `same action+same idempotency key = one effect`, `closed case cannot execute`, `unverified proposal cannot execute`, `cross-tenant evidence cannot appear in context`).

## 13. Missing controls (consolidated, repo-grounded)

Input: `InvestigationRequest` lacks required `tenant_id` + actor, context `MAX_CONTEXT_CHARS=4000` truncation exists but not tenant-scoped context assembly, no per-exception-type allowed-scope map beyond allowlist subset, no `oversized context/tool output` bounded error.

Tool: allowlist closed, but not `tenant`, `case scope`, `argument schema`, `input/output size`, `timeout`, `credential context`, `resource identity` per-call validation as explicit suite.

Reasoning: 5 allowed acts handoff exists, but `HYPOTHESIS != FACT != VERIFIED` and `confidence != authority` not yet a single sequenced ladder test; prompt injection corpus not yet built — `rg -n "prompt injection"` has 0 hits in `agents/`.

Output: `evidence_required` grounding exists, but `FACTUAL must cite tenant-owned, provenance-valid, supported evidence` as one invariant not yet; `prohibited-action` attempts (approve, state transition, financial authority) not yet exhaustively tested as `control integrity`.

Execution: `finance/policy` gate exists, but `proposal tampering`, `stale proposal`, `duplicate execution`, `provider UNKNOWN` not yet adversarially tested as `finance/execution`.

Post-execution: `post-execution verification mandatory` (`I9`) but `legacy duplicate file`, `invalid control total`, `partial processing`, `malicious tool result` not yet tested for legacy+S3 path.

Systemic: PII/secret boundary `provider → adapter → canonical → evidence → context → LLM → traces → logs → audit` not yet traced with `retained/redacted/hashed/excluded` matrix; observability payload discipline not yet tested; legacy protocol `docs/architecture/LEGACY_BATCH_PROTOCOL.md` not yet created; trajectory harness not yet first-class.

## 14. Reusable components

Reuse as-is or via narrow hardening:

- `finance/reconciliation/*` (pure, `Decimal`, `MoneyDecimal` in `apps/api/schemas.py`), `finance/exceptions/aggregate.py+states.py` (SM-1, CAS, `ApprovalPin`), `finance/policy/execution_policy.py` (7-gate pure), `finance/evidence/models.py` + `finance/object_store/port.py` (`ObjectMeta` hash), `shared/aws/config.py` (host vs container), `docker-compose.ministack.yml` (LocalStack S3), `shared/llm/*` (thin SDKs, `LLMProvider`, `Fake`/`Replay`), `shared/tracing/*` (`TracerProtocol`/`NoOp`/`Langfuse` lazy, `create_tracer()`), `agents/investigation/{plan,request,planner}.py` (allowlist, bounded prompt, typed `InvestigationPlan`), `agents/capabilities/{registry,types,executor}.py` (closed vocab, bounded args, dedup), `agents/verification/verifier.py` (6 stages, pure), `apps/api/{middleware,webhooks}.py` (HMAC, RLS, `_audit`), `pyproject.toml` markers/budget guard.

Do not duplicate validators, policies, evidence models, capability checks, or tracing primitives — harden them.

## 15. Required changes

Derived from missing controls, ordered to maximize trust before surface:

1. **Context/security boundary** (`agents/investigation/request.py` + `finance/context` or new `shared/context/boundary.py`) — deterministic `tenant_id`/`case`/`actor` context assembly, `MAX_CONTEXT_CHARS` already, add per-tenant + per-exception-type scope, `allowlisted evidence` bounded text, provenance-preserving, `untrusted-content` fence, no arbitrary DB/S3 retrieval — unit-testable, no LLM.
2. **Tenant isolation proofs** — add `tests/unit/tenant_isolation/` or extend `tests/integration/test_stripe_tenant_isolation.py` to cover `case lookup → evidence retrieval → capability execution → S3 → LLM context → proposal` per tenant prefix, fail-closed.
3. **Capability security hardening** — extend `agents/capabilities/executor.py` checks to `tenant/case scope/argument schema/input-output size/timeout/credential/resource identity` and explicit `arbitrary SQL/HTTP/URL/filesystem/credential` denials; no new capability without spec.
4. **Prompt-injection corpus** — `tests/fixtures/security/prompt_injection/` (Gmail, Sheets, legacy records, provider metadata, tool results, S3 objects, case notes) with `ignore prior instructions / execute refund / approve proposal / send credentials / change tenant / read another case / call unapproved tool / override policy` — verify preserved as evidence, never executed, never alters authorization/policy/state; not solved by system prompt alone.
5. **Grounding contract** — formalize `FACTUAL → must cite evidence → exists → belongs to tenant → provenance valid → supported → VERIFIED` with `HYPOTHESIS != FACT != VERIFIED` ladder tests in `agents/verification/` and `finance/evidence/`.
6. **PII/secret controls** — trace-sensitive path `provider → adapter → canonical → evidence → context builder → LLM → traces → logs → audit`, define `retained/redacted/hashed/excluded`, add `rg` gate for `api_key|secret` in `tests/`, prove `credential never reaches LLM context/agent output/Langfuse/logs/audit`.
7. **Agent trajectory harness** — first-class `trajectory` package (`shared/harness` or `agents/trajectory/`) with `Fake`/`Replay`/`Live`/`E2E` modes, recorded `INPUT → MODEL OUTPUT → VERIFIER → TOOL → RESULT → NEXT OUTPUT → FINAL` journal, `pytest -m live_llm` gated `FINSIGHT_ALLOW_LIVE_LLM=1`, budget-guarded, small representative scenarios, replay for evaluation.
8. **Observability abstraction** — evaluate `shared/tracing/` vs required `case → context assembly → planner → LLM generation → verifier → capability call → result → replan → final candidate → policy → approval → execution → verification` trace with `correlation_id`/`tenant-safe`/`case`/`timestamp`/`latency`/`status`, no unrestricted payload; decide Langfuse adapter (`Langfuse adapter optional` per `docs/09-platform/llmops.md`), not core dependency.
9. **Legacy protocol** — `docs/architecture/LEGACY_BATCH_PROTOCOL.md` (`file identity`, `batch identity`, `schema`, `field positions`, `version`, `sequence`, `control total`, `checksum/hash`, `accepted/rejected record`, `partial processing`, `duplicate detection`, `result/retry/timeout semantics`, `OUTBOUND → RESULT` without HTTP) using existing `finance/object_store` S3 buckets as `OUTBOUND`/`RESULT` per tenant.
10. **MiniStack-backed artifact tests** — extend `tests/ministack/test_s3_ministack.py` with `evidence artifacts / legacy outbound/result files` via S3, not PostgreSQL state.
11. **Full security regression** — adversarial matrix (§5.19) with `positive/negative/adversarial` per invariant, gated `pytest -m "not live_llm"` stays `1870 passed` baseline.
12. **Evaluation + golden datasets + property-based tests** — §5.21–5.23 datasets and `hypothesis`/`fuzzing` for `gross-fees-refunds-adjustments=net`, `duplicate event != duplicate effect`, `cross-tenant evidence cannot appear in context`, `Decimal`/`currency`/`identifiers`/`Gmail`/`tool results`/`S3 metadata`.

## 16. Explicit non-goals

- Generic chatbot / AI CFO / multi-agent swarm / autonomous finance system (P5 is trust boundary hardening, not capability expansion).
- Generic `Namecheap`/`Twilio`/`Stripe Dashboard` clones (FinSight is exception-resolution, not payment initiation UI).
- `SQS`/`SNS`/`EventBridge`/`DynamoDB`/`StepFunctions` adapter/service/test until queue gate fires (seam audit `NOT REQUIRED`).
- Full COBOL bridge implementation in first P5 slice (protocol only).
- Making `Langfuse` a core dependency (observability abstraction first, adapter optional).
- Moving financial truth into `S3` or making `S3` authoritative (S3 is transport/artifact only).
- Adding a new `LLMProvider` or prompt registry beyond `shared/llm/` without gated evaluation.
- Large `finplatform` RBAC migration in first slice (harden `InvestigationRequest` + `CapabilityExecutor` + `ObjectStorePort` first).

## 17. Threat model

**External content becomes authority:** Gmail/Sheets/Slack/legacy rejection/tool-result/S3 object free text containing `approve this proposal` / `change tenant` / `call unapproved tool` / `override policy` must never create authorization, approval, permission, tenant access, or state transition — verified by adversarial corpus (§5.8) preserving content as evidence.

**Tenant boundary violation:** `Tenant A` reading `Tenant B` evidence/S3 object/capability/case must fail closed (`TenantIsolationError` before store/network, RLS `app.tenant_id`, `ExceptionAggregate.tenant_id`) — tested `cross-tenant evidence/cross-tenant S3` positive/negative/adversarial.

**Credential/PII leakage:** `api_key`/`secret` in `LLM context`/`agent output`/`Langfuse`/`logs`/`audit` → bounded `redacted`/`hashed`/`excluded`; verified by `rg` gate and `test_security_no_credential_leak_in_exception`.

**Tool escape:** `arbitrary SQL/HTTP/URLs/filesystem` / `credential-containing args` / `cross-tenant identifiers` / `unapproved capability` / `oversized context/tool output` → `ExecutorRejectedError`/`TenantIsolationError`/`ValueError` before execution.

**Control integrity:** `fake approval` / `proposal tampering` / `stale proposal` / `state bypass` / `duplicate execution` / `provider UNKNOWN` / `legacy duplicate file` / `invalid control total` / `partial processing` / `malicious tool result` → deterministic gates (`ApprovalPin`/`verify_hash`/`state_version` CAS/`ALLOWED_TRANSITIONS`/`post-execution verification mandatory`/`I10` no closure without terminal verification).

**Financial correctness:** `MoneyDecimal`/`Decimal` only, `I1` no floats, `I2` deterministic computation, `gross-fees-refunds-adjustments=net`, `debit==credit`, `refund<=refundable`, `idempotency same action+same key = one effect`, `closed case cannot execute`.

## 18. Test matrix

| Dimension | Invariant | Positive | Negative | Adversarial |
|-----------|-----------|----------|----------|-------------|
| Tenant isolation | `Tenant A cannot see B evidence/capability/S3/case` | Own-tenant put/get/capability succeeds | Wrong-tenant prefix → `TenantIsolationError` (no store) | `change tenant` in Gmail/Sheets/S3 free text — preserved as data, no boundary bypass |
| Prompt injection | Retrieved content is DATA | Evidence preserved with `content_hash` | Embedded `approve`/`execute refund` not executed | Indirect injection via tool-result → capability result preserved, no new tool call |
| Grounding | `FACTUAL → cited, tenant-owned, provenance-valid, supported → VERIFIED` | Cited+proven → `VERIFIED` | Uncited → unsupported-claim → rejected | `confidence=0.99` without citation → rejected (confidence != authority) |
| Tool security | `tenant/case/schema/allowlist/size/timeout/credential/resource` | Bounded, allowlisted, tenant-scoped call succeeds | Arbitrary SQL/URL/credential arg → `ExecutorRejectedError` | Oversized tool output (e.g., 10MB sheet) → bounded error, no LLM flood |
| Control integrity | `policy/approval/state` | Valid `ApprovalPin` + `verify_hash` → execution | Stale `state_version`/`content_hash` → rejected | `fake approval` JSON → `ApprovalPin` mismatch |
| Financial | `MoneyDecimal`, idempotency, state machine | `gross-fees-refunds-adjustments=net` holds | Float → `MoneyDecimal` rejects | `duplicate event` with same `idempotency_key` → one effect |
| Reliability | `duplicate/timeout/retry/unknown/legacy partial/replay` | Idempotent redelivery same hash | `provider UNKNOWN` → `post-execution verification` required, no closure | `legacy partial processing` (half accepted) → `control total` mismatch → bounded |

## 19. Open questions

1. Does `InvestigationRequest` become the sole `context assembly` boundary (deterministic, unit-testable) or does `apps/api/middleware.py` + `shared/context/boundary.py` share the role?
2. Should `finance/evidence/models.py:EvidenceItem` gain explicit `tenant`, `content_hash`, `retrieval_time`, `provenance` fields, or keep envelope in `ObjectMeta` + `ExceptionAggregate.evidence_ids`?
3. Can `shared/tracing/` already satisfy `case → context → planner → LLM → verifier → capability → result → replan → policy → approval → execution → verification` with `correlation_id`/`tenant-safe` IDs, or is a new `agents/trajectory/` harness required before wiring?
4. Is `Langfuse adapter optional` still correct after `shared/tracing/factory.py:create_tracer()` env-driven already exists, or should the first P5 slice wire `TracerProtocol` through `Planner`+`Executor`+`Verifier` now?
5. Should `docs/architecture/LEGACY_BATCH_PROTOCOL.md` version the fixed-width field positions now, or defer until `finance/legacy/` consumes `finance/object_store` buckets?
6. Which hypothesis library (`hypothesis` vs `polyfactory` already in `pyproject.toml:dev`) should gate property-based tests for `Decimal`/`currency`/`identifiers` fuzzing?
7. Do we create `tests/evals/p5/` golden datasets now (happy/timing/fee/duplicate/legacy rejection/ambiguous/conflicting/prompt-injection/cross-tenant/partial/provider timeout/UNKNOWN) or seed from existing `docs/08-evaluation/Golden Datasets.md` first?

---

*Evidence: `rg -n` counts above (tenant/auth/policy/evidence/claim/audit/secret/credential/trace/capability/S3/ObjectStorePort), `apps/api/{middleware,webhooks,schemas}.py`, `finplatform/rbac/matrix.py`, `finance/{evidence,policy,exceptions,reconciliation,object_store}/`, `finance/ml/registry.py`, `shared/{llm,tracing,aws}/`, `shared/config/config.py`, `agents/{investigation,capabilities,verification}/`, `pyproject.toml` markers `live_llm/evals/integration/ministack`, `docker-compose*.yml`, `docs/architecture/MINISTACK_SEAM_AUDIT.md`, `openspec/changes/{add-finsight-v2-reconciliation,add-ministack-s3-contract}/`.*
