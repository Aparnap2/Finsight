# FinSight Acceptance Test Plan (Human-Executable)

- Scope: Phases 10 (acceptance) + 11 (production readiness) evidence, human-run.
- Grounding: `docs/architecture/PROJECT_COMPLETION_GAP_AUDIT.md` (base `6373489`);
  slice SHAs `e28c149` (P6 slice), `680f3bd` (P7 pipeline), `5f75036` (P8→P7),
  `5a17730` (P8 PG durability), `f65d480` (API `/execute`+`/verify`),
  `218f08d` (adversarial, 16 attacks), `6cb8396` (LLM eval), `7b5d385` (observability).
- Automated coverage already exists for every scenario below; the human step
  confirms observable behavior (HTTP status / CLI output), not internals.

## Prerequisites

- Shell: `UV_PROJECT_ENVIRONMENT=.venv-aparna uv sync && UV_PROJECT_ENVIRONMENT=.venv-aparna uv run python -m pytest --collect-only` (env repair: audit G10).
- No live Postgres needed except PG-gated files (`test_p8_postgres_durability.py`,
  `test_tenant_isolation.py`, `test_stripe_*`); everything else runs on fakes/in-memory.
- No credentials needed: deterministic path only. Live-provider eval was NOT run
  (see `docs/release/PRODUCTION_READINESS.md`).
- Boot API (optional, for HTTP-observable steps): `uvicorn apps.api.main:app`,
  then `GET /health` → 200, `GET /live` → 200, `GET /ready` → 200/503 by DB probe
  (`apps/api/observability.py`: `create_readiness_router`, `RequestIDMiddleware`).

## How to record

Each scenario ends with an actual-behavior table. Fill `Result` with
PASS / FAIL + date + operator initials. Leave blank until run.

## Scenarios

### A01 — Normal financial workflow (happy path)

- Automated: `tests/integration/test_p6_executable_slice.py::TestExecutableSliceHappy::test_fixture_to_verified_report_in_order`
  (fixture → verified report: builder→decide→run→verify, `mint_report`);
  API: `tests/integration/test_api_execute_verify.py::TestExecuteHappy::test_execute_runs_controlled_path_to_verified`
  + `TestVerifyEndpoint::test_verify_happy_path_returns_verified`.
- Manual steps:
  1. `UV_PROJECT_ENVIRONMENT=.venv-aparna uv run python -m pytest tests/integration/test_p6_executable_slice.py::TestExecutableSliceHappy -q`
  2. `UV_PROJECT_ENVIRONMENT=.venv-aparna uv run python -m pytest tests/integration/test_api_execute_verify.py::TestExecuteHappy::test_execute_runs_controlled_path_to_verified tests/integration/test_api_execute_verify.py::TestVerifyEndpoint::test_verify_happy_path_returns_verified -q`
  3. (Optional live API) `POST /execute` with authorized fixture body → expect
     controlled-path verified payload; `POST /verify` → verified report.
- Expected: all green; `/execute` returns verified (not bypass); single executor
  entry guarded by authorization (`TestNoBypass::test_single_executor_entry_guarded_by_authorization`).

| Step | Expected | Result |
|---|---|---|
| 1 P6 slice happy | 1 passed | |
| 2 API happy | 2 passed | |
| 3 live POSTs (optional) | verified payloads | |

### A02 — Conflicting evidence stays blocked

- Automated: `tests/integration/test_adversarial_system.py::TestAdversarialSystem::test_09_contradictory_evidence_stays_blocked`;
  related: `test_06_forged_evidence_refused_before_reasoning`;
  P7 gate: `agents/integration/control_plane.py:90 ControlPlaneGate.admit()->GateResult` (`BLOCKED`|`P6_HANDOFF`).
- Manual steps:
  1. Run `uv run python -m pytest tests/integration/test_adversarial_system.py::TestAdversarialSystem::test_09_contradictory_evidence_stays_blocked tests/integration/test_adversarial_system.py::TestAdversarialSystem::test_06_forged_evidence_refused_before_reasoning -q`
  2. Confirm refusal occurs before reasoning (no P7 entries on refusal path).
- Expected: BLOCKED; zero P7 side entries; forged evidence refused pre-reasoning.

| Step | Expected | Result |
|---|---|---|
| 1 adversarial contradictory+forged | 2 passed | |
| 2 no-P7-entries on refusal | zero entries asserted in test | |

### A03 — Stale evidence refused without execution

- Automated: `tests/integration/test_adversarial_system.py::TestAdversarialSystem::test_05_stale_version_refused_without_execution`;
  P6: `tests/integration/test_p6_executable_slice.py::TestExecutableSliceFailures::test_14_stale_context`.
- Manual steps:
  1. Run both tests by node ID (`-q`).
  2. Confirm stale version/context refuses before any execution effect.
- Expected: refusal, no execution side effects.

| Step | Expected | Result |
|---|---|---|
| 1 stale version + stale context | 2 passed | |

### A04 — Provider failure bounded (timeout→retry→exhaustion)

- Automated: `tests/integration/test_adversarial_system.py::TestAdversarialSystem::test_12_timeout_then_success_retries_once`
  + `test_13_retry_exhaustion_bounded_no_p7_entries`;
  P6: `test_15_retry_exhaustion`; budgets/retry real per audit G14
  (`contract.py: check_budget/classify/call_with_retry`).
- Manual steps:
  1. Run the three tests by node ID.
  2. Confirm exactly-once retry then success; exhaustion bounded with no P7 entries.
- Expected: 1 retry then success; exhaustion → typed failure, bounded, silent P7.

| Step | Expected | Result |
|---|---|---|
| 1 timeout/retry/exhaustion trio | 3 passed | |

### A05 — Replay single effect (idempotency)

- Automated: `tests/integration/test_adversarial_system.py::TestAdversarialSystem::test_03_replay_completed_key_single_effect`
  + `test_04_concurrent_replays_single_winner`;
  P6: `test_07_duplicate_idempotent_single_effect`;
  API: `TestExecuteRefusals`-adjacent `test_duplicate_idempotency_key_single_effect`.
- Manual steps:
  1. Run the four replay/idempotency tests.
  2. (Optional live API) `POST /execute` twice with same idempotency key → one effect.
- Expected: completed-key replay = single effect; concurrent replays = single winner.

| Step | Expected | Result |
|---|---|---|
| 1 replay/idempotency quartet | 4 passed | |
| 2 live double-POST (optional) | one effect | |

### A06 — Approval rejection recorded, nothing executes

- Automated: `tests/integration/test_p6_executable_slice.py::TestExecutableSliceFailures::test_02_approval_rejection_records_rejected`
  + `test_01_policy_rejection_over_threshold`;
  adversarial: `test_07_approval_laundering_refused`;
  races: `tests/integration/test_approval_races.py` (`test_extra_amount_action_rejected_422_no_mutation`,
  `test_missing_auth_denied_401_no_mutation` — 4 tests, run file).
- Manual steps:
  1. Run P6 `test_01`, `test_02`, adversarial `test_07`, full `test_approval_races.py`.
  2. Confirm rejected state recorded; no mutation on 401/403/422.
- Expected: rejection recorded; laundering refused; race denials mutate nothing.

| Step | Expected | Result |
|---|---|---|
| 1 approval-rejection set | all passed | |

### A07 — Execution failure typed (unbookable action)

- Automated: `tests/integration/test_p6_executable_slice.py::TestExecutableSliceFailures::test_04_execution_failure_unbookable_action`
  + `test_06_insufficient_budget_over_tier`;
  API: `test_policy_rejected_input_refuses_before_execution`, `test_missing_authorization_context_refuses`.
- Manual steps:
  1. Run the four tests by node ID.
  2. Confirm typed failure (not exception leak); policy/auth refusals precede execution.
- Expected: typed `FailureKind`; budget-over-tier refused; no execution without auth.

| Step | Expected | Result |
|---|---|---|
| 1 execution-failure quartet | 4 passed | |

### A08 — Verification failure (tolerance + R1/R2/R3 + mint binding)

- Automated: `tests/integration/test_p6_executable_slice.py::TestExecutableSliceFailures::test_05_verification_failure_tolerance_exceeded`
  + `test_08_r1_violation_digest_mismatch` + `test_09_r2_violation_count_skew`
  + `test_10_r3_violation_control_skew` + `test_16_missing_authorization_binding_refuses_mint`;
  API: `TestVerifyEndpoint::test_verification_failure_returns_typed_failure`.
- Manual steps:
  1. Run the six tests by node ID.
  2. Confirm each R-rule violation refuses mint; tolerance breach → typed failure.
- Expected: R1/R2/R3 each refuse; mint requires authorization binding.

| Step | Expected | Result |
|---|---|---|
| 1 verification sextet | 6 passed | |

### A09 — Tenant isolation (no cross-tenant read or effect)

- Automated: `tests/integration/test_adversarial_system.py::TestAdversarialSystem::test_01_cross_tenant_refused_without_side_effects`
  + `test_02_cross_situation_refused`;
  P6: `test_13_wrong_tenant`, `test_17_wrong_company_prefix_escape`, `test_18_case_skew_refuses_cross_case_replay`;
  DB: `tests/integration/test_tenant_isolation.py` (5 tests, PG-gated);
  API: `test_wrong_tenant_refuses_without_effect`.
- Manual steps:
  1. Run non-PG tests by node ID (no live PG needed).
  2. PG-gated `test_tenant_isolation.py` + `test_stripe_tenant_isolation.py`:
     require live PG; fresh-DB breakages documented as pre-existing (see
     `docs/release/PRODUCTION_READINESS.md`); record outcome, do not fix here.
- Expected: cross-tenant/situation refused, zero side effects; prefix/case
  escapes refused; RLS tests pass on provisioned PG.

| Step | Expected | Result |
|---|---|---|
| 1 non-PG isolation set | all passed | |
| 2 PG RLS files (needs live PG) | pass / pre-existing failure recorded | |

### A10 — Prompt injection stays data

- Automated: `tests/integration/test_adversarial_system.py::TestAdversarialSystem::test_11_prompt_injection_stays_data`
  + `test_10_malformed_model_output_fails_with_zero_p7_entries`
  + `test_15_canary_secrets_absent_everywhere`;
  eval guard: `tests/evaluation/test_llm_quality_regression.py::test_injection_cases_reference_security_fixtures`
  + `test_quality_regression_never_alters_safety`.
- Manual steps:
  1. Run the five tests by node ID.
  2. Confirm injection never becomes instruction; canary secrets absent from logs
     (redaction: `apps/api/observability.py` via `shared.safety.secrets`).
- Expected: injection treated as data; malformed output → zero P7 entries; no
  secret leakage (audit K1 rule).

| Step | Expected | Result |
|---|---|---|
| 1 injection/secrecy quintet | 5 passed | |

## Traceability index (scenario → files)

| Scenario | Test file(s) |
|---|---|
| A01 | `tests/integration/test_p6_executable_slice.py`, `tests/integration/test_api_execute_verify.py` |
| A02 | `tests/integration/test_adversarial_system.py`, `agents/integration/control_plane.py` |
| A03 | `tests/integration/test_adversarial_system.py`, `tests/integration/test_p6_executable_slice.py` |
| A04 | `tests/integration/test_adversarial_system.py`, `tests/integration/test_p6_executable_slice.py` |
| A05 | `tests/integration/test_adversarial_system.py`, `tests/integration/test_p6_executable_slice.py`, `tests/integration/test_api_execute_verify.py` |
| A06 | `tests/integration/test_p6_executable_slice.py`, `tests/integration/test_adversarial_system.py`, `tests/integration/test_approval_races.py` |
| A07 | `tests/integration/test_p6_executable_slice.py`, `tests/integration/test_api_execute_verify.py` |
| A08 | `tests/integration/test_p6_executable_slice.py`, `tests/integration/test_api_execute_verify.py` |
| A09 | `tests/integration/test_adversarial_system.py`, `tests/integration/test_p6_executable_slice.py`, `tests/integration/test_tenant_isolation.py`, `tests/integration/test_api_execute_verify.py` |
| A10 | `tests/integration/test_adversarial_system.py`, `tests/evaluation/test_llm_quality_regression.py`, `apps/api/observability.py` |

UNVERIFIED this session: wall-clock durations of each scenario; live-`/execute`
payload shape (only exercised via mocked API tests, not a live server here).
