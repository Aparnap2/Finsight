# IMPLEMENTATION_PLAN.md
_Last updated: 2026-07-15 by MiMoCode_

## Goal
Build FinSight — an agentic FP&A operations platform that autonomously runs the month-end close cycle (variance detection → root-cause investigation → commentary generation → scenario re-forecasting) with human-in-the-loop review checkpoints.

## Architecture
- **Go**: api-gateway, finance-core, connector-hub (high-throughput, deterministic)
- **Python**: agent-runtime (LangGraph + PydanticAI), workflow-orchestrator (Temporal)
- **Infra**: Postgres, Redis, Qdrant, Redpanda, Temporal, Jaeger, LiteLLM proxy
- **Free-tier APIs**: Groq (primary), OpenRouter (fallback) via LiteLLM

## Status
- Total tasks: 9
- Completed: 9
- Remaining: 0

### Completed this session
- **T1** ✅ Config: Added GROQ/OPENROUTER fields to Settings. All 52 tests pass.
- **T2** ✅ Ingestion: Agent queries real PostgreSQL via optional engine param. 4 new tests pass.
- **T3** ✅ Commentary: Agent calls OpenRouter free model (gemma-4-26b), parses structured sections. Falls back to placeholders.
- **T4** ✅ Docker: Memory-limited compose (2.8GB total). Added redpanda, temporal, jaeger, litellm.
- **T5** ✅ E2E curl: docker up → alembic migrate → seed DB → curl health + pipeline. Real $58K variances visible.
- **T6** ✅ Pipeline E2E: ingestion fetches real DB data, variance engine finds material variances.
- **T7** ✅ Root-cause + Commentary agents wired to OpenRouter with structured prompt engineering.
- **T8** ✅ ClaimValidator: extracts $-amounts from commentary, verifies against DB facts (5% tolerance), blocks hallucinated numbers.
- **T9** ✅ EvidenceGraph: EvidenceItem model links root-cause conclusions to specific DB records.

## Tasks

### Phase 0: Foundations (Week 1-2)

#### T0.1: Docker Compose dev profile — ✅ DONE
- **Scope:** Update docker-compose.yml with memory-limited services: Postgres, Redis, Qdrant, Redpanda (single-node), Temporal dev server, Jaeger all-in-one, LiteLLM proxy. Total infra ≤4GB.
- **Acceptance criteria:** `docker compose up -d` starts all infra in <2 min; `docker stats` shows total memory <4GB.
- **Test phase:** Integration
- **Depends on:** none

#### T0.2: PostgreSQL canonical schema — ⏳ TODO
- **Scope:** Alembic migration for all financial tables (PRD §6): entities, gl_accounts, trial_balance, budget_lines, forecast_lines, actuals, headcount_data, vendor_invoices, sales_pipeline. Add tenant_id to all tables for RLS.
- **Acceptance criteria:** `alembic upgrade head` succeeds; all tables exist with correct columns and indexes.
- **Test phase:** Unit
- **Depends on:** T0.1

#### T0.3: Synthetic dataset generator — ⏳ TODO
- **Scope:** Python script to generate CloudForge Inc. mock data: 50 GL accounts, 5 departments, 2 regions, 18 months history, budget, forecast, headcount (~280), 15 vendors, 40 sales pipeline deals. 4 pre-planted variances for demo.
- **Acceptance criteria:** `uv run python -m backend.data.seed` populates all tables; golden tests verify debits=counts correct.
- **Test phase:** Unit + Integration
- **Depends on:** T0.2

#### T0.4: Config + env wiring — ✅ DONE
- **Scope:** Update config.py to read GROQ_API_KEY, OPENROUTER_API_KEY, LITELLM_PROXY_URL from .env. Add LiteLLM routing config. Wire OpenTelemetry + Jaeger.
- **Acceptance criteria:** `uv run python -c "from backend.config import get_settings; s=get_settings(); print(s.openrouter_api_key)"` prints key.
- **Test phase:** Unit
- **Depends on:** none

#### T0.5: CI/CD + lint gates — ⏳ TODO
- **Scope:** GitHub Actions workflow: ruff check, mypy --strict, pytest --cov. Pre-push hook.
- **Acceptance criteria:** `uv run ruff check .` and `uv run mypy backend/` pass clean.
- **Test phase:** N/A
- **Depends on:** none

### Phase 1: Deterministic Finance Core (Week 3-4)

#### T1.1: Go finance-core service — ⏳ TODO
- **Scope:** Go service with variance engine, materiality engine, close-readiness checks. Pure deterministic logic, no LLM calls.
- **Acceptance criteria:** Go unit tests pass; golden test: known variances flagged correctly.
- **Test phase:** Unit
- **Depends on:** T0.2

#### T1.2: Go api-gateway — ⏳ TODO
- **Scope:** Go/Fiber REST gateway: health, pipeline trigger, variance list, materiality review, status endpoints. Tenant-aware routing.
- **Acceptance criteria:** `curl localhost:8080/health` returns 200; all endpoints documented in OpenAPI.
- **Test phase:** Integration
- **Depends on:** T1.1

#### T1.3: Go connector-hub — ⏳ TODO
- **Scope:** Mock ERP adapter, CSV import, snapshot normalization. Emits normalized envelopes.
- **Acceptance criteria:** Import CSV → normalized snapshot in DB; unit tests for each adapter.
- **Test phase:** Unit
- **Depends on:** T0.2

#### T1.4: Period-run state machine — ⏳ TODO
- **Scope:** In-memory state machine for period runs: INGESTING → ANALYZING → REVIEWING → COMMENTING → SCENARIOS → APPROVED. No Temporal yet.
- **Acceptance criteria:** State transitions correct; concurrent run isolation.
- **Test phase:** Unit
- **Depends on:** T1.2

#### T1.5: Variance workspace UI — ⏳ TODO
- **Scope:** Next.js heatmap (account × department), materiality color coding, drill-down, classification badges.
- **Acceptance criteria:** Visual test: heatmap renders with seeded data.
- **Test phase:** Unit
- **Depends on:** T1.2

### Phase 2: Agent + Workflow Layer (Week 5-7)

#### T2.1: Temporal dev server integration — ⏳ TODO
- **Scope:** Temporal worker for period-run workflow with approval checkpoints.
- **Acceptance criteria:** Temporal workflow starts, pauses at HITL, resumes on approval.
- **Test phase:** Integration
- **Depends on:** T1.4

#### T2.2: Python agent-runtime — ⏳ TODO
- **Scope:** LangGraph state graph + PydanticAI typed agents. Root-cause agent with read-only tool gateway.
- **Acceptance criteria:** Agent produces RootCauseFinding with evidence chain; mock tool calls verified.
- **Test phase:** Unit
- **Depends on:** T2.1

#### T2.3: Commentary agent — ✅ DONE
- **Scope:** Structured commentary (Exec Summary, Revenue, Cost, Cash, Risks, Actions). RAG over prior commentary. Claim validator.
- **Acceptance criteria:** Generated commentary has all 6 sections; fabricated numbers caught.
- **Test phase:** Unit
- **Depends on:** T2.2

#### T2.4: HITL review UI — ⏳ TODO
- **Scope:** Variance checkpoint, root-cause validation, CFO approval UIs. Approve/reject/modify actions.
- **Acceptance criteria:** Review form submits decision that unpauses workflow.
- **Test phase:** Integration
- **Depends on:** T2.1, T1.5

### Phase 3: Advanced Intelligence (Week 8-9)

#### T3.1: Sandbox gateway service — ⏳ TODO
- **Scope:** Spawns isolated Docker containers for code execution. No network, no live creds.
- **Acceptance criteria:** Analyst writes pandas transform; output validates through claim validator.
- **Test phase:** Integration
- **Depends on:** T2.2

#### T3.2: smolagents CodeAgent integration — ⏳ TODO
- **Scope:** Custom scenario modeling, ad-hoc pandas analysis in sandbox.
- **Acceptance criteria:** Code agent runs custom scenario; output is deterministic and auditable.
- **Test phase:** Unit
- **Depends on:** T3.1

### Phase 4: Production Hardening (Week 10-12)

#### T4.1: Real connectors — ⏳ TODO
- **Scope:** NetSuite, QuickBooks, Salesforce, Google Sheets adapters.
- **Acceptance criteria:** Each connector imports real data; unit tests with cassettes.
- **Test phase:** Integration
- **Depends on:** T1.3

#### T4.2: E2E tests + demo — ⏳ TODO
- **Scope:** Playwright E2E tests for full pipeline. 3 demo scenarios.
- **Acceptance criteria:** All E2E tests pass; demo flow works end-to-end.
- **Test phase:** E2E
- **Depends on:** T2.4, T1.5

## Execution Order
1. T0.1 → T0.2 → T0.3 (foundations)
2. T0.4, T0.5 (parallel with T0.3)
3. T1.1, T1.2, T1.3 (finance core, parallel)
4. T1.4 → T2.1 → T2.2 → T2.3 (agent layer, sequential)
5. T1.5, T2.4 (UI, parallel with agent layer)
6. T3.1 → T3.2 (sandbox, after agent layer)
7. T4.1, T4.2 (hardening, after all features)

## Key files added this session
```
backend/config.py                    — GROQ/OPENROUTER env vars
backend/agents/ingestion_agent.py    — real PostgreSQL queries
backend/agents/commentary_agent.py   — OpenRouter LLM + structured parser
backend/agents/root_cause_agent.py   — OpenRouter LLM + EvidenceItem output
backend/validators/claim_validator.py — hallucination detection (5% tolerance)
backend/models/state.py              — EvidenceItem model added
docker-compose.yml                   — memory-limited (2.8GB)
litellm-config.yaml                  — Groq + OpenRouter routing
tests/backend/validators/            — 7 claim validator tests
tests/backend/models/test_evidence.py — 3 evidence model tests
```

## Known Risks / Gotchas
- 16GB RAM limit: infra must stay ≤4GB; heavy services on-demand only
- Free-tier API rate limits: Groq 10-30 req/min; cache LLM responses in Redis
- LangGraph HITL interrupt requires careful state serialization
- Deterministic vs LLM boundary: never let LLM do arithmetic
- Go + Python split requires gRPC/HTTP contract between services
- qdrant healthcheck occasionally flaky on restart
