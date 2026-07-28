# FinSight — Evidence-backed FP&A Intelligence System

> A deterministic-by-construction financial intelligence platform that ingests source data, validates it, computes KPIs and variances, generates evidence-grounded assertions, renders AI commentary under strict guardrails, and routes findings through governed approval workflows — all without floating-point money or hallucinated numbers.

---

## Problem

FP&A teams spend 60–70% of each close cycle on mechanical work: importing actuals, reconciling sources, scanning spreadsheets for variances, chasing owners for explanations, writing repetitive commentary, and formatting board packs. This manual churn leaves minimal time for strategic analysis, scenario modelling, and decision support.

Existing AI tools in this space are copilots — they generate text when prompted but do not own the workflow, enforce data quality, validate claims against evidence, or guard against hallucinated financial figures. They produce drafts, not auditable outcomes.

## Solution

FinSight is an **evidence-backed FP&A intelligence system** that owns the variance-to-action loop within explicit boundaries:

1. **Ingest** source data from databases, CSVs, and ERP snapshots
2. **Validate** data quality with deterministic checks (coverage, freshness, diversity, schema)
3. **Compute** KPIs and variances using a declarative formula engine — no float, no LLM
4. **Assess** materiality with tiered sensitivity thresholds (CRITICAL / HIGH / MEDIUM / LOW)
5. **Generate assertions** — typed, evidence-linked, confidence-scored claims
6. **Render commentary** — the LLM receives only validated assertions and may not invent numbers
7. **Enforce policy** — autonomy decisions based on confidence, degraded modes, and assertion types
8. **Propose actions** — taxonomy-backed, gate-enforced action items with impact quantification

Every monetary value is `decimal.Decimal`. Every claim is evidence-backed. Every autonomy decision is policy-bound.

## Core Principles

| Principle | Meaning |
|-----------|---------|
| **Deterministic > LLM** | All financial calculations — variances, materiality, bridge decomposition, KPIs — are pure deterministic Python. LLMs never compute numbers. |
| **Evidence > Opinions** | Every assertion must cite specific evidence records. Unsupported claims are rejected by the claim validator before they reach commentary. |
| **Typed > Untyped** | All monetary values use `decimal.Decimal` (never `float`). API schemas reject floats with clear error messages. Assertions are typed (numeric, comparative, causal, hypothesis, action). |
| **Validation > Blind Trust** | LLM output is always validated: claim validator cross-checks every `$` figure against evidence; data quality checks run before any analysis; policy engine gates every action. |

## Architecture

```
                          ┌────────────────────┐
                          │   FastAPI Backend    │
                          │  (Python 3.12)       │
                          └──────────┬─────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              │                      │                      │
              ▼                      ▼                      ▼
   ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
   │   Finance Core    │   │   Agents         │   │   Shared Core    │
   │  (Deterministic)  │   │  (LLM-guided)    │   │  (Models+Utils)  │
   │                   │   │                  │   │                  │
   │ • Formula Engine  │   │ • Orchestrator   │   │ • Pydantic       │
   │ • Materiality     │   │ • Commentary     │   │   Assertions     │
   │ • Calendar        │   │ • Root Cause     │   │ • Policy Engine  │
   │ • Bridge Analysis │   │ • Scenario       │   │ • Claim Valid.   │
   │ • Data Quality    │   │ • Variance       │   │ • Evidence Model │
   └──────────────────┘   └──────────────────┘   └──────────────────┘
                                     │
                                     ▼
                          ┌────────────────────┐
                          │   PostgreSQL DB     │
                          │   (15 tables)       │
                          └────────────────────┘
```

### Dependency Rules

```
apps/ → agents/ → shared/
apps/ → finance/ → shared/
agents/ → finance/  (read-only, via tool results)
shared/ has no dependents on apps/, agents/, or finance/
```

## Features

| Feature | Status | Description |
|---------|--------|-------------|
| **Formula Engine** | ✅ | Declarative Formula + FormulaRegistry with topological dependency resolution |
| **Materiality Engine** | ✅ | Tiered sensitivity model (CRITICAL / HIGH / MEDIUM / LOW) with configurable thresholds |
| **Fiscal Calendar** | ✅ | Period generation, lookup, navigation (monthly / quarterly / yearly) |
| **Decimal Money Layer** | ✅ | `MoneyDecimal` type rejects floats at API boundary; all engine values are `Decimal` |
| **Bridge Analysis** | ✅ | Deterministic variance decomposition into price/volume/mix/one-time/timing/scope |
| **Data Quality Engine** | ✅ | 6 deterministic checks: coverage, freshness, row count, source diversity, filters, quality score |
| **Assertion Pipeline** | ✅ | Transforms tool results into typed, validated, confidence-scored assertions |
| **Policy Engine** | ✅ | Autonomy-level matrix: FULLY_AUTONOMOUS → ANALYST → MANAGER → CFO approval |
| **Action Framework** | ✅ | Taxonomy-backed action creation with gate enforcement (5 gates) |
| **Claim Validator** | ✅ | Extracts and cross-verifies all monetary claims against evidence |
| **LangGraph Orchestrator** | ✅ | StateGraph with conditional routing, degraded-mode handling, HITL checkpoints |
| **Commentary Agent** | ✅ | Truth/render separation: LLM receives only validated assertions |
| **Root-Cause Agent** | ✅ | LLM investigation with read-only tool access, evidence graph |
| **API** | ✅ | 12 endpoints covering pipeline, commentary, variances, bridge, data quality, policy, actions |
| **LLM Integration** | ✅ | LiteLLM proxy with multi-provider routing and fallbacks |
| **Seeded Dataset** | ✅ | CloudForge Inc. — 18 GL accounts, 18 months, 2 material variances |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend Framework | FastAPI (Python 3.12) |
| Agent Orchestration | LangGraph (StateGraph + AsyncPostgresSaver) |
| LLM Proxy | LiteLLM (multi-provider routing) |
| LLM Providers | OpenRouter / OpenAI / Anthropic via LiteLLM |
| Database | PostgreSQL 16 (asyncpg + psycopg) |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Vector Store | Qdrant + LangChain integration |
| Cache | Redis |
| Workflow Engine | Temporal (Phase 2) |
| Event Streaming | Redpanda (Phase 2) |
| Observability | Langfuse, Jaeger |
| Validation | Pydantic v2, mypy strict, ruff |
| Containerization | Docker Compose |
| Testing | pytest, pytest-asyncio, pytest-cov |

## Project Structure

```
finsight/
├── apps/
│   └── api/                    # FastAPI application layer
│       ├── main.py             # App entrypoint, lifespan, checkpointer setup
│       ├── routes.py           # 12 REST endpoints
│       ├── schemas.py          # Pydantic models with MoneyDecimal
│       ├── serializers.py      # Amount serialization helpers
│       └── websocket.py        # WebSocket hub for real-time agent status
├── finance/                    # Deterministic financial core (no LLM)
│   ├── formula_engine/         # Formula definitions, registry, dependency resolution
│   │   ├── formula_registry.py # Formula + FormulaRegistry classes
│   │   ├── dependency_resolver.py
│   │   └── evaluator.py
│   ├── variance_engine/        # Variance computation and materiality assessment
│   │   └── materiality.py      # MaterialityEngine with tiered sensitivity
│   ├── validation/             # Data quality, calendar, period models
│   │   ├── models.py           # FiscalPeriod, PeriodStatus, PeriodType
│   │   ├── calendar.py         # FiscalCalendar — period generation & navigation
│   │   ├── validator.py        # PeriodValidator
│   │   ├── progression.py      # PeriodProgression lifecycle
│   │   └── data_quality.py     # 6 deterministic data quality checks
│   ├── driver_engine/          # Bridge analysis (variance decomposition)
│   │   └── bridge_analysis.py  # Deterministic price/volume/mix decomposition
│   ├── ingestion/              # Data ingestion from database sources
│   ├── assertion_pipeline.py   # Transforms tool results → assertions
│   ├── kpi_engine/
│   ├── scenario_engine/
│   ├── forecast_engine/
│   └── reporting/
├── agents/                     # LangGraph agent nodes (LLM-guided)
│   ├── orchestrator.py         # StateGraph with conditional routing
│   ├── variance/               # Variance detection node (deterministic)
│   ├── commentary/             # Commentary renderer (truth/render separation)
│   ├── driver/                 # Root-cause investigation node
│   ├── scenario.py
│   ├── forecast/
│   └── recommendation/
├── shared/                     # Shared core — no dependents on apps/ or finance/
│   ├── models/                 # Pydantic domain models
│   │   ├── state.py            # PipelineState, Variance, EvidenceItem, etc.
│   │   ├── assertions.py       # Assertion, AssertionType, SupportLevel
│   │   ├── action.py           # ActionItem, ActionDomain, ActionStatus
│   │   ├── database.py         # SQLAlchemy ORM models
│   │   └── degraded_mode.py    # 7 degraded mode enum values
│   ├── config/                 # Pydantic Settings
│   ├── utils/                  # Policy engine, confidence, encoders, seed
│   │   ├── policy.py           # Autonomy policy matrix
│   │   ├── confidence.py       # Deterministic confidence computation
│   │   ├── llm_client.py       # LLM client abstraction
│   │   ├── encoders.py         # DecimalEncoder for JSON serialization
│   │   ├── tools/              # Tool contracts (ToolResult, GL, headcount, RAG)
│   │   └── validators/         # Claim validator (hallucination detection)
│   ├── schemas/
│   └── prompts/
├── tests/
│   ├── unit/                   # Unit tests (formula engine, calendar, materiality, decimal layer)
│   │   ├── api/
│   │   └── test_finance/
│   ├── backend/                # Integration tests
│   │   ├── api/
│   │   ├── agents/
│   │   ├── engine/
│   │   ├── models/
│   │   ├── validators/
│   │   ├── tools/
│   │   └── data/
│   ├── e2e/
│   └── integration/
├── docs/                       # Documentation
├── alembic/                    # Database migrations
├── docker-compose.yml
├── Dockerfile.backend
├── pyproject.toml
└── litellm-config.yaml
```

## Quick Start

### Prerequisites

- Python 3.12+
- Docker & Docker Compose
- `uv` (Python package manager)

### 1. Start Infrastructure

```bash
docker compose up -d
```

Services: PostgreSQL (`:5432`), Redis (`:6380`), Qdrant (`:6333`), Temporal (`:7233`), Jaeger (`:16686`).

### 2. Setup Backend

```bash
uv sync
cp .env.example .env    # Edit with your LLM API keys
alembic upgrade head
```

### 3. Run Tests

```bash
uv run pytest tests/ -v
```

### 4. Start API Server

```bash
uv run uvicorn apps.api.main:app --reload
```

### 5. Run Pipeline

```bash
curl -X POST http://localhost:8000/api/v1/pipeline/execute \
  -H "Content-Type: application/json" \
  -d '{"period": "2026-06", "tenant_id": "CF001"}'
```

## Examples

### Detect Material Variances

```python
from finance.variance_engine.materiality import MaterialityEngine, SensitivityTier

engine = MaterialityEngine()
assessment = engine.assess(
    account_id="4010",     # Consulting Revenue (CRITICAL tier)
    actual=Decimal("426328"),
    budget=Decimal("484464"),
)
# assessment.is_material → True (12% variance on CRITICAL account)
```

### Evaluate a Financial Formula

```python
from finance.formula_engine.formula_registry import FormulaRegistry
from decimal import Decimal

registry = FormulaRegistry()
result = registry.evaluate("gross_margin", {
    "revenue": Decimal("1000000"),
    "cogs": Decimal("600000"),
})
# result → Decimal("0.40")
```

### Create an Action Item with Gate Enforcement

```python
from shared.models.action import ActionDomain, create_action

result = create_action(
    action="reduce",
    domain=ActionDomain.COST,
    target="Cloud Infrastructure",
    description="Reduce cloud spend by negotiating reserved instances",
    cited_assertion_ids=["ast-001"],
    owner="user@example.com",
)
# result.created → True (passes all 5 gates)
# result.action_item.status → ActionStatus.PROPOSED
```

## Evaluation

| Metric | Target |
|--------|--------|
| Unit test count (deterministic core) | 83+ tests across formula engine, materiality, calendar, decimal layer |
| Float rejection | 100% — all monetary fields use `MoneyDecimal` |
| Claim validation | Every monetary claim cross-checked against evidence |
| Time to close | < 4 hours (variance to pack) |
| Human override rate | < 15% |
| System availability | > 99.5% during close windows |

## Limitations

- **LLM commentary is read-only rendering** — the LLM receives pre-validated assertions and may only arrange, paraphrase, and group them. It cannot invent figures.
- **No autonomous system-of-record writes** — FinSight never posts to GL/ERP, changes budgets, or approves payments. All actions are proposed, not executed.
- **Single-tenant today** — multi-tenant isolation (RLS) is designed but not production-deployed.
- **Temporal workflow engine** is ready but not wired into the active pipeline.
- **Real ERP connectors** (NetSuite, QuickBooks) are planned but not yet implemented.

## Future Work

- Domain Models & Graph — full financial domain graph with account relationships
- Sheets / CSV Adapter — spreadsheet ingestion with schema inference
- Context Builder — structured context packaging for LLM queries
- Evidence Engine — automated evidence gathering across tool surfaces
- Prompt Harness — version-controlled prompt templates with eval
- LLM Guardrails — output validation, prompt injection detection
- Validation Harness — comprehensive eval suite for agent trajectories
- Board Reporting — PDF/HTML management pack generation
- Temporal Durable Workflows — crash-resilient period-run orchestration

## License

MIT
