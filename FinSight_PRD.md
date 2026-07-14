
# PRD: FinSight — Agentic FP&A Operations Platform

## 1. Product Overview

**FinSight** is a vertical agentic AI system that autonomously executes the month-end FP&A cycle — from actuals ingestion through variance detection, root-cause investigation, narrative commentary generation, and scenario re-forecasting. Unlike copilot-style tools that answer ad-hoc questions, FinSight runs a complete, closed-loop FP&A workflow with multi-step agent reasoning, tool-use, inter-agent communication, and human-in-the-loop review at critical checkpoints.

**One-liner:** "The AI FP&A analyst that runs your month-end close — detects what changed, figures out why, writes the board commentary, and re-forecasts — all before your morning standup."

---

## 2. Problem Statement

### The Month-End FP&A Grind

Every month, FP&A teams repeat the same labor-intensive cycle [web:37][web:41]:

- **Days 1–3:** Close books, import actuals from ERP, reconcile subledgers
- **Days 4–6:** Run variance analysis (actual vs budget/forecast), flag material variances (>£5k or >5%)
- **Days 7–8:** Drill into each material variance, identify root causes by cross-referencing GL detail, headcount data, vendor invoices, sales pipeline
- **Days 9–10:** Write management commentary — plain-English explanations of what happened and why, quantified impacts, recommended actions
- **Day 12:** Leadership review — CFO reviews, challenges assumptions, approves
- **Day 15:** Board pack (if board month)

57% of finance teams are now implementing agentic AI, with forecasting cycles shrinking from 3 weeks to 5 days [web:2]. But existing tools fall into two camps:

1. **Heavyweight CPM suites** (OneStream, Pigment, Cube) — full FP&A platforms with bolted-on AI copilots. Not agentic-native.
2. **Lightweight copilots** (ChatFin, Power BI Copilot) — NL Q&A on top of existing data. No autonomous multi-step workflows.

**The gap:** No tool delivers an agentic-native system that autonomously chains variance analysis → root-cause investigation → narrative commentary → scenario re-forecasting in a single coherent pipeline. That end-to-end orchestration is where agentic AI genuinely outperforms copilot-style tools [web:7][web:38].

---

## 3. Target Users

### Primary Persona: FP&A Analyst / Manager

- Works at a mid-market SaaS or B2B company ($10M–$500M ARR)
- Spends 60–70% of time on data gathering, reconciliation, and variance explanation — not strategic analysis
- Uses Excel/Google Sheets as primary tool, pulls data from ERP (NetSuite, Xero, QuickBooks) manually
- Wants to reduce month-end cycle from 10+ days to 3–5 days
- Needs audit trail and human review before numbers go to the CFO

### Secondary Persona: CFO / VP Finance

- Reviews the management pack and challenges assumptions
- Wants faster visibility into what's driving results
- Needs confidence that AI-generated commentary is accurate and defensible

---

## 4. System Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Next.js Frontend (Dashboard)               │
│  Variance Heatmap │ Commentary Editor │ Scenario Explorer    │
│  Agent Run Timeline │ Review Checkpoints                      │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST + WebSocket
┌──────────────────────────┴──────────────────────────────────┐
│                   FastAPI Backend (Python)                    │
│  API Routes │ Auth │ WebSocket Hub │ Review Service          │
└───────┬──────────────────┬─────────────────────┬────────────┘
        │                  │                     │
┌───────▼───────┐ ┌───────▼────────┐  ┌────────▼──────────┐
│  LangGraph     │ │  PostgreSQL    │  │  Qdrant (Vector)  │
│  Agent Engine  │ │  Financial DB  │  │  Commentary RAG   │
│                │ │  Agent State   │  │  Policy RAG       │
│  ┌──────────┐  │ └────────────────┘  └───────────────────┘
│  │Orchestr. │  │
│  │  Agent   │  │ ┌────────────────┐  ┌───────────────────┐
│  └────┬─────┘  │ │  Redis         │  │  Langfuse         │
│       │        │ │  Job Queue     │  │  Observability    │
│  ┌────▼────┐   │ │  Caching       │  │  LLM Tracing      │
│  │Ingestion│   │ └────────────────┘  │  Evaluation       │
│  │ Agent   │   │                     └───────────────────┘
│  └────┬────┘   │
│       │        │ ┌──────────────────┐
│  ┌────▼────┐   │ │  Redpanda        │
│  │Variance │   │ │  Event Stream    │
│  │ Agent   │   │  │  (Inter-agent    │
│  └────┬────┘   │  │   comms, events) │
│       │        │ └──────────────────┘
│  ┌────▼────┐   │
│  │RootCause│   │
│  │ Agent   │   │
│  └────┬────┘   │
│       │        │
│  ┌────▼────┐   │
│  │Commentary│  │
│  │ Agent   │   │
│  └────┬────┘   │
│       │        │
│  ┌────▼────┐   │
│  │Scenario │   │
│  │ Agent   │   │
│  └─────────┘   │
└────────────────┘
```

### Agent Topology (LangGraph State Graph)

The system uses a **LangGraph StateGraph** with a supervisor-orchestrated multi-agent pattern. Each agent is a node in the graph. The orchestrator manages state transitions, human-in-the-loop interrupts, and error handling.

```
                    ┌─────────────┐
                    │  START      │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Ingestion  │
                    │  Agent      │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Variance   │
                    │  Detection  │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  ⏸ REVIEW  │ ← Human checkpoint 1: FP&A Analyst reviews materiality flags
                    │  (HITL)     │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Root-Cause │
                    │  Investiga- │
                    │  tion Agent │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  ⏸ REVIEW  │ ← Human checkpoint 2: FP&A Analyst validates root-cause findings
                    │  (HITL)     │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
       ┌──────▼──┐  ┌─────▼────┐  ┌───▼──────┐
       │Comment- │  │ Scenario  │  │ (parallel)│
       │ary Agent│  │ Agent     │  │           │
       └──────┬──┘  └─────┬────┘  └───┬──────┘
              │           │            │
              └────────────┼────────────┘
                           │
                    ┌──────▼──────┐
                    │  ⏸ REVIEW  │ ← Human checkpoint 3: CFO reviews commentary + forecast
                    │  (HITL)     │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  END        │
                    └─────────────┘
```

### Why LangGraph + Temporal

- **LangGraph** handles the agent-level orchestration: stateful multi-agent workflows, conditional routing, parallel agent execution, and human-in-the-loop interrupts [web:36].
- **Temporal** provides durable execution for the outer workflow — if the month-end pipeline crashes mid-run (LLM API downtime, network failure), Temporal resumes exactly where it left off [web:43][web:44]. This is critical for a finance system where partial execution without audit trail is unacceptable.
- **Pattern:** Temporal wraps the entire month-end close workflow as a durable activity. Inside each activity, LangGraph manages the agent subgraph. Temporal handles retries, timeouts, and resumability; LangGraph handles agent reasoning and state [web:38].

---

## 5. Agent Specifications

### 5.1 Orchestrator Agent

| Aspect | Detail |
|--------|--------|
| **Role** | Top-level supervisor that manages the end-to-end pipeline |
| **Framework** | LangGraph StateGraph supervisor |
| **Responsibilities** | Route state between agents, manage HITL interrupts, handle errors and fallbacks, maintain audit trail |
| **State Schema** | `PipelineState` containing: period, entity_id, actuals_snapshot, budget_snapshot, forecast_snapshot, variances[], root_causes[], commentary_draft, scenarios[], review_decisions[] |
| **Decision Logic** | Conditional edges: if variances are empty → skip root-cause → go to commentary with "no material variances" template |
| **Error Handling** | If any agent fails 3x → pause pipeline, alert user, save partial state to Temporal |

### 5.2 Ingestion Agent

| Aspect | Detail |
|--------|--------|
| **Role** | Pull, validate, and reconcile financial data for the period |
| **Type** | Mostly deterministic (80% deterministic, 20% LLM for anomaly flagging) |
| **Inputs** | Period (month/year), entity_id |
| **Data Sources (v1: mock)** | Mock ERP API returning trial balance, GL detail, actuals. Simulated as PostgreSQL tables with a synthetic SaaS company dataset (12 months of history) |
| **Tools** | `fetch_trial_balance(period)`, `fetch_gl_detail(account, period)`, `fetch_budget(period)`, `fetch_forecast(period)`, `validate_completeness(data)` |
| **LLM Use** | Anomaly detection — flag unusual patterns (e.g., "Revenue suddenly doubled for one account — possible data entry error") |
| **Outputs** | Validated `ActualsSnapshot` and `BudgetSnapshot` objects in pipeline state |
| **Deterministic Components** | Data validation rules, reconciliation logic, completeness checks — all in Python, not LLM |

### 5.3 Variance Detection Agent

| Aspect | Detail |
|--------|--------|
| **Role** | Compute actual vs budget/forecast variances, apply materiality thresholds, classify variance types |
| **Type** | Hybrid (60% deterministic, 40% LLM) |
| **Inputs** | `ActualsSnapshot`, `BudgetSnapshot`, `ForecastSnapshot` from pipeline state |
| **Deterministic Components** | Variance computation (Python arithmetic), materiality threshold application (> £5k AND > 5%), aggregation by department/account/dimension |
| **LLM Use** | Variance classification — given a variance and context, classify as: timing difference, volume variance, rate variance, one-time event, data error, strategic shift. LLM receives structured variance data + account context and outputs a classification with confidence score. |
| **Tools** | `compute_variance(actuals, budget)`, `apply_materiality(variances, threshold)`, `classify_variance(variance, context)`, `fetch_account_metadata(account_id)` |
| **Outputs** | List of `Variance` objects: `{account, department, actual, budget, variance_amount, variance_pct, materiality_flag, classification, confidence_score}` |
| **HITL Checkpoint** | After this agent — FP&A analyst reviews materiality flags, can override thresholds, dismiss variances, or flag additional items for investigation |

### 5.4 Root-Cause Investigation Agent

| Aspect | Detail |
|--------|--------|
| **Role** | For each material variance, drill into underlying data to identify the specific driver. This is the most agentic agent — multi-step reasoning with tool-use. |
| **Type** | Fully agentic (ReAct loop with tools) |
| **Inputs** | List of material `Variance` objects from pipeline state |
| **Reasoning Pattern** | ReAct (Reason + Act): The agent reasons about what data to examine, calls a tool to fetch it, reasons about the result, decides whether to drill deeper or conclude |
| **Tools** | |
| `drill_gl_detail` | Fetch GL line items for a specific account/period — see individual transactions |
| `query_headcount` | Fetch headcount data — new hires, departures, compensation changes by department |
| `query_vendor_invoices` | Fetch AP invoice data — vendor, amount, period, category |
| `query_sales_pipeline` | Fetch CRM pipeline data — deal stage, expected close, amount, region |
| `query_fx_rates` | Fetch FX rates for multi-currency variance analysis |
| `search_historical_variances` | Search Qdrant for similar past variance explanations (RAG) |
| `search_finance_policy` | Search Qdrant for relevant accounting policies (e.g., revenue recognition rules) |
| **Example Reasoning Trace** | "Revenue down 12% in EMEA → call `drill_gl_detail(account=4000, dept=EMEA, period=2026-06)` → see revenue by product line → Product X down 30% → call `query_sales_pipeline(region=EMEA, product=X)` → see $2M deal slipped from June to July → call `search_historical_variances("EMEA revenue deal slippage")` → find similar Q2 2025 pattern → conclude: root cause is deal slippage, not demand loss" |
| **Outputs** | List of `RootCauseFinding` objects: `{variance_id, root_cause_summary, evidence[], confidence_score, recommended_action, similar_historical_case?}` |
| **HITL Checkpoint** | After this agent — FP&A analyst validates findings, can add qualitative context the agent couldn't access (e.g., "we knew this deal would slip, sales team had already flagged it") |

### 5.5 Narrative Commentary Agent

| Aspect | Detail |
|--------|--------|
| **Role** | Generate board-ready written commentary explaining the period's results |
| **Type** | LLM synthesis (90% LLM, 10% deterministic for data formatting) |
| **Inputs** | `Variance` list + `RootCauseFinding` list + period context + historical commentary (RAG) |
| **LLM Use** | Generate structured commentary sections: Executive Summary, Revenue Commentary, Cost Commentary, Cash Position, Key Risks & Opportunities, Recommended Actions. Each section follows finance commentary conventions. |
| **RAG Context** | Qdrant vector search over prior months' commentary to maintain tone consistency and reference prior trends. Also retrieves company-specific commentary guidelines. |
| **Tools** | `search_prior_commentary(period, section)`, `format_variance_bridge(variance)`, `generate_chart_data(findings)` |
| **Outputs** | `CommentaryDraft`: `{executive_summary, revenue_section, cost_section, cash_section, risks_section, actions_section, generated_at, version}` |
| **Quality Guardrails** | Every number in commentary must be traceable to a source data point. Deterministic post-processing validates that all cited figures match the underlying variance/actuals data. If mismatch detected → flag for review. |
| **HITL Checkpoint** | CFO/Manager reviews and edits the commentary. All edits tracked for version history and future RAG context. |

### 5.6 Scenario Re-Forecasting Agent

| Aspect | Detail |
|--------|--------|
| **Role** | Take identified root causes and run what-if scenarios to produce an updated rolling forecast |
| **Type** | Hybrid (30% LLM, 70% deterministic) |
| **Inputs** | `RootCauseFinding` list + current actuals + current forecast |
| **LLM Use** | Scenario generation — given root causes, generate relevant scenarios to model (e.g., "If deal slippage persists through Q3", "If marketing spend normalizes in August", "If the FX rate moves 5% adverse"). LLM selects which scenarios are most relevant. |
| **Deterministic Components** | Scenario modeling — parametric Python models that take assumptions and compute financial impacts. NOT LLM math. Deterministic models for: revenue projection (pipeline-based), cost projection (headcount-based), cash flow projection. |
| **Tools** | `generate_scenarios(root_causes)`, `run_revenue_model(assumptions)`, `run_cost_model(assumptions)`, `run_cashflow_model(assumptions)`, `compute_forecast_accuracy(actuals, prior_forecast)` |
| **Outputs** | List of `Scenario` objects: `{name, description, assumptions, revenue_impact, ebitda_impact, cash_impact, probability_assessment}` + updated `RollingForecast` |
| **Key Design Principle** | LLM decides WHAT to model; deterministic code computes the numbers. This is the critical balance for financial accuracy — never let an LLM do arithmetic [web:38]. |

---

## 6. Data Model

### Financial Data (PostgreSQL)

```
entities
  id, name, currency, fiscal_year_start

gl_accounts
  id, entity_id, account_number, account_name, account_type (revenue/expense/asset/liability/equity)
  department, region, product_line

trial_balance
  id, entity_id, period (YYYY-MM), account_id, debit, credit, balance

budget_lines
  id, entity_id, period, account_id, department, amount, notes

forecast_lines
  id, entity_id, period, account_id, department, amount, version, created_at

actuals
  id, entity_id, period, account_id, department, amount

headcount_data
  id, entity_id, period, department, headcount, total_compensation, new_hires, departures

vendor_invoices
  id, entity_id, period, vendor_name, account_id, amount, category, invoice_date

sales_pipeline
  id, entity_id, period, deal_name, stage, expected_close_date, amount, region, product
```

### Agent State Data (PostgreSQL)

```
agent_runs
  id, pipeline_id, entity_id, period, status (running/paused/completed/failed)
  started_at, completed_at, temporal_workflow_id

agent_state
  id, agent_run_id, agent_name, state_json (LangGraph checkpoint), created_at

variances
  id, agent_run_id, account_id, department, actual_amount, budget_amount,
  variance_amount, variance_pct, is_material, classification, confidence_score

root_causes
  id, variance_id, summary, evidence_json, confidence_score, recommended_action, similar_case_ref

commentary_drafts
  id, agent_run_id, version, content_json, status (draft/reviewed/approved), reviewed_by, reviewed_at

scenarios
  id, agent_run_id, name, description, assumptions_json, revenue_impact,
  ebitda_impact, cash_impact, probability

review_logs
  id, agent_run_id, checkpoint, reviewer, decision (approve/reject/modify), notes, timestamp
```

### Vector Store (Qdrant)

```
Collection: historical_commentary
  Vectors of prior months' commentary sections
  Metadata: period, section_type, entity_id
  Purpose: RAG for commentary tone consistency and trend referencing

Collection: variance_patterns
  Vectors of historical variance explanations
  Metadata: period, account, classification, root_cause
  Purpose: RAG for root-cause agent to find similar past variances

Collection: finance_policies
  Vectors of company accounting policies and recognition rules
  Metadata: policy_name, effective_date, category
  Purpose: RAG for both root-cause and commentary agents
```

---

## 7. Tech Stack

| Layer | Technology | Justification |
|-------|-----------|---------------|
| Agent Orchestration | LangGraph (Python) | Stateful multi-agent workflows, HITL interrupts, conditional routing [web:36] |
| Workflow Durability | Temporal (Python SDK) | Durable execution, resumability, audit trail for finance compliance [web:43][web:44] |
| Backend API | FastAPI (Python) | Async, typed (Pydantic), fast, great for AI workloads |
| Frontend | Next.js (TypeScript) | SSR dashboard, real-time updates via WebSocket |
| Primary Database | PostgreSQL | ACID for financial data, JSON columns for agent state |
| Vector Store | Qdrant | Fast similarity search for RAG over commentary and variance history |
| Cache & Queue | Redis | Job queue, caching, pub/sub for real-time updates |
| Event Streaming | Redpanda | Inter-agent event communication, audit event log |
| LLM Observability | Langfuse | LLM call tracing, agent execution traces, evaluation metrics |
| Containerization | Docker + k3d | Local dev, consistent environments |
| LLM Provider | OpenAI GPT-4o / Anthropic Claude (via LiteLLM) | Best-in-class reasoning for agent tasks; LiteLLM for provider abstraction |

---

## 8. End-to-End Workflow Design

### The Month-End Close Pipeline

**Trigger:** Manual (user clicks "Run Month-End Analysis" in dashboard) or scheduled (Temporal cron trigger on 1st business day of month).

```
Phase 1: Data Ingestion (Deterministic, ~2 min)
  ├── Ingestion Agent pulls actuals, budget, forecast from mock ERP
  ├── Validates completeness (all accounts present, no nulls)
  ├── Reconciles trial balance (debits = credits)
  ├── LLM flags anomalies (unexpected patterns)
  └── Output: Validated ActualsSnapshot + BudgetSnapshot

Phase 2: Variance Detection (Hybrid, ~3 min)
  ├── Compute variances: actual vs budget, actual vs forecast, actual vs prior period
  ├── Apply materiality: > £5k AND > 5% → material flag
  ├── Aggregate by department, account type, region
  ├── LLM classifies each material variance (timing, volume, rate, one-time, etc.)
  └── Output: Materialized Variance list

Phase 2.5: HITL Review Checkpoint 1
  ├── Dashboard shows variance heatmap + classification
  ├── FP&A analyst reviews, can override materiality, dismiss items, add notes
  └── Approved variance list proceeds to Phase 3

Phase 3: Root-Cause Investigation (Agentic, ~5-10 min)
  ├── For each material variance:
  │   ├── Agent reasons about what data to examine
  │   ├── Calls tools: drill_gl_detail, query_headcount, query_vendor_invoices, query_sales_pipeline
  │   ├── RAG: searches historical variance patterns and finance policies
  │   ├── ReAct loop: reason → act → observe → reason → act ...
  │   └── Concludes with root-cause finding + evidence chain + confidence
  └── Output: RootCauseFinding list

Phase 3.5: HITL Review Checkpoint 2
  ├── Dashboard shows root-cause findings with evidence trails
  ├── FP&A analyst validates, adds qualitative context
  └── Approved findings proceed to Phase 4

Phase 4: Commentary + Scenario (Parallel, ~5 min)
  ├── Commentary Agent:
  │   ├── RAG: retrieves prior commentary for tone + trend reference
  │   ├── Generates structured sections (Exec Summary, Revenue, Cost, Cash, Risks, Actions)
  │   ├── Deterministic validation: every cited number traceable to source
  │   └── Output: CommentaryDraft
  │
  └── Scenario Agent (parallel):
      ├── LLM generates relevant what-if scenarios from root causes
      ├── Deterministic Python models compute financial impacts
      ├── LLM explains results and assesses probability
      └── Output: Scenario list + Updated Rolling Forecast

Phase 4.5: HITL Review Checkpoint 3
  ├── Dashboard shows commentary draft + scenario results
  ├── CFO reviews, edits commentary, approves/rejects scenarios
  ├── All edits tracked in version history
  └── Approved commentary + forecast = Final Output

Phase 5: Output & Audit
  ├── Final management pack generated (commentary + variance report + scenario analysis)
  ├── Full audit trail saved (every agent decision, tool call, LLM output, human review)
  └── Pipeline status: COMPLETED
```

### Temporal Workflow Structure

```python
@workflow
class MonthEndFPAPipeline:
    @activity
    async def ingest_data(self, period, entity_id) -> ActualsSnapshot

    @activity
    async def detect_variances(self, actuals, budget) -> list[Variance]

    @activity  # HITL — blocks until human reviews
    async def review_variances(self, variances) -> list[Variance]

    @activity
    async def investigate_root_causes(self, variances) -> list[RootCauseFinding]

    @activity  # HITL
    async def review_root_causes(self, findings) -> list[RootCauseFinding]

    @activity
    async def generate_commentary(self, findings, variances) -> CommentaryDraft

    @activity
    async def run_scenarios(self, findings, actuals) -> list[Scenario]

    @activity  # HITL
    async def review_final_output(self, commentary, scenarios) -> ApprovedOutput

    async def run(self, period, entity_id):
        actuals = await self.ingest_data(period, entity_id)
        variances = await self.detect_variances(actuals, budget)
        reviewed_variances = await self.review_variances(variances)
        findings = await self.investigate_root_causes(reviewed_variances)
        reviewed_findings = await self.review_root_causes(findings)

        # Parallel execution of commentary and scenarios
        commentary, scenarios = await asyncio.gather(
            self.generate_commentary(reviewed_findings, reviewed_variances),
            self.run_scenarios(reviewed_findings, actuals)
        )

        return await self.review_final_output(commentary, scenarios)
```

---

## 9. Human-in-the-Loop Design

### Checkpoint 1: Variance Review

- **Who:** FP&A Analyst
- **What they see:** Variance heatmap (account × department), classification, confidence scores. Can sort/filter by materiality.
- **What they do:** Override materiality flags, dismiss false positives, add context notes ("we expected this variance due to planned campaign launch")
- **Why it matters:** Ensures the agent isn't chasing noise. Analyst's domain knowledge filters the investigation scope.
- **LangGraph mechanism:** `interrupt()` — pipeline pauses, state persisted, resumes when user submits review.

### Checkpoint 2: Root-Cause Validation

- **Who:** FP&A Analyst / Manager
- **What they see:** For each variance: the agent's reasoning trace (tool calls, observations, conclusions), evidence chain, confidence score, similar historical cases.
- **What they do:** Validate findings, correct wrong conclusions, add qualitative context the agent couldn't access ("the sales team had already flagged this deal as at-risk")
- **Why it matters:** The agent's investigation is based on data — human adds the qualitative "why behind the why" that isn't in any system.

### Checkpoint 3: CFO Review

- **Who:** CFO / VP Finance
- **What they see:** Generated commentary draft (formatted as management pack), scenario analysis with financial impacts, updated rolling forecast.
- **What they do:** Edit commentary for tone/accuracy, approve or reject scenarios, approve or override forecast assumptions.
- **Why it matters:** This is the governance layer — nothing goes to the board without human sign-off. All edits are tracked for audit trail.

### Audit Trail

Every decision in the pipeline is logged:
- Agent reasoning traces (Langfuse)
- Tool call inputs/outputs
- LLM prompts and responses
- Human review decisions (approve/reject/modify + notes)
- Version history on all outputs

This audit trail is what makes the system defensible — you can show exactly how every number in the management pack was derived.

---

## 10. Observability & Evaluation

### Langfuse Integration

| Metric | What it Measures |
|--------|-----------------|
| Agent execution trace | Full reasoning chain for each agent — every LLM call, tool call, observation |
| Latency per agent | Time spent in each phase of the pipeline |
| Token usage | LLM token consumption per agent, per run |
| Tool call success rate | Percentage of tool calls that succeed vs fail |
| HITL override rate | How often humans override agent decisions (indicator of agent accuracy) |
| Commentary edit distance | How much the CFO edits the generated commentary (Levenshtein distance as quality proxy) |

### Evaluation Framework

| Eval Dimension | Method |
|----------------|--------|
| Variance detection accuracy | Compare agent-flagged variances against manually computed ground truth |
| Root-cause accuracy | Human-rated: does the root cause explanation match the actual driver? (1-5 scale) |
| Commentary quality | Human-rated: accuracy, completeness, tone, actionability (1-5 scale per dimension) |
| Scenario relevance | Human-rated: are the generated scenarios actually useful for decision-making? |
| Forecast accuracy | MAPE (Mean Absolute Percentage Error) of updated forecast vs subsequent actuals |

---

## 11. MVP Scope (Phase 1)

### In Scope

- Synthetic SaaS company dataset (12 months of GL, budget, forecast, headcount, vendor invoices, sales pipeline data — ~50 GL accounts, 5 departments, 2 regions)
- Full 6-agent pipeline: Ingestion → Variance → Root-Cause → Commentary → Scenario
- LangGraph state graph with 3 HITL checkpoints
- Next.js dashboard: variance heatmap, agent run timeline, commentary editor, scenario viewer
- Langfuse observability (all LLM traces, tool calls)
- FastAPI backend with REST + WebSocket
- Docker Compose for local deployment
- 2-3 demo scenarios with pre-seeded "interesting" variances

### Out of Scope (Phase 1)

- Temporal integration (use LangGraph's built-in checkpointing for v1)
- Redpanda event streaming (use direct function calls for v1)
- Real ERP integration (use mock data)
- Multi-entity consolidation
- User authentication / multi-tenancy
- Production deployment (local Docker only)

---

## 12. Phase 2 Roadmap

| Feature | Priority | Rationale |
|---------|----------|-----------|
| Temporal durable execution | High | Show production-grade resilience for long-running workflows [web:43] |
| Redpanda event streaming | Medium | Event-driven inter-agent communication, audit event log |
| Real ERP mock API | High | Simulate GL feed via a mock server (FastAPI) returning trial balance on demand |
| RAG over historical commentary | Medium | Improves commentary quality with trend references |
| Multi-entity consolidation | Low | Adds complexity without much demo value |
| Deploy to Azure (AKS) | Medium | Show cloud-native deployment capability |
| Evaluation pipeline (automated) | Medium | Automated regression testing of agent outputs |

---

## 13. Demo Scenarios

### Scenario A: Revenue Miss Due to Deal Slippage

**Setup:** EMEA revenue down 12% vs budget in June. Root cause: $2M enterprise deal slipped from June to July. Sales pipeline shows deal still in "Negotiation" stage.

**Agent behavior:**
1. Variance Agent flags EMEA revenue variance as material
2. Root-Cause Agent drills into GL detail → sees Product X revenue down 30% → queries sales pipeline → finds slipped deal → searches historical variances → finds similar pattern in Q2 2025
3. Commentary Agent writes: "EMEA revenue declined 12% vs budget, driven by the slippage of a $2M enterprise deal from June to July. The deal remains in late-stage negotiation and is expected to close in July. Excluding this one-time slippage, EMEA revenue was in line with budget (+1%)."
4. Scenario Agent generates: "If deal closes in July → no full-year impact. If deal slips to Q3 → $2M Q2 revenue gap, $500K EBITDA impact."

### Scenario B: Cost Overrun Due to Vendor Price Increase

**Setup:** Cloud infrastructure costs up 35% vs budget. Root cause: AWS renegotiated pricing after commit tier expired. Headcount unchanged.

**Agent behavior:**
1. Variance Agent flags cloud cost variance
2. Root-Cause Agent queries vendor invoices → sees AWS invoices at new rate → confirms no usage increase (queries cloud cost allocation data) → identifies pricing change as driver
3. Commentary Agent writes: "Cloud infrastructure costs exceeded budget by 35% due to the expiration of our AWS committed-use discount. The new pricing tier took effect in May. We are evaluating a renewed commitment to restore prior pricing."
4. Scenario Agent generates: "If we renew AWS commit → costs normalize in August. If we stay on-demand → $150K/month incremental cost, $1.8M annualized EBITDA impact."

### Scenario C: Clean Month (No Material Variances)

**Setup:** All variances below materiality threshold.

**Agent behavior:**
1. Variance Agent computes variances → none material
2. Orchestrator skips root-cause investigation (conditional edge)
3. Commentary Agent generates: "June results were in line with budget across all major categories. Revenue was within 1% of forecast, and cost variance was driven by minor timing differences in marketing spend. No material concerns identified."
4. Scenario Agent updates forecast with minor adjustments

---

## 14. Differentiation

### What Makes This Different

| Dimension | Existing Tools | FinSight |
|-----------|---------------|---------|
| Workflow depth | Copilot Q&A or single-function automation | End-to-end closed-loop pipeline (variance → root cause → commentary → scenario) |
| Agentic behavior | LLM answers questions | Multi-step reasoning with tool-use, inter-agent communication |
| Determinism balance | Either fully LLM or fully rules | Explicit separation: LLM decides WHAT to investigate/model, deterministic code computes the numbers |
| Human oversight | After-the-fact review | Structured HITL checkpoints at 3 critical decision points |
| Audit trail | Manual or fragmented | Every agent decision, tool call, LLM output, and human review logged |
| Architecture showcase | Black-box AI | Open multi-agent architecture with LangGraph + Temporal, observable via Langfuse |

### Why This Is a Compelling Portfolio Project

1. **Demonstrates vertical domain depth** — shows you understand FP&A workflows, not just AI
2. **Showcases agentic AI done right** — multi-step reasoning, tool-use, RAG, human-in-the-loop, not just "LLM wrapper"
3. **Production-grade architecture** — LangGraph + Temporal + FastAPI + observability with Langfuse
4. **Deterministic vs LLM balance** — the key challenge in production AI systems, explicitly designed into the system [web:38]
5. **Compelling demo narrative** — "watch the AI analyst run your month-end close" is viscerally impressive
6. **Tech stack alignment** — LangGraph, FastAPI, Next.js, Go (for scenario models), PostgreSQL, Qdrant, Temporal, Redpanda — all technologies in your existing toolkit

---

## 15. Synthetic Dataset Design

### Mock SaaS Company: "CloudForge Inc."

| Dimension | Value |
|-----------|-------|
| Industry | B2B SaaS |
| ARR | ~$45M |
| Entity | Single entity (CloudForge Inc.) |
| Departments | Sales, Marketing, Engineering, G&A, Customer Success |
| Regions | North America, EMEA |
| GL Accounts | ~50 (revenue, COGS, OpEx categories) |
| Historical Periods | Jan 2025 – Jun 2026 (18 months) |
| Budget | Annual budget for FY2026 (Jan–Dec 2026) |
| Forecast | Rolling forecast, updated quarterly |
| Headcount | ~280 employees across 5 departments |
| Vendors | ~15 key vendors (AWS, Stripe, Slack, Datadog, etc.) |
| Sales Pipeline | ~40 active deals with stages, amounts, expected close dates |

### Seeded Variances (for Demo)

- June 2026: EMEA revenue -12% (deal slippage — Scenario A)
- June 2026: Cloud costs +35% (vendor pricing change — Scenario B)
- May 2026: Marketing spend +18% (campaign launch — minor variance, below threshold)
- April 2026: Engineering contractor costs +22% (one-time migration project)

---

## 16. Project Structure

```
finsight/
├── backend/
│   ├── agents/
│   │   ├── orchestrator.py        # LangGraph StateGraph definition
│   │   ├── ingestion_agent.py
│   │   ├── variance_agent.py
│   │   ├── root_cause_agent.py
│   │   ├── commentary_agent.py
│   │   └── scenario_agent.py
│   ├── tools/
│   │   ├── gl_tools.py            # GL detail, trial balance queries
│   │   ├── headcount_tools.py     # Headcount data queries
│   │   ├── vendor_tools.py        # Vendor invoice queries
│   │   ├── pipeline_tools.py      # Sales pipeline queries
│   │   └── rag_tools.py           # Qdrant search tools
│   ├── models/
│   │   ├── state.py               # Pydantic models for PipelineState
│   │   ├── financial.py           # Variance, RootCause, Commentary, Scenario models
│   │   └── database.py            # SQLAlchemy models
│   ├── api/
│   │   ├── routes.py              # FastAPI routes
│   │   └── websocket.py           # WebSocket for real-time updates
│   ├── data/
│   │   ├── seed.py                # Synthetic dataset generator
│   │   └── mock_erp.py            # Mock ERP API server
│   └── config.py
├── frontend/
│   ├── app/
│   │   ├── page.tsx               # Dashboard home
│   │   ├── variance/              # Variance heatmap view
│   │   ├── commentary/            # Commentary editor view
│   │   ├── scenario/              # Scenario explorer view
│   │   └── runs/                  # Agent run timeline view
│   └── components/
├── docker-compose.yml
├── Dockerfile.backend
├── Dockerfile.frontend
└── README.md
```
