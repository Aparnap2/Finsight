# Tasks: add-finsight-v2-reconciliation

> Normalized P0–P9 execution plan. Sequential phases. No phase skipping. P0 must freeze before any code.

## P0 Specification & Contract Freeze (STOP before code)

- [ ] P0.1 Scaffold openspec change `add-finsight-v2-reconciliation` with `proposal.md`, `design.md`, `tasks.md` (this file)
- [ ] P0.2 Freeze 5 contracts: PaymentRecord, ReconciliationResult, Evidence, ResolutionProposal (!= Execution), Execution
- [ ] P0.3 Freeze invariants I1–I10 + exception state machine with allowed transitions only
- [ ] P0.4 Run `openspec validate --strict`, resolve all errors, record human approval checkpoint
- [ ] P0.5 Explicit STOP gate: no `finance/`, `agents/`, `apps/`, `shared/` code changes until P0.1–P0.4 approved

## P1 Pure Reconciliation Core (no LLM / DB / net)

- [ ] P1.1 Implement amount normalizer in `finance/` using `decimal.Decimal` only, minor-units → Decimal, currency guard
- [ ] P1.2 Implement deterministic matcher: exact + windowed match on amount, currency, timestamp, reference id
- [ ] P1.3 Implement tolerance policy: zero-default, explicit per-currency epsilon config, no silent rounding
- [ ] P1.4 Implement idempotency fingerprint: stable hash of normalized fields, dedupes replays
- [ ] P1.5 Unit tests only with mocked boundaries: normalizer, matcher happy/edge, tolerance boundaries, fingerprint stability
- [ ] P1.6 Verify `ruff check` + `mypy --strict` + `pytest tests/unit` pass, no imports from `apps/` or `agents/` in `finance/`

## P2 Stripe Sandbox Ingestion (no LLM first)

- [ ] P2.1 Implement Stripe webhook signature verification with timestamp tolerance, reject on invalid signature
- [ ] P2.2 Implement ingestion dedup via P1 fingerprint + event-id idempotency key before any state mutation
- [ ] P2.3 Normalize Stripe sandbox events through P1 normalizer into PaymentRecord contract
- [ ] P2.4 Reconcile normalized Stripe intents against ledger fixtures using P1 matcher only (deterministic path)
- [ ] P2.5 Integration tests with recorded Stripe sandbox fixtures (VCR/cassette), no live network in test loop
- [ ] P2.6 Verify no LLM calls on ingestion path; log correlation IDs via structured logging

## P3 HITL + Mock QuickBooks Execution (adapter boundary)

- [ ] P3.1 Define QuickBooks adapter interface in `finance/`; mock sandbox implementation only, no real QB credentials
- [ ] P3.2 Implement strict pipeline order: proposal → policy check → HITL approval → sandbox execute → post-verify
- [ ] P3.3 Implement policy gate: blocks auto-execution, amount thresholds, unsafe-action deny list
- [ ] P3.4 Implement HITL queue: pending approvals are explicit, auditable, single-decision semantics
- [ ] P3.5 Implement post-execution verifier: re-reads sandbox state, asserts expected mutation, marks CLOSED only on proof
- [ ] P3.6 Tests: proposal rejection, policy block, approve-then-execute, verify-failure does not close

## P4 Agentic Investigation (read-only, assertion-gated)

- [ ] P4.1 Wire swappable Groq LLM client behind `shared/` interface; deterministic fallback when agent unavailable
- [ ] P4.2 Implement exactly 6 read-only investigation tools (ledger read, event read, match trace, tolerance explain, fingerprint lookup, policy preview); no write tools
- [ ] P4.3 Gate all agent proposals through P1 invariants + P3 policy; ungrounded proposals rejected with rationale
- [ ] P4.4 Persist agent trace: inputs, tool calls, assertion results, confidence; no critical state in process memory
- [ ] P4.5 Agent tests with mocked LLM (no real calls): happy-path diagnosis, low-confidence routes to HITL, write-attempt blocked
- [ ] P4.6 Verify agent-unavailable path still reconciles deterministically via P1–P2 (degraded mode)

## P5 Local Infrastructure + Flagship E2E

- [ ] P5.1 Add `docker-compose.test.yml` only for test orchestration with app healthcheck gate; no dev-environment compose
- [ ] P5.2 Seed local fixtures: 50k sale, 15k refund lag, net 35k expected
- [ ] P5.3 Implement `make e2e` target: gated compose, ingestion → reconcile → HITL approve → mock-QB execute → verify
- [ ] P5.4 Assert flagship outcome: 35k == 35k, state == CLOSED, unsafe-action count == 0
- [ ] P5.5 Capture E2E log to `/tmp/integration_<timestamp>.log`; pass criterion is exit code 0 only

## P6 Failure / Chaos Testing

- [ ] P6.1 Duplicate delivery: same Stripe event x2 reconciles once, second is deduped via fingerprint
- [ ] P6.2 Out-of-order delivery: refund-before-sale converges to correct net without double-count
- [ ] P6.3 Crash-after-execute: replay after sandbox execute does not re-execute (idempotency key holds)
- [ ] P6.4 Double-approve: second HITL approval is rejected as no-op with audit entry
- [ ] P6.5 Lost-response: execute timeout triggers verify-before-retry, never blind retry
- [ ] P6.6 All chaos cases assert no CLOSED on unverified state and no unsafe actions executed

## P7 Evaluation Harness (separate pipeline, never in dev loop)

- [ ] P7.1 Build golden dataset: 3 types (match, mismatch, exception) × 3 regimes (happy, edge, adversarial)
- [ ] P7.2 Keep evals in `evals/` with promptfoo YAML config; no eval execution inside unit/integration loop
- [ ] P7.3 Measure: reconciliation accuracy, assertion compliance, hallucination rate, unsafe-proposal rate (must be 0)
- [ ] P7.4 Record baseline scores; regressions block P9 sign-off
- [ ] P7.5 Enforce LLM budget in evals only: max 3 real calls per run, log raw responses to `/tmp/llm_debug_*.json` on failure

## P8 Go Extraction Benchmark (parity-gated)

- [ ] P8.1 Export Python parity fixtures from P1 normalizer/matcher (inputs + expected outputs, Decimal as string)
- [ ] P8.2 Benchmark Go extraction implementation against fixtures only; no behavior drift allowed
- [ ] P8.3 Threshold gate: parity == 100% on happy/edge fixtures before promotion; record latency comparison
- [ ] P8.4 Document parity result in change; Go code does not replace Python path in this change

## P9 Hardening + Final Gates

- [ ] P9.1 Run `uv run ruff check .` clean (100-char limit)
- [ ] P9.2 Run `uv run mypy .` strict clean with full annotations, Decimal for all money
- [ ] P9.3 Run `python -m pytest` full suite: unit + integration + ai (mocked) + e2e gated compose, all green
- [ ] P9.4 Secret scan: no credentials in code/logs/cassettes; HMAC/signature secrets via env only
- [ ] P9.5 Dependency audit: no new deps without justification; verify `pyproject.toml` / lockfile consistency
- [ ] P9.6 Migration validation: migrations apply/rollback cleanly on ephemeral DB if touched, else mark N/A
- [ ] P9.7 API contract check: webhook + proposal schemas validated with Pydantic strict mode, error responses standardized
- [ ] P9.8 Idempotency proof: duplicate/out-of-order/crash replays from P6 re-run green
- [ ] P9.9 Degraded-mode proof: agent-unavailable run still reconciles via deterministic path, E2E CLOSED holds
