# IMPLEMENTATION_PLAN.md
_Last updated: 2026-07-14 by MiMoCode_

## Goal
Build FinSight — an agentic FP&A operations platform that autonomously runs the month-end close cycle (variance detection → root-cause investigation → commentary generation → scenario re-forecasting) with human-in-the-loop review checkpoints.

## Status
- Total tasks: 20
- Completed: 0
- Remaining: 20

## Tasks

### Task 1: Research LangGraph multi-agent patterns + FastAPI + Next.js — ⏳ TODO
- **Scope:** Research LangGraph StateGraph supervisor patterns, FastAPI async patterns, Next.js App Router conventions. Review existing open-source examples of multi-agent financial analysis systems.
- **Acceptance criteria:** Documented key patterns and conventions to follow; identified any library version constraints.
- **Test phase:** N/A (research only)

### Task 2: Project scaffolding — ⏳ TODO
- **Scope:** Docker Compose with PostgreSQL, Redis, Qdrant. Backend Python shell (FastAPI + uvicorn). Frontend Next.js shell. pyproject.toml, package.json, Dockerfiles.
- **Acceptance criteria:** `docker compose up` brings up all services; FastAPI returns 200 on `/health`; Next.js renders landing page.
- **Test phase:** Integration
- **Depends on:** T1

### Task 3: Synthetic dataset seed — ⏳ TODO
- **Scope:** CloudForge Inc. mock data generator: 50 GL accounts, 5 departments, 2 regions, 18 months history (Jan 2025–Jun 2026), budget, forecast, headcount (~280), 15 vendors, 40 sales pipeline deals. Seed 4 pre-planted variances for demo.
- **Acceptance criteria:** Seed script populates all tables; query sample confirms data integrity (debits=credits, counts correct).
- **Test phase:** Unit + Integration
- **Depends on:** T2, T4

### Task 4: Database models — ⏳ TODO
- **Scope:** SQLAlchemy models for all financial tables (PRD §6): entities, gl_accounts, trial_balance, budget_lines, forecast_lines, actuals, headcount_data, vendor_invoices, sales_pipeline. Agent state tables: agent_runs, agent_state, variances, root_causes, commentary_drafts, scenarios, review_logs.
- **Acceptance criteria:** Alembic migration runs clean; all models pass `alembic upgrade head` + `alembic downgrade -1 && alembic upgrade head`.
- **Test phase:** Unit
- **Depends on:** T2

### Task 5: FastAPI backend — ⏳ TODO
- **Scope:** FastAPI app with config (env vars, DB URLs), health endpoint, pipeline trigger endpoint, agent status endpoint, review submission endpoint. Pydantic models for PipelineState and all agent I/O types.
- **Acceptance criteria:** FastAPI test client hits all endpoints; OpenAPI docs at `/docs` show all routes.
- **Test phase:** Unit
- **Depends on:** T4

### Task 6: LangGraph orchestrator — ⏳ TODO
- **Scope:** StateGraph definition with 6 agent nodes, conditional edges (skip root-cause if no material variances), 3 HITL interrupt points, error handling (3x retry → pause). PipelineState schema.
- **Acceptance criteria:** Unit test: mock agents, verify state transitions; HITL interrupt/pause/resume works.
- **Test phase:** Unit
- **Depends on:** T5

### Task 7: Ingestion Agent — ⏳ TODO
- **Scope:** Fetch trial balance, GL detail, budget, forecast from DB. Validate completeness (no nulls, accounts present). Reconcile debits=credits. LLM anomaly flagging for unusual patterns.
- **Acceptance criteria:** Unit test with seeded data returns validated ActualsSnapshot and BudgetSnapshot; anomaly flags surfaced for edge cases.
- **Test phase:** Unit
- **Depends on:** T6

### Task 8: Variance Detection Agent — ⏳ TODO
- **Scope:** Compute actual vs budget/forecast variances (deterministic Python). Apply materiality (>£5k AND >5%). Aggregate by department/account. LLM classification (timing/volume/rate/one-time/error/strategic).
- **Acceptance criteria:** Unit test: known variances flagged correctly; classification outputs match expected categories for demo data.
- **Test phase:** Unit
- **Depends on:** T6

### Task 9: Root-Cause Investigation Agent — ⏳ TODO
- **Scope:** ReAct loop with tools: drill_gl_detail, query_headcount, query_vendor_invoices, query_sales_pipeline, query_fx_rates, search_historical_variances (Qdrant RAG), search_finance_policy (Qdrant RAG).
- **Acceptance criteria:** Unit test: given material variance, agent produces RootCauseFinding with evidence chain; mock tool calls verify correct tool selection.
- **Test phase:** Unit
- **Depends on:** T12

### Task 10: Commentary Agent — ⏳ TODO
- **Scope:** Generate structured commentary (Exec Summary, Revenue, Cost, Cash, Risks, Actions). RAG over prior commentary for tone consistency. Deterministic validation: all cited numbers traceable to source.
- **Acceptance criteria:** Unit test: generated commentary contains all 6 sections; number validation catches fabricated figures.
- **Test phase:** Unit
- **Depends on:** T12

### Task 11: Scenario Re-Forecasting Agent — ⏳ TODO
- **Scope:** LLM selects relevant scenarios from root causes. Deterministic Python models (revenue, cost, cashflow) compute financial impacts. LLM explains results and assesses probability.
- **Acceptance criteria:** Unit test: scenario outputs include revenue/EBITDA/cash impacts; deterministic models produce reproducible numbers.
- **Test phase:** Unit
- **Depends on:** T12

### Task 12: Tool implementations — ⏳ TODO
- **Scope:** All tool functions called by agents: gl_tools (drill_gl_detail, fetch_trial_balance), headcount_tools, vendor_tools, pipeline_tools, rag_tools (Qdrant search). Each tool queries PostgreSQL or Qdrant, returns structured Pydantic objects.
- **Acceptance criteria:** Unit test for each tool against seeded data; RAG tools test with mock Qdrant collections.
- **Test phase:** Unit
- **Depends on:** T3, T4

### Task 13: WebSocket + real-time updates — ⏳ TODO
- **Scope:** WebSocket endpoint for agent progress streaming. Redis pub/sub for agent state changes. Frontend receives real-time agent status updates during pipeline execution.
- **Acceptance criteria:** Integration test: WebSocket connection receives agent progress events as pipeline runs.
- **Test phase:** Integration
- **Depends on:** T5, T6

### Task 14: Next.js frontend shell — ⏳ TODO
- **Scope:** Next.js App Router layout, API client (fetch/axios), WebSocket hook, Tailwind CSS setup, navigation sidebar, theme.
- **Acceptance criteria:** `pnpm dev` renders layout with sidebar navigation; API client connects to FastAPI backend.
- **Test phase:** Unit
- **Depends on:** T2

### Task 15: Frontend — Variance Heatmap — ⏳ TODO
- **Scope:** Account × department grid visualization, materiality color coding, sort/filter, classification badges, confidence scores.
- **Acceptance criteria:** Visual regression test shows heatmap renders with seeded data.
- **Test phase:** Unit
- **Depends on:** T14, T8

### Task 16: Frontend — Commentary Editor — ⏳ TODO
- **Scope:** Draft commentary display with section editing, edit tracking, version history, approval workflow UI.
- **Acceptance criteria:** Component renders commentary sections; edit/save works.
- **Test phase:** Unit
- **Depends on:** T14, T10

### Task 17: Frontend — Scenario Explorer — ⏳ TODO
- **Scope:** Scenario cards with financial impact tables, comparison view, probability badges, forecast overlay.
- **Acceptance criteria:** Component renders scenario data from API.
- **Test phase:** Unit
- **Depends on:** T14, T11

### Task 18: Frontend — Agent Timeline + HITL Review — ⏳ TODO
- **Scope:** Agent run timeline visualization (horizontal pipeline), 3 review checkpoint UIs (variance review, root-cause validation, CFO review). Approve/reject/modify actions.
- **Acceptance criteria:** Timeline renders agent progress; review forms submit decisions that unpause the pipeline.
- **Test phase:** Integration
- **Depends on:** T14, T6

### Task 19: Langfuse observability — ⏳ TODO
- **Scope:** Langfuse integration for LLM call tracing, agent execution traces, token usage, tool call success rate. Dashboard metrics endpoint.
- **Acceptance criteria:** Langfuse dashboard shows traces for a test pipeline run.
- **Test phase:** Integration
- **Depends on:** T6

### Task 20: E2E tests + demo scenarios — ⏳ TODO
- **Scope:** Playwright E2E tests for full pipeline flow. 3 demo scenarios pre-seeded (deal slippage, vendor price increase, clean month). End-to-end smoke test.
- **Acceptance criteria:** Playwright tests pass for all 3 demo scenarios; `docker compose up` → trigger pipeline → review → approve flow works end-to-end.
- **Test phase:** E2E
- **Depends on:** T15, T16, T17, T18

## Known Risks / Gotchas
- LangGraph HITL interrupt mechanism requires careful state serialization — checkpoint/resume must persist correctly across agent boundaries
- LLM token budget: Root-Cause agent may make many tool calls in ReAct loop — need to cap iterations
- Deterministic vs LLM boundary is critical: never let LLM do arithmetic — all financial calculations in Python
- Qdrant collections need sufficient seed data for RAG to be useful in demo
- Temporal excluded from MVP (PRD §11) — using LangGraph checkpointing instead
- Redpanda excluded from MVP — using direct function calls instead

## Execution Order
1. T1 (Research) → T2 (Scaffold) → T4 (DB models) → T3 (Seed data) + T5 (API) in parallel
2. T6 (Orchestrator) → T7-T11 (Agents) + T12 (Tools) in parallel
3. T14 (Frontend shell) → T15-T18 (Views) in parallel
4. T13 (WebSocket) + T19 (Langfuse) → T20 (E2E tests)
