# Tasks: add-p5-guardrails

> Architecture/discovery phase only. No production behavior changes in this PR.
> Each task below is a future atomic PR after this proposal is approved.
> `openspec validate add-p5-guardrails --strict` must stay green throughout.

## P5.0 Discovery checkpoint (this PR)

- [x] P5.0.1 Verify Git state, tag `finsight-p4-complete` at `1d0005b`, create branch `feat/finsight-guardrails-security` from checkpoint
- [x] P5.0.2 Repository archaeology (finance / agents / shared / apps / tests / CI / docs)
- [x] P5.0.3 Produce `docs/architecture/P5_GUARDRAILS_GAP_ANALYSIS.md` (17-section, repo-grounded, no generic prose)
- [x] P5.0.4 Scaffold OpenSpec delta `add-p5-guardrails` with `proposal.md`, `design.md`, `tasks.md`, spec deltas for `guardrails`, `grounding`, `agent-harness`, `observability`, `legacy-boundary`
- [x] P5.0.5 Validate `openspec validate add-p5-guardrails --strict` green before commit
- [ ] P5.0.6 Create GitHub Issues for P5.1–P5.11 (Issue 1 is this architecture/spec PR)
- [ ] P5.0.7 Run regression `pytest -m "not live_llm"` + `ruff check .` + `mypy .` scoped to touched files
- [ ] P5.0.8 Commit + PR only architecture/spec artifacts (`docs/architecture/`, `openspec/changes/add-p5-guardrails/`)

## P5.1 Context / security boundary (future PR)

- [ ] P5.1.1 Harden `agents/investigation/request.py` + `finance/context` with tenant/case/actor authz, context-size cap, classification, allowed-scope per exception_type
- [ ] P5.1.2 Add `tests/unit/investigation/test_context_boundary.py` (positive + negative + adversarial)
- [ ] P5.1.3 Extend `apps/api/middleware.py` tenant isolation proof at HTTP boundary
- [ ] P5.1.4 `ruff check` + `mypy --strict` + `pytest -m "not live_llm"` green

## P5.2 Grounding hardening (future PR)

- [ ] P5.2.1 Formalize verifier ladder `FACTUAL → evidence → tenant → provenance → supported → VERIFIED` in `agents/verification/verifier.py`
- [ ] P5.2.2 Add `tests/unit/verification/test_grounding_ladder.py` proving `HYPOTHESIS ↛ FACTUAL ↛ VERIFIED`
- [ ] P5.2.3 Document grounding contract vs existing FP&A hallucination docs

## P5.3 Prompt-injection corpus (future PR)

- [ ] P5.3.1 Add corpus fixtures: hostile instructions in Gmail/Sheets/legacy-rejection/Slack/provider-metadata/tool-result
- [ ] P5.3.2 Add `tests/unit/security/test_prompt_injection_corpus.py` proving evidence-as-data (no instruction/authorization/policy elevation)
- [ ] P5.3.3 Ensure verifier/executor deterministic fence, not prompt-only defense

## P5.4 Trajectory harness (future PR)

- [ ] P5.4.1 Implement `TrajectoryHarness` journal: `input context → model output → verifier → selection → args → result → next output → final candidate`
- [ ] P5.4.2 Add `tests/unit/trajectory/test_harness.py` (Fake → Replay byte-stable)
- [ ] P5.4.3 Keep `pytest -m "not live_llm"` zero-network

## P5.5 Observability integration (future PR)

- [ ] P5.5.1 Wire `shared/tracing/` into `agents/orchestrator/`, `planner.py`, `executor.py`, `verifier.py` + per-case trace shape
- [ ] P5.5.2 Add PII/money/secret redaction gate `tests/unit/tracing/test_observability_payload.py`
- [ ] P5.5.3 Add `docker-compose.langfuse.yml` already present: keep local-only, not CI-required

## P5.6 Legacy protocol contract (future PR)

- [ ] P5.6.1 Define `docs/architecture/legacy_protocol.md` fixed-width spec + `batch_id/sequence/control_total` contract
- [ ] P5.6.2 Add `tests/unit/legacy/test_batch_protocol.py`

## P5.7–P5.9 Legacy implementation (future PRs)

- [ ] P5.7.1 Minimal GnuCOBOL batch behind `docker-compose.legacy.yml` (local only, not CI-required)
- [ ] P5.8.1 `finance/legacy/adapter.py` file/batch boundary + `tests/unit/legacy/test_adapter.py` + `tests/integration/test_legacy_e2e.py`

## P5.10 Live-agent integration (future PR, gated)

- [ ] P5.10.1 `tests/evals/agent/test_live_agent.py` real Groq + real caps + real guardrails, gated `live_llm` + `LIVE_LLM=1`

## P5.11 E2E acceptance (future PR)

- [ ] P5.11.1 `docker-compose.test.yml` healthcheck-gated acceptance: flagship + hostile-input + legacy-batch + stale-state
