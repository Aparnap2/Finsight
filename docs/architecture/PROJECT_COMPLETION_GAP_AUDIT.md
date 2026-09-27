# Phase 0 — Project Completion Gap Audit (FinSight)

- Phase: 0 (read-only audit, no behavior change)
- Base: `6373489`
- Branch: `chore/project-completion-gap-audit`
- Date: 2026-09-27
- Mode: DOC-ONLY. Scope = this file only (`docs/architecture/PROJECT_COMPLETION_GAP_AUDIT.md`).
- Inputs: four read-only surveys P6 (engines/approvals/execution/verification + API surface), P7 (producers/control-plane), P8 (runtime/durability/orchestration), tests+infra (~581 test functions, Docker/CI/env). Trusted as stated; filenames/symbols below verified only to citation level.
- Normative keywords: MUST / MUST NOT per file. No new abstractions. No frozen-contract changes; genuine defects require failing-test evidence and a FIX entry.

## 1. Current executable workflow (honest, thin)

There is no end-to-end executable workflow. What runs in isolation:

- Boot: `uvicorn apps.api.main:app`; `uv sync`; `compose` (`postgres`/`redis`/`qdrant`); `GET /health`.
- P6 seams (callable directly, no chain): `finance/policy/execution_policy.check`, `finance/approval/decision.decide`, `finance/approval/authorization.mint/verify_authorization`, `finance/approvals/service.ApprovalService` (DB-backed HITL CAS), `finance/proposals/builder`, `finance/execution/executor.Executor.run`, `finance/verification/orchestrator.verify_execution`, `finance/verification/minter.mint_report`.
- P7 seams (callable directly, no pipeline): `agents/discovery/engine.py:30 discover()`, `agents/reasoning/resolution.py:221 reason()`, `agents/brief/brief.py:196 brief()`, `agents/evaluation/harness.py:33 evaluate()->str`, `agents/integration/control_plane.py:90 ControlPlaneGate.admit()->GateResult`.
- P8 seams (pure logic, in-memory): `contract.py: check_budget/classify/call_with_retry/validate_raw_output`, `execution.py: execute_run`, `durability.py: projections/seals/recover/resume`, `orchestration.py: submit/schedule/resume/recover/cancel/resubmit/handoff`.
- MUST NOT claim: builder→decide→run→verify chain, discover→reason→brief→admit pipeline, durable execution, or LLM-backed reasoning in P7-04–08. None exists.

## 2. P6 API table

| Symbol | File | Status |
|---|---|---|
| `execution_policy.check` | `finance/policy/execution_policy.py` | implemented, isolated |
| `decision.decide` (G1–G6) | `finance/approval/decision.py` | implemented, isolated |
| `authorization.mint` / `verify_authorization` (G7) | `finance/approval/authorization.py` | implemented, isolated |
| `ApprovalService` (DB HITL CAS) | `finance/approvals/service.py` | implemented, isolated |
| `builder` | `finance/proposals/builder.py` | implemented, no caller |
| `Executor.run` (14-step, idempotency ledger) | `finance/execution/executor.py` | implemented, no caller |
| `verify_execution` (R1/R2/R3 re-read) | `finance/verification/orchestrator.py` | implemented, no caller |
| `mint_report` | `finance/verification/minter.py` | implemented, no caller |
| `POST /approvals/decide` | `apps/api` | exposed (only P6 route) |
| `POST /execute`, `POST /verify` (or equivalent) | `apps/api` | absent |

## 3. P7 producer table

| Symbol | File | Status |
|---|---|---|
| `discover()` | `agents/discovery/engine.py:30` | implemented, isolated |
| `reason()` | `agents/reasoning/resolution.py:221` | implemented, isolated |
| `brief()` | `agents/brief/brief.py:196` | implemented, isolated |
| `evaluate()->str` | `agents/evaluation/harness.py:33` | implemented, test/docs only |
| `ControlPlaneGate.admit()->GateResult` (`BLOCKED`\|`P6_HANDOFF`) | `agents/integration/control_plane.py:90` | implemented, isolated |
| `discover→reason→brief→admit` pipeline caller | — | absent |
| legacy orchestrator loop | `agents/` (legacy) | exists, does not consume P7-04–08 |
| LLM dependency in P7-04–08 producers | — | none (deterministic; LLM only in P4.5-era modules) |

## 4. P8 capability table (implemented vs stub)

| Capability | Module | Status |
|---|---|---|
| `Budget`, `FailureKind`, `RetryPolicy`, `ProviderAdapter.complete`, `RunIdentity` | `contract.py` | implemented |
| `check_budget`, `classify`, `call_with_retry`, `validate_raw_output` | `contract.py` | implemented, REAL (budgets/retry) |
| `replay_run` | `contract.py` | stub (`->None`) |
| `execute_run`, states, `Attempt`/`RunRecord`, in-memory store | `execution.py` | implemented, zero backends |
| projections, seals, `recover`/`resume`, in-memory dicts | `durability.py` | implemented, zero backends |
| workflow states/records, `submit`/`schedule`/`resume`/`recover`/`cancel`/`resubmit`/`handoff` | `orchestration.py` | implemented, zero backends |
| `backend_tokens()` | `orchestration.py` | stub (`==()`) |
| telemetry | P8 | stub / observer-only |
| real-call adapters | `shared/llm/openai_compatible.py` (OpenAI SDK), `shared/llm/groq.py` (stdlib `urllib`) | implemented, needs creds+network; `Fake`/`Replay` otherwise |
| `StructuredModelOutput`/`Handoff` → P7 types bridge | — | absent by design |
| parallel stack bypassing P8 seam | `finance/llm/` | legacy, MUST NOT reuse |

## 5. Gap register

Format: `GAP-ID | description | class | owner layer | size`. Each gap has exactly one class.

- G01 | chain `proposals.builder→ApprovalService.decide→Executor.run→verify_execution` has no caller | INTEGRATE | `finance` | M
- G02 | expose `Executor.run` / `verify_execution` via API (only `POST /approvals/decide` exists; no `/execute`, no `/verify`) | IMPLEMENT | `apps` | M
- G03 | `discover→reason→brief→admit` has no pipeline caller | INTEGRATE | `agents` | M
- G04 | `ControlPlaneGate.admit()->GateResult` → P6 handoff unwired (`P6_HANDOFF` unconsumed) | INTEGRATE | `agents` | S
- G05 | `StructuredModelOutput`/`Handoff` → P7 types bridge absent (by design, still a gap) | INTEGRATE | `agents` | S
- G06 | dual approval stacks `finance/approval/` vs `finance/approvals/` uncanonicalized | FIX | `finance` | M
- G07 | `finance/llm/` parallel stack bypasses P8 seam | FIX | `finance` | M
- G08 | two orchestrators (P7 vs legacy loop); legacy does not consume P7-04–08 | FIX | `agents` | M
- G09 | `accounting/mock.py` vs `stripe/` + webhooks overlap unresolved | FIX | `finance` | S
- G10 | local env broken: `.venv`/`.lock` permission-denied, system python missing `polars` (see §9) | FIX | `shared` (tooling) | S
- G11 | persistent backends for `execution.py`/`durability.py`/`orchestration.py` stores absent (in-memory only) | IMPLEMENT | `shared` | L
- G12 | `replay_run->None` stub; `backend_tokens()==()` stub; telemetry observer-only | IMPLEMENT | `shared` | S
- G13 | pass-stubs in P7-era files | IMPLEMENT | `agents` | S
- G14 | budgets/retry REAL — reuse `check_budget`/`call_with_retry`/`classify` as-is | REUSE | `shared` | S
- G15 | deterministic P7-04–08 producers (no LLM) — reuse without adding LLM deps | REUSE | `agents` | S
- G16 | `evaluate()->str` harness exists but test/docs-only; no CI gate | TEST | `agents` | S
- G17 | integration suite postgres-gated (5 files, ~14 tests); unit/contract cannot validate seams end-to-end | TEST | `tests` | M
- G18 | security only partial (8 prompt-injection fixtures); LLM-eval gated/manual (`tests/llm/`, `evals/llm/`) | TEST | `tests` | M
- G19 | real-call adapters (`openai_compatible.py`, `groq.py`) need creds+network; no provisioned target | DEPLOYMENT | `shared` | S
- G20 | durable-run persistence/observability backends unprovisioned (compose exists, unwired to P8) | DEPLOYMENT | `shared` | M
- G21 | `finance/legacy/` + `finance/legacy_execution/` (9 files, superseded) | NOT NEEDED | `finance` | S
- G22 | legacy FP&A nodes (`scenario.py`, `driver/`, `commentary/`, `variance/`, `forecast/`, `recommendation/`) superseded by P7-04–08 | NOT NEEDED | `agents` | M
- G23 | legacy orchestrator loop as runtime path (keep only for reference) | NOT NEEDED | `agents` | S

Frozen-contract rule: G06–G09 MUST NOT rename/alter frozen P6-01–P6-08 / P7 / P8 contracts; genuine defects need failing-test evidence first.

## 6. Dead / duplicate list

| Item | Verdict |
|---|---|
| `finance/legacy/` + `finance/legacy_execution/` (9 files) | NOT NEEDED (G21) |
| legacy FP&A nodes: `scenario.py`, `driver/`, `commentary/`, `variance/`, `forecast/`, `recommendation/` | NOT NEEDED (G22) |
| legacy orchestrator loop (non-P7 consumer) | NOT NEEDED (G23) |
| dual approval stacks `approval/` vs `approvals/` (canonicalize, do not delete blindly) | FIX (G06) |
| `finance/llm/` bypass stack | FIX — retire or gate behind P8 seam (G07) |
| `accounting/mock.py` vs `stripe/`+webhooks overlap | FIX — single owner (G09) |
| two orchestrators | FIX — one durable path via P8-04 (G08) |

## 7. Test-layer matrix (12 layers)

| Layer | Verdict | Evidence |
|---|---|---|
| unit | present | ~485 functions |
| contract | present | 18 files |
| integration | partial | 5 files, ~14 tests, postgres-gated |
| provider | absent | no provider-adapter gate wired |
| e2e | partial | 2 files |
| failure-injection | partial | `failure/` 1 dir |
| replay | absent | `replay_run->None`; `Fake`/`Replay` unexercised |
| security | partial | 8 prompt-injection payloads; no gate |
| llm-eval | partial | `tests/llm/` 4 tests; `evals/llm/` README + groq smoke (gated/manual) |
| cloud-emulation | absent | compose×6 exists, no emulation gate |
| load | absent | nothing observed |
| deployment-smoke | partial | `GET /health`, Dockerfile×3, CI×3, alembic 3 versions, seeds (10 dirs) + `tenants/demo` |

Suite cannot run locally (broken venv — see §9); counts trusted from Survey D.

## 8. First integration slice (PROPOSAL, not an order)

PROPOSAL (suggested, not sequenced): deterministic fixture drives `finance/proposals/builder → finance/approvals/service.ApprovalService.decide → finance/execution/executor.Executor.run → finance/verification/orchestrator.verify_execution`, asserting idempotency-ledger + R1/R2/R3 re-read + `mint_report` without new abstractions and without frozen-contract changes. Requires G10 (env FIX) and G17 (TEST) first; consumes G01/G14/G15.

## 9. Environment repair note (FIX)

G10 (FIX, `shared`/tooling, S): local boot documented (`uvicorn apps.api.main:app`, `uv sync`, compose `postgres`/`redis`/`qdrant`) but local env is broken — `.venv`/`.lock` permission-denied, system python missing `polars`. Repair perms/ownership, regenerate venv via `uv sync`, verify `python -m pytest --collect-only`. No code changes under this entry.
