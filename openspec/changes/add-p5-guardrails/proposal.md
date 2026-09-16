# Proposal: P5 Guardrails — Trust, Security, Grounding & Production Agent Harness

## Why

P4 proved the bounded-cognition thesis: deterministic code owns every number, reconciliation, policy, transition, execution and post-verification; the LLM produces typed candidates only, never authority. The next question is not "can it reason?" but "can it survive hostile inputs, untrusted evidence, tenant isolation, PII/secret constraints, observability discipline, and a constrained legacy financial core without weakening P3/P4 control semantics?"

The current repository (checkpoint `finsight-p4-complete` at `1d0005b`) carries strong deterministic gates (SM-1 CAS, 14-never set, 6-stage verifier, closed allowlist, MoneyDecimal, sandbox+post-verify) but no prompt-injection-as-data contract, no PII/secret boundary for the LLM path, no observability redaction gate, no per-case trajectory harness, and no legacy file/batch boundary. This proposal makes those gaps explicit before any implementation code.

## What Changes

- **BREAKING: none.** This change is architecture/discovery only. No financial mutation path, no new runtime dependency unless justified below, no P3/P4 invariant weakened. `P4 adds cognition without changing P3 control semantics` remains frozen.
- Adds 5 capability deltas: `guardrails`, `grounding`, `agent-harness`, `observability`, `legacy-boundary`.
- Formalizes the trust model (Trusted / Conditionally trusted / Untrusted) and the guardrail taxonomy (Input / Tool / Reasoning / Output / Execution / Post-execution).
- Formalizes the grounding ladder `FACTUAL → requires evidence → evidence ∈ tenant → provenance valid → claim supported → VERIFIED` and the `HYPOTHESIS ↛ FACTUAL ↛ VERIFIED` non-elevation rule.
- Formalizes the prompt-injection-as-data contract and the PII/secret path audit (`provider → adapter → canonical → evidence → context → LLM → trace → audit`).
- Defines the agent trajectory harness (Fake / Replay / Live / E2E) with gated `live_llm`.
- Defines observability as evaluation layer only (not authorization/policy/execution/state), with payload discipline and the per-case trace shape.
- Defines the legacy file/batch boundary (fixed-width, batch_id/sequence/control-total, duplicate/partial/rejected handling, no HTTP).
- Explicit non-goals: no MiniStack/SQS until the queue gate fires, no LangGraph orchestrator replacement, no new financial authority for the LLM.

## Impact

- **Affected specs (new capabilities, ADDED only):**
  - `guardrails` — trust boundaries + taxonomy
  - `grounding` — grounding ladder + injection contract + PII/secret boundary
  - `agent-harness` — trajectory harness (4 modes)
  - `observability` — tracing seam wiring + redaction
  - `legacy-boundary` — file/batch protocol contract
- **Affected code (future, not in this PR):** `agents/investigation/request.py`, `agents/verification/verifier.py`, `agents/orchestrator/`, `agents/capabilities/`, `shared/tracing/`, `finance/evidence/`, `finance/legacy/` (new), `tests/{unit,evals}/`, `docker-compose.legacy.yml` (local only), `apps/api/approvals.py`.
- **Not in this PR:** any `finance/`, `agents/`, `shared/`, `apps/` behavior change, any new `pyproject.toml` dependency, any ledger mutation path, any LangGraph rewrite. This PR commits only `docs/architecture/P5_GUARDRAILS_GAP_ANALYSIS.md` + this OpenSpec delta + issue scaffolding. Implementation lands as small follow-up PRs per `tasks.md` after this proposal is approved.
