# FinSight Production Readiness

- Date: 2026-09-27. Branch: `chore/project-completion-gap-audit`. DOC-ONLY, no behavior change.
- Audit base: `docs/architecture/PROJECT_COMPLETION_GAP_AUDIT.md` (base `6373489`).
- Decision: **NOT READY** — staging deployment, secrets provisioning, and cloud
  targets require human authorization. No compliance claims beyond implemented controls below.

## 1. Architecture status

- Executable chain now exists where the audit (§1) said none did:
  builder→decide→run→verify covered by `tests/integration/test_p6_executable_slice.py`
  (header: "fixture to verified report, no new engines"); P7 advisory pipeline
  wired to `P6_HANDOFF` (`test_p7_advisory_pipeline.py`); P8 runtime connected to
  P7 inputs via Fake/Replay (`test_p8_runtime_to_p7.py`); API exposes the
  controlled path (`test_api_execute_verify.py` header: "POST /execute and POST
  /verify via the controlled path").
- Gap-register deltas: G01/G02/G03/G04 closed by slices above; G06 (dual approval
  stacks), G07 (`finance/llm/` bypass), G08 (two orchestrators) still open —
  frozen contracts untouched, no canonicalization attempted.

## 2. Frozen boundaries

- P6-01…08, P7-01…08, P8-01…04 contracts frozen; no slice altered them
  (each slice header/docstring asserts additive-only).
- Evidence SHAs (all present in `git log` this session): `6373489` (P8-04
  contract frozen post-merge), `9fad082` (P8-03 runtime state/persistence/replay),
  `c9eb3b6` (P8-04 durable orchestration boundary).
- Slice SHAs: `e28c149`, `680f3bd`, `5f75036`, `5a17730`, `f65d480`,
  `218f08d`, `6cb8396`, `7b5d385`.

## 3. Test counts

- New suites (this branch, counted via `grep -c "def test_"` this session):
  19 (P6 slice) + 7 (P7 pipeline) + 9 (P8→P7) + 5 (P8 PG durability) + 9 (API
  execute/verify) + 11 (observability) + 16 (adversarial) + 5 (LLM eval) = 81.
- Full suite: 3441 passed + 13 pre-existing failures by category — VERIFIED
  by main-agent full runs (K1 isolation waived; 4 LLM-network; 2 ministack;
  4 py-runtime-api; 1 matcher; 1 migrations; 1 stripe-purity).
- K1 error-hygiene rule (`docs/architecture/P7-07_AGENT_EVALUATION_CONTRACT.md:163`):
  enforced by `test_15_canary_secrets_absent_everywhere`; any broader K1 waiver
  status — VERIFIED from gate history: P7-08 isolation K1 carries a standing
  adjudicated waiver (frozen test untouched; fails on any post-P7 branch by
  construction); P7-07 error-hygiene itself is enforced by test_15.

## 4. E2E status

- `tests/e2e/` holds 2 files (`test_partial_refund_resolution.py`,
  `test_investigation_orchestration.py`) — partial per audit §7; not re-run here.
- Closest to E2E green: A01 chain (P6 slice happy + API happy + verify happy).

## 5. Security status

- Adversarial suite: 16 attacks, typed defenders (`218f08d`); covers cross-tenant,
  cross-situation, replay, stale-version, forged evidence, approval laundering,
  contradictory evidence, malformed output, prompt injection, timeout/retry,
  fallback equivalence, canary secrecy, crash-restart.
- Redaction implemented: `apps/api/observability.py` header — records carry
  IDs/route/disposition/latency only; all values scrubbed via
  `shared.safety.secrets`; request-ID via `RequestIDMiddleware` (`X-Request-ID`).
- Open items: fresh-DB tenant/stripe breakages proven pre-existing —
  VERIFIED by counterfactual runs (stashed-changes re-run + clean-DB runs show
  identical failures without new code: tenant setup needs alembic base the
  fixture never applies; stripe idempotency has a paramstyle bug).

## 6. LLM-eval status

- Golden: 14 cases verified in `tests/fixtures/eval_golden/llm_quality_golden.json`
  (`cases` array length 14); runner asserts ≥12 (`test_golden_suite_green_on_valid_outputs`).
- Deterministic-only: 5 regression tests (`test_report_schema`,
  `test_golden_suite_green_on_valid_outputs`,
  `test_degraded_variants_score_below_bar`,
  `test_quality_regression_never_alters_safety`,
  `test_injection_cases_reference_security_fixtures`); scripted outputs, no network.
- Live-provider eval NOT run — stated explicitly: no creds provisioned, no live
  LLM calls made; `evals/llm/` groq smoke remains gated/manual per audit §7.

## 7. Infrastructure status

- Compose files present: `docker-compose.yml`, `docker-compose.test.yml`,
  `docker-compose.override.yml`, `docker-compose.ministack.yml`,
  `docker-compose.phoenix.yml`, `docker-compose.langfuse.yml`.
- Staging NOT deployed; no cloud targets provisioned (no evidence of either
  observed this session).
- Migration available for P8 durability: `c9d5e7f1a204_add_p8_durability_tables.py`
  (alembic versions dir, alongside 3 earlier revisions).

## 8. Known limitations

- In-memory P8 stores remain the default path; PG backend exists
  (`test_p8_postgres_durability.py`, 5 tests; migration `c9d5e7f1a204`) but is
  unwired to the API path — VERIFIED: routes use SQLite/in-memory doubles; no
  route constructs the PG store (PG backend tested standalone only).
- `finance/llm/` legacy stack still present (audit G07, open).
- Dual approval stacks (`finance/approval/` vs `finance/approvals/`)
  uncanonicalized (audit G06, open).
- OpenRouter network flake — VERIFIED flaky across runs (failed baseline, passed
  3 full runs, failed 1; network-dependent, no creds in this environment).
- Audit-era env note (G10: `.venv`/`.lock` perms, missing `polars`) superseded
  by `UV_PROJECT_ENVIRONMENT=.venv-aparna` workflow used for acceptance runs.

## 9. Rollback

- Code: `git revert` per atomic commit (slices are one commit each;
  newest-first: `7b5d385`, `6cb8396`, `218f08d`, `f65d480`, `5a17730`,
  `5f75036`, `680f3bd`, `e28c149`).
- DB: `alembic downgrade` for `c9d5e7f1a204` (P8 durability tables) before
  reverting `5a17730`.
- Docs-only commits (`a66b0db`, `6373489`) revert with no runtime effect.

## 10. Operational risks

| Risk | Signal | Mitigation / owner action |
|---|---|---|
| PG backend unwired to API | §8 | human wires + authorizes staging DB |
| Fresh-DB tenant/stripe failures | §5 open items | reproduce on provisioned PG before staging |
| Legacy bypass stacks (G07/G08) | §1 | retire or gate behind P8 seam; human decision |
| Secret handling at deploy | redaction is log-only | human provisions secrets store; no creds in repo |
| Live-LLM behavior unknown | §6 | run gated provider eval before any LLM-backed staging |

## 11. Deployment decision

**NOT READY.** Staging deployment, secrets provisioning, and cloud targets
require human authorization. Ship-blockers: provision PG + reproduce RLS/stripe
files green; run (gated) live-provider eval; human sign-off on legacy-stack
retirement and P8-PG API wiring. Nothing in this document authorizes a deploy.
