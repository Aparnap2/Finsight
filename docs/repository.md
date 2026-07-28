# Repository Structure

## Top-Level Directories

```
finsight/
├── apps/            # FastAPI web layer
├── agents/          # AI orchestration (LangGraph)
├── finance/         # Finance domain logic & engines
├── shared/          # Cross-cutting utilities & models
├── tests/           # Test suite (mirrors source structure)
├── docs/            # Project documentation
├── alembic/         # Database migration scripts
└── scripts/         # Development utilities
```

## `apps/` — API Layer

The FastAPI-based web layer. Owns HTTP routing, WebSocket connections, request/response serialization, and API schema definitions.

```
apps/
├── __init__.py
└── api/
    ├── __init__.py
    ├── main.py           # FastAPI app factory
    ├── routes.py         # REST endpoints (/api/v1/*)
    ├── schemas.py        # Pydantic request/response schemas with MoneyDecimal
    ├── serializers.py    # Decimal-to-string serialization helpers
    ├── websocket.py      # Real-time WebSocket handler
    └── frontend/         # Frontend application (if applicable)
```

**Rules:**
- No business logic in routes — routes only parse requests, delegate to engines, return responses.
- All monetary fields use `MoneyDecimal` (rejects floats via `BeforeValidator`).

## `agents/` — AI Orchestration

LangGraph-based agent orchestration layer. Each agent node is a focused, single-responsibility LangGraph node.

```
agents/
├── __init__.py
├── orchestrator.py       # Pipeline state machine
├── scenario.py           # Scenario analysis agent
├── commentary/           # Executive commentary generation
│   ├── __init__.py
│   └── commentary_agent.py
├── driver/               # Root cause / driver investigation
│   ├── __init__.py
│   └── root_cause_agent.py
├── forecast/             # Forecast commentary
│   └── __init__.py
├── recommendation/       # Recommendation generation
│   └── __init__.py
└── variance/             # Variance explanation
    ├── __init__.py
    └── variance_agent.py
```

**Rules:**
- Agents never perform calculations — they receive pre-computed values from finance engines.
- Agents only explain, summarize, hypothesize, or recommend.
- All agent I/O is typed Pydantic models.

## `finance/` — Domain Logic

The heart of the system. All deterministic finance logic lives here. No web concerns, no AI prompts.

```
finance/
├── __init__.py
├── assertion_pipeline.py    # Truth-layer assertion pipeline
├── domain/                  # DDD-inspired finance domain models
│   ├── __init__.py
│   ├── company.py
│   ├── fiscal_calendar.py
│   ├── chart_of_accounts.py
│   ├── account.py
│   ├── department.py
│   ├── cost_center.py
│   ├── budget.py
│   ├── actual.py
│   ├── forecast.py
│   ├── transaction.py
│   ├── kpi.py
│   ├── variance.py
│   ├── driver.py
│   ├── evidence.py
│   ├── recommendation.py
│   └── board_report.py
├── formula_engine/          # KPI formula registry & evaluator
│   ├── __init__.py
│   ├── formula_registry.py
│   ├── dependency_resolver.py
│   └── evaluator.py
├── variance_engine/         # Variance calculation & materiality
│   ├── __init__.py
│   └── materiality.py
├── driver_engine/           # Bridge analysis (price/volume/mix)
│   ├── __init__.py
│   └── bridge_analysis.py
├── kpi_engine/              # KPI calculation engine
│   └── __init__.py
├── forecast_engine/         # Forecast calculation engine
│   └── __init__.py
├── scenario_engine/         # Scenario modeling engine
│   └── __init__.py
├── recommendation_engine/   # Recommendation engine
│   └── __init__.py
├── ingestion/               # Data ingestion from spreadsheets
│   ├── __init__.py
│   └── ingestion_agent.py
├── validation/              # Calendar logic, data quality, period validation
│   ├── __init__.py
│   ├── calendar.py
│   ├── data_quality.py
│   ├── models.py
│   ├── progression.py
│   └── validator.py
├── context/                 # Finance Context Pack builder
│   ├── __init__.py
│   └── context_builder.py
├── evidence/                # Evidence collection & tracking
│   ├── __init__.py
│   └── evidence_engine.py
├── prompts/                 # Typed prompt harness
│   ├── __init__.py
│   └── prompt_harness.py
├── guardrails/              # Hallucination detection & validation
│   ├── __init__.py
│   └── validation_harness.py
├── evaluation/              # Evaluation metrics & dashboards
│   └── __init__.py
└── reporting/               # Board report generation
    └── __init__.py
```

**Rules:**
- `finance/` NEVER imports from `apps/` or `agents/`.
- `finance/` may import from `shared/` only.
- All monetary values use `Decimal`, never `float`.

## `shared/` — Cross-Cutting

The foundational layer. Zero internal dependencies within the project.

```
shared/
├── __init__.py
├── config/              # Application configuration
│   ├── __init__.py
│   └── config.py
├── models/              # Shared Pydantic models
│   ├── __init__.py
│   ├── state.py         # Variance, AnalysisState, PipelineState
│   ├── assertions.py    # Assertion, AssertionType, SupportLevel
│   ├── database.py      # SQLAlchemy Base and ORM models
│   ├── degraded_mode.py # DegradedMode enum
│   └── action.py        # Action, ActionResult
├── utils/               # Shared utilities
│   ├── __init__.py
│   ├── confidence.py    # Confidence scoring
│   ├── encoders.py      # JSON encoders for Decimal
│   ├── llm_client.py    # LLM client abstraction
│   ├── policy.py        # Policy engine
│   ├── seed.py          # Data seeding utilities
│   └── tools/           # LangChain/LangGraph tools
│       ├── __init__.py
│       ├── gl_tools.py
│       ├── headcount_tools.py
│       ├── pipeline_tools.py
│       ├── rag_tools.py
│       ├── tool_result.py
│       └── vendor_tools.py
├── prompts/             # Shared prompt templates
│   └── __init__.py
└── schemas/             # Shared Pydantic schemas
    └── __init__.py
```

**Rules:**
- `shared/` NEVER imports from `apps/`, `agents/`, or `finance/`.
- This is the foundation — circular imports break the build.

## `tests/` — Test Suite

Mirrors the source directory structure. Four layers of testing:

```
tests/
├── conftest.py              # Shared test fixtures
├── unit/                    # Unit tests (pure logic)
│   ├── test_finance/
│   │   ├── test_formula_engine.py
│   │   ├── test_materiality.py
│   │   └── test_calendar.py
│   └── api/
│       └── test_decimal_layer.py
├── integration/             # Integration tests (database, pipelines)
├── backend/                 # Legacy backend tests (pre-refactor)
└── agents/                  # Agent tests (mocked LLM)
```

**Running tests:**
```bash
python -m pytest                                   # All tests
python -m pytest tests/unit/                       # Unit tests only
python -m pytest tests/unit/test_finance/          # Finance engine tests
python -m pytest tests/unit/test_finance/test_formula_engine.py  # Specific file
```

## `docs/` — Documentation

```
docs/
├── SYSTEM_ARCHITECTURE.md     # System architecture & data flow
├── testing.md                 # Testing strategy
├── development.md             # Developer guide
├── decisions.md               # Decision log
├── glossary.md                # Finance glossary
├── principles.md              # Design principles
├── repository.md              # This file
├── adr/                       # Architecture Decision Records (10 ADRs)
├── domain/                    # Domain model documentation
├── context/                   # Context engineering docs
├── guardrails/                # Guardrails and validation docs
└── evaluation/                # Evaluation metrics
```

## `alembic/` — Database Migrations

Standard Alembic migration scripts initialized with SQLAlchemy autogenerate support.

```
alembic/
├── env.py           # Migration environment
├── script.py.mako   # Migration template
└── versions/        # Migration revisions
```

## Root Files

| File | Purpose |
|------|---------|
| `pyproject.toml` | Project metadata, dependencies, tool config (ruff, mypy, pytest) |
| `README.md` | Project overview, quick start, core principles |
| `PRD.md` | Product Requirements Document |
| `ROADMAP.md` | Development roadmap |
| `CHANGELOG.md` | Version history |
| `CONTRIBUTING.md` | Contribution guidelines |
| `SECURITY.md` | Security posture & policies |
| `Dockerfile` | Container build (if present) |
| `docker-compose.yml` | Local development environment (if present) |
