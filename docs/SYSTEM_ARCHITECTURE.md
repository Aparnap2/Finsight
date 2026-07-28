# System Architecture — FinSight FP&A Intelligence System

> Architecture documentation for the evidence-backed FP&A Intelligence System. Covers system context, container decomposition, component responsibilities, sequence diagrams, data flow, and extension points.

---

## 1. System Context

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Financial Systems                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────────────────┐ │
│  │PostgreSQL│  │   CSV    │  │ Mock ERP │  │ Future: NetSuite, QB,   │ │
│  │  Source  │  │  Upload  │  │ Endpoint │  │ Salesforce, Sheets      │ │
│  └──────────┘  └──────────┘  └──────────┘  └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
         │               │            │                    │
         ▼               ▼            ▼                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           FinSight System                                │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                      FastAPI Backend                              │   │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────────┐ │   │
│  │  │  REST API  │ │ WebSocket  │ │  Pipeline  │ │  Agent Runtime │ │   │
│  │  │  (12 eps)  │ │   Hub      │ │  Engine    │ │  (LangGraph)   │ │   │
│  │  └────────────┘ └────────────┘ └────────────┘ └────────────────┘ │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                    Finance Core (Deterministic)                   │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │   │
│  │  │  Formula │ │Materiality│ │ Calendar │ │  Bridge  │ │  Data  │ │   │
│  │  │  Engine  │ │  Engine   │ │  Engine  │ │ Analysis │ │Quality │ │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └────────┘ │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                       Shared Core                                  │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │   │
│  │  │  Domain  │ │  Policy  │ │ Claim    │ │Evidence  │ │ Tool   │ │   │
│  │  │  Models  │ │  Engine  │ │Validator │ │  Model   │ │Contract│ │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └────────┘ │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
         │               │            │                    │
         ▼               ▼            ▼                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Infrastructure                                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐ │
│  │PostgreSQL│ │  Redis   │ │  Qdrant  │ │ Temporal │ │ Jaeger +      │ │
│  │  (15TB)  │ │  Cache   │ │  Vector   │ │(Phase 2) │ │ Langfuse      │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └───────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

**Actors:**
- **FP&A Analyst** — Reviews variances, provides context, approves findings via API
- **FP&A Manager** — Sets policies, monitors pipeline progress, handles escalations
- **Controller / CFO** — Final approval on published outputs, audit trail review
- **Data/Finance Ops** — Monitors data quality, manages source connections
- **External Systems** — PostgreSQL database, CSV uploads, mock ERP endpoint

---

## 2. Containers

### 2.1 FastAPI Backend Container

**Responsibility:** HTTP API gateway, pipeline orchestration, agent runtime hosting.

**Technology:** Python 3.12, FastAPI, Uvicorn, LangGraph, SQLAlchemy 2.0 (async).

**Key interfaces:**
- REST API on port 8000 (12 endpoints)
- WebSocket hub on `/ws` for real-time agent status
- CSV import via multipart upload

**Dependencies:**
- PostgreSQL (primary data store)
- Redis (cache, job queue)
- LiteLLM (LLM provider abstraction)
- Qdrant (vector store — RAG)

### 2.2 Finance Core Container

**Responsibility:** All deterministic financial calculations.

**Technology:** Pure Python 3.12 — no external runtime dependencies. Zero LLM calls.

**Sub-packages:**

| Sub-package | Responsibility | Key Classes |
|-------------|---------------|-------------|
| `formula_engine/` | Declarative formulas, registry, topological evaluation | `Formula`, `FormulaRegistry`, `FormulaEvaluator`, `DependencyResolver` |
| `variance_engine/` | Variance computation, materiality assessment | `MaterialityEngine`, `MaterialityConfig`, `MaterialityRule`, `SensitivityTier` |
| `validation/` | Fiscal calendar, period lifecycle, data quality | `FiscalCalendar`, `FiscalPeriod`, `PeriodValidator`, `PeriodProgression`, `DataQualityCheck` |
| `driver_engine/` | Bridge variance decomposition | `BridgeDecomposition`, `BridgeType`, `BridgeComponent` |
| `ingestion/` | Data ingestion from sources | `ingestion_node` |
| `assertion_pipeline.py` | Tool results → typed assertions | `AssertionPipelineResult` |

### 2.3 Agent Runtime Container

**Responsibility:** LLM-guided financial analysis and commentary rendering.

**Technology:** LangGraph StateGraph with AsyncPostgresSaver checkpoints.

**Agents:**

| Agent | Responsibility | LLM Type | Read-Only? |
|-------|---------------|----------|------------|
| **Orchestrator** | Conditional routing, state management, HITL checkpoints | Deterministic | N/A |
| **Variance Agent** | Compute actual-vs-budget variances, apply materiality thresholds | Deterministic | N/A |
| **Root-Cause Agent** | Investigate material variances using read-only tools, produce evidence graph | LLM-guided | ✅ |
| **Commentary Agent** | Render narrative from validated assertions (truth/render separation) | LLM-rendering | ✅ |
| **Scenario Agent** | Generate "what-if" scenarios with deterministic financial projection | Hybrid | ✅ |

### 2.4 Shared Core Container

**Responsibility:** Domain models, policy engine, validation, tool contracts.

**Dependency rule:** `shared/` has zero dependencies on `apps/`, `agents/`, or `finance/`.

| Module | Responsibility |
|--------|---------------|
| `shared/models/state.py` | `PipelineState`, `Variance`, `EvidenceItem`, `RootCauseFinding`, `CommentaryDraft`, `Scenario` |
| `shared/models/assertions.py` | `Assertion`, `AssertionType`, `SupportLevel` |
| `shared/models/action.py` | `ActionItem`, `ActionDomain`, `ActionStatus`, `ActionImpact` |
| `shared/models/database.py` | SQLAlchemy ORM models |
| `shared/models/degraded_mode.py` | `DegradedMode` enum (7 values) |
| `shared/utils/policy.py` | `PolicyEngine`, `AutonomyLevel`, `PolicyDecision` |
| `shared/utils/confidence.py` | Deterministic confidence computation |
| `shared/utils/validators/claim_validator.py` | Monetary claim extraction and cross-verification |
| `shared/utils/tools/tool_result.py` | `ToolResult` — standard evidence contract |
| `shared/config/config.py` | Pydantic `Settings` with environment variable loading |

### 2.5 Data Containers

| Container | Technology | Purpose |
|-----------|-----------|---------|
| **Primary Database** | PostgreSQL 16 | Operational state, financial data, agent checkpoints (15 tables) |
| **Cache** | Redis | Session, rate limiting, ephemeral coordination |
| **Vector Store** | Qdrant | Prior commentary, policy docs, historical patterns (RAG) |
| **Workflow Engine** | Temporal (Phase 2) | Durable execution for long-running finance workflows |
| **LLM Proxy** | LiteLLM | Multi-provider routing, rate limiting, fallbacks |
| **Observability** | Jaeger + Langfuse | Distributed tracing, LLM cost breakdown, quality scoring |

---

## 3. Components

### 3.1 API Layer (`apps/api/`)

```
┌────────────────────────────────────────────────────────────────────┐
│                        FastAPI Application                          │
│                                                                    │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  main.py                                                     │  │
│  │  • Lifespan: DB pool init, checkpointer setup               │  │
│  │  • Router mounting (/api/v1, /ws)                           │  │
│  │  • Global connection pool (5-20 connections)                │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  routes.py                                                   │  │
│  │  • GET  /status                   — System status + endpoint │  │
│  │  • GET  /health                   — Health check             │  │
│  │  • POST /pipeline/run             — Trigger pipeline (sync)  │  │
│  │  • POST /pipeline/execute         — Full pipeline (execute)  │  │
│  │  • GET  /pipeline/{id}/status     — Run status               │  │
│  │  • GET  /pipeline/{id}/results    — Run results              │  │
│  │  • POST /pipeline/{id}/review     — HITL review              │  │
│  │  • GET  /commentary/{period}      — Commentary + assertions  │  │
│  │  • GET  /variances/{period}       — Computed variances       │  │
│  │  • GET  /bridge/{period}/{acct}   — Bridge analysis          │  │
│  │  • GET  /data-quality/{period}    — Data quality assessment  │  │
│  │  • GET  /policy/{period}          — Policy decision          │  │
│  │  • GET  /actions                  — List action items        │  │
│  │  • POST /actions                  — Create action (gated)    │  │
│  │  • GET  /actions/{id}             — Get action item          │  │
│  │  • POST /import/csv               — CSV data import          │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  schemas.py — Pydantic request/response models               │  │
│  │  • MoneyDecimal: Decimal-backed type that rejects float      │  │
│  │  • 18 response schemas (VarianceResponse, AssertionResponse, │  │
│  │    CommentaryResponse, PipelineExecuteResponse, etc.)        │  │
│  │  • field_validator on every monetary field to reject float    │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  websocket.py — WebSocket hub for real-time agent status    │  │
│  └─────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

### 3.2 Finance Core (`finance/`)

```
┌────────────────────────────────────────────────────────────────────┐
│  formula_engine/                                                    │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  formula_registry.py                                          │  │
│  │  • Formula: name, description, category, inputs, output_name │  │
│  │  • FormulaRegistry: register, get, list_by_category, names   │  │
│  │  • evaluate(name, inputs) → Decimal                          │  │
│  │  • evaluate_all(inputs) → dict[str, Decimal]                 │  │
│  │  • Topological sort (Kahn's algorithm) for dependency chain  │  │
│  └─────────────────────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  evaluator.py — EvaluationContext, formula execution engine  │  │
│  └─────────────────────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  dependency_resolver.py — Dependency graph construction     │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  variance_engine/                                                  │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  materiality.py                                              │  │
│  │  • SensitivityTier: CRITICAL, HIGH, MEDIUM, LOW              │  │
│  │  • MaterialityRule: pct_threshold, abs_threshold, tier,     │  │
│  │    combined_rule (any/both), account_code/pattern matching  │  │
│  │  • MaterialityConfig: default rules per tier                 │  │
│  │  • MaterialityEngine: assess(variance) → MaterialityResult  │  │
│  │  • TenantMaterialityConfig: per-tenant rule overrides        │  │
│  │  • Default tiers: CRITICAL(3%, $50K), HIGH(5%, $100K),      │  │
│  │    MEDIUM(10%, $250K), LOW(15%, $500K)                      │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  validation/                                                       │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  models.py — FiscalPeriod, PeriodStatus, PeriodType          │  │
│  │  calendar.py — FiscalCalendar                                │  │
│  │  • generate_periods(year, type) → list[FiscalPeriod]        │  │
│  │  • get_period(id), get_period_for_date(date), get_range()   │  │
│  │  • Supports monthly, quarterly, yearly                       │  │
│  │  • Configurable fiscal year start month                      │  │
│  │  • Prior-period and prior-year-period linking               │  │
│  ├─────────────────────────────────────────────────────────────┤  │
│  │  validator.py — PeriodValidationResult, PeriodValidator      │  │
│  │  progression.py — PeriodProgression lifecycle management     │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  driver_engine/                                                    │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  bridge_analysis.py                                          │  │
│  │  • BridgeType: REVENUE, COST                                 │  │
│  │  • BridgeComponent: PRICE, VOLUME, MIX, FX, ONE_TIME,       │  │
│  │    TIMING, SCOPE, RATE                                       │  │
│  │  • decompose_bridge() → BridgeAnalysis with reconciliation   │  │
│  │  • 100% deterministic — no LLM                               │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ingestion/                                                        │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  ingestion_agent.py — PipelineState → actuals + budget      │  │
│  │  • Reads from PostgreSQL database tables                     │  │
│  │  • Returns {"actuals": {...}, "budget": {...}}               │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  assertion_pipeline.py                                             │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  run_assertion_pipeline(variances, tool_results)             │  │
│  │  → AssertionPipelineResult(assertions, rejected,    │  │
│  │    degraded_modes)                                            │  │
│  │  1. Collect tool results                                      │  │
│  │  2. Build typed Assertion objects with evidence               │  │
│  │  3. Validate each assertion by class                          │  │
│  │  4. Compute deterministic confidence                          │  │
│  │  5. Surface only passing assertions to commentary             │  │
│  └─────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

### 3.3 Agent Layer (`agents/`)

```
┌────────────────────────────────────────────────────────────────────┐
│  orchestrator.py — LangGraph StateGraph                            │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  State machine:                                               │  │
│  │  ingestion → variance_detection → root_cause → commentary   │  │
│  │  → review → complete                                         │  │
│  │                                                               │  │
│  │  Routing:                                                     │  │
│  │  • material variances → root_cause                            │  │
│  │  • no material variances → skip root_cause (→ commentary)    │  │
│  │  • critical degraded modes → skip root_cause (→ commentary)  │  │
│  │  • review rejected → remediation (→ scenario)                │  │
│  │                                                               │  │
│  │  Degraded mode handling:                                     │  │
│  │  • LOW_COVERAGE, STALE_SOURCE, INSUFFICIENT_CAUSAL_EVIDENCE  │  │
│  │    → skip root cause investigation                           │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  variance/variance_agent.py                                       │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  • compute_variances(actuals, budget) → list[Variance]         │  │
│  • apply_materiality(variances, threshold) → marked variances  │  │
│  • Uses Decimal arithmetic throughout                          │  │
│  • 100% deterministic — no LLM                                 │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  driver/root_cause_agent.py                                       │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  • investigate_root_causes(material_variances, llm_client)     │  │
│  • → list[RootCauseFinding] with evidence graph                │  │
│  • Read-only tool access to internal data                       │  │
│  • Produces alternative hypotheses + confidence scores          │  │
│  • Notes data gaps explicitly                                   │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  commentary/commentary_agent.py                                   │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  • CommentaryRenderInput: only validated assertions             │  │
│  • render_commentary(input, llm_client) → rendered text        │  │
│  • Truth/render separation — LLM cannot invent numbers         │  │
│  • Explicit prohibitions in prompt: no invented values,        │  │
│    no hypothesis→fact upgrades, no new claims                  │  │
│  • Post-rendering claim validation cross-check                 │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  scenario.py — Scenario agent for "what-if" analysis              │
│                                                                    │
│  forecast/ — Forecast engine agent                                │
│                                                                    │
│  recommendation/ — Recommendation agent                           │
└────────────────────────────────────────────────────────────────────┘
```

### 3.4 Shared Core (`shared/`)

```
┌────────────────────────────────────────────────────────────────────┐
│  models/                                                           │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  state.py — P0 domain models                                │  │
│  │  • PipelineState (TypedDict) — full pipeline state shape     │  │
│  │  • Variance — account_id, amounts (Decimal), is_material     │  │
│  │  • EvidenceItem — source_table, record_id, field, value      │  │
│  │  • RootCauseFinding — variance_id, assertions, evidence,     │  │
│  │    confidence_score, alternative_hypotheses, data_gaps       │  │
│  │  • CommentarySection — section_type, content, cited_data     │  │
│  │  • CommentaryDraft — sections, actions, assertions_used,     │  │
│  │    generated_at, version, status, approval_state             │  │
│  │  • Scenario — name, assumptions, revenue/ebitda/cash impact  │  │
│  ├─────────────────────────────────────────────────────────────┤  │
│  │  assertions.py — Assertion types                             │  │
│  │  • AssertionType: NUMERIC, COMPARATIVE, CAUSAL, HYPOTHESIS, │  │
│  │    ACTION                                                    │  │
│  │  • SupportLevel: VERIFIED, PROBABLE, WEAK, INSUFFICIENT     │  │
│  │  • Assertion: id, type, text, value (Decimal), evidence_ids,│  │
│  │    support_level, confidence, contradictions, source         │  │
│  ├─────────────────────────────────────────────────────────────┤  │
│  │  action.py — Action taxonomy with gate enforcement           │  │
│  │  • ActionDomain: COST, REVENUE, HEADCOUNT, OPERATIONS,      │  │
│  │    COMPLIANCE, STRATEGY                                     │  │
│  │  • 20 approved action/domain pairs                           │  │
│  │  • 5 gates: taxonomy, cause, policy, owner, impact         │  │
│  │  • create_action() → ActionCreationResult(action_item?,     │  │
│  │    created?, errors[], warnings[])                           │  │
│  ├─────────────────────────────────────────────────────────────┤  │
│  │  database.py — SQLAlchemy ORM (15 tables)                   │  │
│  ├─────────────────────────────────────────────────────────────┤  │
│  │  degraded_mode.py — 7 degraded mode enums                   │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  utils/                                                            │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  policy.py — Autonomy policy engine                          │  │
│  │  • AutonomyLevel: FULLY_AUTONOMOUS, ANALYST_IN_THE_LOOP,    │  │
│  │    MANAGER_APPROVAL, CFO_APPROVAL                           │  │
│  │  • PolicyDecision: autonomy_level, routing_target, reasons,  │  │
│  │    requires_review, blocked_actions, confidence              │  │
│  │  • evaluate_policy(assertions, degraded_modes) → decision   │  │
│  │  • evaluate_from_pipeline_result(pipeline_result) → decision │  │
│  ├─────────────────────────────────────────────────────────────┤  │
│  │  confidence.py — Deterministic confidence computation        │  │
│  ├─────────────────────────────────────────────────────────────┤  │
│  │  llm_client.py — LLM client abstraction (LiteLLM)            │  │
│  ├─────────────────────────────────────────────────────────────┤  │
│  │  encoders.py — DecimalEncoder for JSON serialization         │  │
│  ├─────────────────────────────────────────────────────────────┤  │
│  │  tools/ — Standardised tool contracts                       │  │
│  │  • tool_result.py: ToolResult (immutable)                    │  │
│  │  • gl_tools.py, headcount_tools.py, vendor_tools.py,        │  │
│  │    pipeline_tools.py, rag_tools.py                           │  │
│  ├─────────────────────────────────────────────────────────────┤  │
│  │  validators/                                                 │  │
│  │  • claim_validator.py — MonetaryClaim, CausalClaim,         │  │
│  │    ActionClaim validation with evidence cross-check          │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  config/config.py — Pydantic Settings (env/file loaded)           │
│                                                                    │
│  prompts/ — Prompt templates                                      │
│                                                                    │
│  schemas/ — Additional Pydantic schemas                           │
└────────────────────────────────────────────────────────────────────┘
```

---

## 4. Sequence Diagrams

### 4.1 Full Pipeline Execution

```
User                    FastAPI                Finance Core            Agents              Shared Core
 │                        │                        │                    │                     │
 │  POST /pipeline/execute│                        │                    │                     │
 │───────────────────────▶│                        │                    │                     │
 │                        │                        │                    │                     │
 │                        │ 1. ingestion_node()    │                    │                     │
 │                        │──────────────────────▶│                    │                     │
 │                        │  (read actuals+budget) │                    │                     │
 │                        │◀──────────────────────│                    │                     │
 │                        │                        │                    │                     │
 │                        │ 2. variance_node()     │                    │                     │
 │                        │──────────────────────▶│                    │                     │
 │                        │  (compute variances    │                    │                     │
 │                        │   + apply materiality) │                    │                     │
 │                        │◀──────────────────────│                    │                     │
 │                        │                        │                    │                     │
 │                        │ 3. root cause (LLM)    │                    │                     │
 │                        │───────────────────────────────────────────▶│                     │
 │                        │  (material variances   │                    │                     │
 │                        │   → findings+evidence) │                    │                     │
 │                        │◀───────────────────────────────────────────│                     │
 │                        │                        │                    │                     │
 │                        │ 4. assertion pipeline  │                    │                     │
 │                        │────────────────────────────────────────────────────────────────▶│
 │                        │  (variances→assertions)│                    │                     │
 │                        │◀────────────────────────────────────────────────────────────────│
 │                        │                        │                    │                     │
 │                        │ 5. data quality check  │                    │                     │
 │                        │──────────────────────▶│                    │                     │
 │                        │◀──────────────────────│                    │                     │
 │                        │                        │                    │                     │
 │                        │ 6. policy evaluation   │                    │                     │
 │                        │────────────────────────────────────────────────────────────────▶│
 │                        │◀────────────────────────────────────────────────────────────────│
 │                        │                        │                    │                     │
 │                        │ 7. render commentary   │                    │                     │
 │                        │ (CommentaryRenderInput) │───────────────────▶│                     │
 │                        │                        │                    │  (LLM rendering      │
 │                        │                        │                    │   from assertions)   │
 │                        │                        │◀───────────────────│                     │
 │                        │                        │                    │                     │
 │  ◀────────────────────│                        │                    │                     │
 │  { assertions[],       │                        │                    │                     │
 │    commentary[],       │                        │                    │                     │
 │    policy_decision,    │                        │                    │                     │
 │    data_quality }      │                        │                    │                     │
```

### 4.2 Truth/Render Separation

```
                 Assertion Pipeline                Commentary Agent
                        │                               │
   ┌────────────────────┼───────────────────────────────┘
   │                    │                               
   ▼                    │                               
 ┌──────────────┐       │                               
 │  Validation   │       │                               
 │  & Scoring    │       │                               
 └──────┬───────┘       │                               
        │               │                               
        ▼               │                               
 ┌──────────────┐       │                               
 │  Assertions   │       │                               
 │  typed+scored  │──────│───▶ CommentaryRenderInput    
 └──────────────┘       │     ┌─────────────────────┐  
                        │     │ verified_assertions  │  
                        │     │ probable_assertions  │  
                        │     │ weak_assertions      │  
                        │     │ degraded_modes       │  
                        │     │ required_sections    │  
                        │     │ audience, period     │  
                        │     └─────────────────────┘  
                        │               │              
                        │               ▼              
                        │     ┌─────────────────────┐  
                        │     │   LLM Rendering      │  
                        │     │  (restricted to      │  
                        │     │   arrange, paraphrase,│  
                        │     │   group — no invent) │  
                        │     └─────────────────────┘  
                        │               │              
                        │               ▼              
                        │     ┌─────────────────────┐  
                        │     │ Commentary Sections   │  
                        │     │ + Claim Validator     │  
                        │     │ (cross-check every    │  
                        │     │  $ figure vs evidence)│  
                        │     └─────────────────────┘  
```

### 4.3 Data Quality Gate

```
  Ingestion              Data Quality Engine              Orchestrator
      │                         │                             │
      │  tool_results[]         │                             │
      │────────────────────────▶│                             │
      │                         │                             │
      │  6 deterministic checks:│                             │
      │  • coverage_pct < 0.5?  │                             │
      │  • freshness > 90d?     │                             │
      │  • row_count == 0?      │                             │
      │  • source_diversity < 2?│                             │
      │  • filters present?     │                             │
      │  • quality_score < 0.5? │                             │
      │                         │                             │
      │  DataQualityReport      │                             │
      │◀────────────────────────│                             │
      │                         │                             │
      │  result.passed?         │                             │
      │  ── yes: continue       │                             │
      │  ── no:  degraded_modes │                             │
      │         propagate through pipeline                    │
      │                         │                             │
```

---

## 5. Data Flow

### 5.1 Pipeline Data Flow

```
Source Data                        Finance Core                        Agents
───────────                        ────────────                       ──────

PostgreSQL DB ──▶ Ingestion ──▶ Variance
  Actuals table     Agent         Computation         Root Cause
  Budget table        │              │                Investigation
  (15 tables)        │              │                     │
                     │              │                     │
                     ▼              ▼                     ▼
                Raw Ledger     Variance[] +           RootCauseFinding[]
                Data           Materiality[]          EvidenceItem[]

                        │                             │
                        ▼                             ▼
                  Assertion Pipeline ──────────▶ Commentary Agent
                  ┌────────────────┐             ┌─────────────────┐
                  │ ToolResult[]   │             │RenderInput      │
                  │ VarianceDict[]  │             │(assertions only)│
                  │                │             │                 │
                  │ ↓ validate     │             │ ↓ LLM render    │
                  │ ↓ confidence   │             │ ↓ claim verify  │
                  │ ↓ filter       │             │                 │
                  │                │             │ CommentarySection│
                  │ Assertion[]    │             │ (narrative)     │
                  └────────────────┘             └─────────────────┘
                        │                             │
                        └──────────┬──────────────────┘
                                   │
                                   ▼
                            Policy Engine
                            ┌─────────────────────┐
                            │ Assertions + degraded│
                            │ → AutonomyLevel      │
                            │ → routing_target     │
                            │ → requires_review    │
                            └─────────────────────┘
                                   │
                                   ▼
                            API Response
                            ┌─────────────────────┐
                            │ assertions (truth)   │
                            │ commentary (render)  │
                            │ data_quality         │
                            │ routing_decision     │
                            │ degraded_modes       │
                            └─────────────────────┘
```

### 5.2 Money Type Flow

```
External (JSON)         API Boundary             Engine              Storage
─────────────────       ──────────────           ──────              ───────

"amount": "484464"      MoneyDecimal             Decimal             Numeric
  │                     (rejects float)          (exact math)        (DB)
  │                           │                       │                 │
  ├── str/Decimal ──────────▶ ✅ ──────────────────▶ Decimal ────────▶ NUMERIC
  ├── int ────────────────── ▶ ✅ ──────────────────▶ Decimal ────────▶ NUMERIC
  └── float ──────────────── ▶ ❌ ValidationError    (never)           (never)
                              "Float values not
                               allowed for monetary
                               fields"
```

---

## 6. Dependency Rules

### 6.1 Layer Architecture

```
apps/  (depends on finance/, agents/, shared/)
  │
  ├── apps/api/routes.py ──▶ finance/ingestion/ingestion_agent.py
  │                       ──▶ finance/assertion_pipeline.py
  │                       ──▶ finance/validation/data_quality.py
  │                       ──▶ finance/driver_engine/bridge_analysis.py
  │                       ──▶ agents/variance/variance_agent.py
  │                       ──▶ agents/commentary/commentary_agent.py
  │                       ──▶ agents/driver/root_cause_agent.py
  │                       ──▶ shared/models/state.py
  │                       ──▶ shared/utils/policy.py
  │                       ──▶ shared/utils/llm_client.py
  │                       ──▶ shared/utils/tools/tool_result.py
  │                       ──▶ shared/config/config.py
  │
  ├── apps/api/schemas.py ──▶ (standard library: decimal, pydantic)
  │
  └── apps/api/main.py    ──▶ shared/config/config.py

agents/  (depends on shared/, finance/ read-only)
  │
  ├── agents/orchestrator.py ──▶ shared/models/state.py
  │                           ──▶ shared/models/degraded_mode.py
  │
  ├── agents/variance/ ────────▶ shared/models/state.py
  │                             (pure deterministic, no shared/)
  │
  ├── agents/commentary/ ──────▶ shared/models/*.py
  │                           ──▶ shared/utils/llm_client.py
  │
  └── agents/driver/ ─────────▶ shared/models/*.py
                             ──▶ shared/utils/llm_client.py

finance/  (depends on shared/ only)
  │
  ├── finance/formula_engine/ ──▶ (pure Python, no dependencies)
  ├── finance/variance_engine/ ─▶ shared/models/state.py (Variance)
  ├── finance/validation/ ──────▶ (pure Python, no dependencies)
  ├── finance/driver_engine/ ───▶ (pure Python, no dependencies)
  ├── finance/ingestion/ ───────▶ shared/config/config.py
  └── finance/assertion_pipeline.py ──▶ shared/models/*.py
                                      ──▶ shared/utils/*.py

shared/  (no dependents on apps/, agents/, or finance/)
  │
  ├── shared/models/     ──▶ pydantic, decimal, enum
  ├── shared/config/     ──▶ pydantic-settings
  ├── shared/utils/      ──▶ shared/models (protocol-level only)
  └── shared/schemas/    ──▶ pydantic
```

### 6.2 Enforced Constraints

1. **`shared/` must never import from `apps/`, `agents/`, or `finance/`**
2. **`finance/` should never import from `agents/` or `apps/`**
3. **`agents/` may read from `finance/` only through tool result contracts — never direct engine calls**
4. **`apps/` is the only layer that wires everything together**
5. **No circular imports between layers**
6. **All monetary values crossing layer boundaries must be `Decimal` or `MoneyDecimal`**

---

## 7. Module Responsibilities

| Module | Responsibility | Deterministic? | LLM? | Tests |
|--------|---------------|----------------|------|-------|
| `finance.formula_engine` | Declarative formula definitions, registry, topological evaluation | ✅ 100% | ❌ | 1 file, ~449 lines |
| `finance.variance_engine` | Tiered materiality assessment with configurable thresholds | ✅ 100% | ❌ | 1 file, ~523 lines |
| `finance.validation.models` | Domain models: FiscalPeriod, PeriodStatus, PeriodType | ✅ 100% | ❌ | — |
| `finance.validation.calendar` | Period generation, lookup, navigation | ✅ 100% | ❌ | 1 file, ~349 lines |
| `finance.validation.data_quality` | 6 deterministic data quality checks, degraded mode production | ✅ 100% | ❌ | 1 file |
| `finance.driver_engine` | Variance bridge decomposition (price/volume/mix, timing/scope) | ✅ 100% | ❌ | 1 file |
| `finance.ingestion` | Data ingestion from database sources | ✅ 100% | ❌ | 1 file |
| `finance.assertion_pipeline` | Tool results → typed, validated, confidence-scored assertions | ✅ 100% | ❌ | 1 file |
| `finance.kpi_engine` | KPI computation | TBD | ❌ | — |
| `finance.scenario_engine` | Scenario modelling | TBD | TBD | — |
| `finance.forecast_engine` | Forecast computation | TBD | TBD | — |
| `finance.reporting` | Report generation | TBD | TBD | — |
| `agents.orchestrator` | LangGraph StateGraph, conditional routing, HITL checkpoints | ✅ Routing | ❌ | 1 file |
| `agents.variance` | Variance detection node | ✅ 100% | ❌ | 1 file |
| `agents.driver` | Root-cause investigation, evidence graph construction | ❌ Logic | ✅ Guided | 3 files |
| `agents.commentary` | Commentary rendering from validated assertions | ❌ | ✅ Render only | 2 files |
| `agents.scenario` | "What-if" scenario generation | ❌ | ✅ Hybrid | 1 file |
| `apps.api` | REST API, WebSocket hub, request/response schemas | ✅ | Via agents | 2 files |
| `shared.models.state` | PipelineState, Variance, EvidenceItem, RootCauseFinding, Commentary models | ✅ | ❌ | — |
| `shared.models.assertions` | Assertion types and support levels | ✅ | ❌ | 1 file |
| `shared.models.action` | Action taxonomy, gate enforcement, creation | ✅ | ❌ | 1 file |
| `shared.models.database` | SQLAlchemy ORM (15 tables) | ✅ | ❌ | 1 file |
| `shared.models.degraded_mode` | 7 degraded mode enum values | ✅ | ❌ | — |
| `shared.utils.policy` | Autonomy policy matrix, routing decisions | ✅ | ❌ | 1 file |
| `shared.utils.confidence` | Deterministic confidence scoring | ✅ | ❌ | 1 file |
| `shared.utils.llm_client` | LiteLLM client abstraction | ❌ | Proxy | — |
| `shared.utils.validators` | Claim validator (hallucination detection) | ✅ | ❌ | 1 file |
| `shared.utils.tools` | ToolResult contract and evidence-gathering tools | ✅ | ❌ | 1 file |

---

## 8. Extension Points

### 8.1 Formula Engine — Adding New KPIs

```python
from finance.formula_engine.formula_registry import Formula, FormulaRegistry
from decimal import Decimal

def _working_capital_ratio(
    current_assets: Decimal, current_liabilities: Decimal
) -> Decimal:
    return current_assets / current_liabilities

registry = FormulaRegistry()
registry.register(Formula(
    name="working_capital_ratio",
    description="Current assets / current liabilities",
    category="ratio",
    inputs=["current_assets", "current_liabilities"],
    output_name="working_capital_ratio",
    fn=_working_capital_ratio,
))
```

### 8.2 Materiality Engine — Custom Rules

```python
from finance.variance_engine.materiality import (
    MaterialityRule, SensitivityTier, MaterialityConfig, MaterialityEngine
)
from decimal import Decimal

config = MaterialityConfig(
    rules=[
        MaterialityRule(
            account_code="4010",  # Override for specific account
            tier=SensitivityTier.CRITICAL,
            pct_threshold=Decimal("0.02"),  # 2% instead of default 3%
            abs_threshold=Decimal("25000"),  # $25K instead of $50K
            combined_rule="both",
        ),
    ]
)
engine = MaterialityEngine(config=config)
```

### 8.3 Assertion Pipeline — New Assertion Types

```python
from shared.models.assertions import Assertion, AssertionType, SupportLevel
from finance.assertion_pipeline import AssertionPipelineResult

# Add assertion type to AssertionType enum
# Implement validator in shared/utils/validators/claim_validator.py
# Register in assertion_pipeline validation dispatch
```

### 8.4 Policy Engine — New Autonomy Rules

```python
from shared.utils.policy import AutonomyLevel, PolicyDecision

# Extend evaluate_policy() in shared/utils/policy.py
# New rules based on assertion types, confidence thresholds, degraded modes
```

### 8.5 Agent Layer — New Agents

```python
# 1. Create agent module in agents/<name>/
# 2. Implement node function: (PipelineState) → dict
# 3. Register node in agents/orchestrator.py
# 4. Add routing in orchestrator routing functions
# 5. Add endpoint in apps/api/routes.py if new API surface needed
```

### 8.6 Data Sources — New Connectors

```python
# 1. Add tool function in shared/utils/tools/
# 2. Tool must return ToolResult (standard contract)
# 3. Tool result feeds into assertion pipeline automatically
# 4. Add data quality checks if new quality dimensions needed
```

---

## 9. Configuration

### 9.1 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_URI` | `postgresql://finsight:finsight@localhost:5432/finsight` | Database connection string |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant vector store URL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `LITELLM_PROXY_URL` | `None` | LiteLLM proxy URL |
| `DEFAULT_LLM_MODEL` | `gpt-4o` | Default LLM model |
| `LANGFUSE_*` | — | Langfuse observability config |
| `APP_ENV` | `development` | Application environment |
| `LOG_LEVEL` | `INFO` | Logging level |

### 9.2 Docker Compose Services

| Service | Port | Memory Limit |
|---------|------|-------------|
| PostgreSQL | 5432 | 512MB |
| Redis | 6380 | 256MB |
| Qdrant | 6333 | 512MB |
| Temporal | 7233 | 512MB |
| Jaeger | 16686 | 512MB |
| FastAPI Backend | 8000 | 512MB |
| **Total** | | **2.8GB** |

---

## 10. Testing Architecture

| Test Layer | Location | Focus | Framework |
|------------|----------|-------|-----------|
| **Unit** — Deterministic Finance | `tests/unit/test_finance/` | Formula engine, calendar, materiality — 100% oracle match | pytest |
| **Unit** — Decimal Layer | `tests/unit/api/` | Float rejection, Decimal serialization | pytest |
| **Integration** — API | `tests/backend/api/` | Endpoints, schema validation | pytest + httpx |
| **Integration** — Agents | `tests/backend/agents/` | Pipeline nodes, state transitions | pytest |
| **Integration** — Engine | `tests/backend/engine/` | Assertion pipeline, policy, bridge, data quality | pytest |
| **Integration** — Models | `tests/backend/models/` | Domain models, tenant isolation | pytest + SQLAlchemy |
| **Integration** — Validators | `tests/backend/validators/` | Claim validator | pytest |
| **Agentic** — Hallucination | `tests/backend/agents/test_agentic_*.py` | LLM safety, formatting, tool calls, type safety | pytest + real LLM |
| **E2E** | `tests/e2e/` | Full pipeline scenarios | pytest |
