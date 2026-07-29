# FinSight — Finance Operations OS

> A cognitive FP&A runtime that reduces variance analysis cycle time from days to minutes by combining LLM-guided planning with deterministic financial engines. Every calculation is auditable. Every claim is evidence-backed. Every decision is policy-bound.

---

## Engagement Summary

| Role | Duration | Delivery |
|------|----------|---------|
| Forward Deployed Engineer | 4 phases | Cognitive FP&A runtime with 22-scenario evaluation suite |

### Business Problem

FP&A teams spend 60–80% of each close cycle on mechanical work: importing actuals, reconciling sources, computing variances, validating assertions, and formatting reports. This leaves 1–2 days for strategic analysis in a typical 10-day close. Existing AI tools generate text when prompted but cannot own the analysis workflow, enforce data quality, or produce auditable outcomes.

### Engagement Scope

| Phase | Focus | Outcome |
|-------|-------|---------|
| **Phase 1** | Deterministic financial engines | Formula engine, KPI engine, variance engine, scenario engine — all Decimal arithmetic, zero float |
| **Phase 2** | Validation & data quality | Materiality assessment, evidence engine, data quality checks, assertion pipeline, policy enforcement |
| **Phase 3** | Cognitive reasoning runtime | Planner → executor → verifier → reflection loop with ActionPlan decomposition, telemetry, and iteration control |
| **Phase 4** | Evaluation & governance | 22 golden datasets, 12 evaluation metrics, regression harness with YAML thresholds, consulting documentation |

---

## Platform Architecture

FinSight is organised as five orthogonal operational disciplines, each with distinct assets, failure modes, and governance. They are not successive generations — they are layers in a platform.

```
                    Finance Operations OS

                 ┌────────────────────────┐
                 │       AgentOps         │
                 │   Orchestration Layer  │
                 ├────────────────────────┤
                 │        LLMOps          │
                 │  Language Intelligence  │
                 ├────────────────────────┤
                 │        MLOps           │
                 │  Predictive Modelling  │
                 ├────────────────────────┤
                 │       DataOps          │
                 │    Data & Quality      │
                 ├────────────────────────┤
                 │      DevSecOps         │
                 │  Foundation & Security  │
                 └────────────────────────┘
```

Each layer depends on the capabilities below it. Each has its own objectives, tooling, and success metrics. Each is documented in `docs/09-platform/`.

| Layer | Owns | doc |
|-------|------|-----|
| **AgentOps** | Workflow planning, coordination, scheduling, state, retries, HITL, escalation | `docs/09-platform/agentops.md` |
| **LLMOps** | Prompt management, model routing, structured outputs, guardrails, cost, latency | `docs/09-platform/llmops.md` |
| **MLOps** | Training, inference, monitoring, drift, retraining, offline evaluation | `docs/09-platform/mlops.md` |
| **DataOps** | Data pipelines, quality, validation, catalog, lineage, transformations | `docs/09-platform/dataops.md` |
| **DevSecOps** | CI/CD, IaC, observability, secrets, security, deployment, runtime | `docs/09-platform/devsecops.md` |

### Cognitive Runtime Pipeline

The AgentOps layer orchestrates this five-node loop:

```
  Query
    │
    ▼
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ Planner  │───▶│Retriever │───▶│ Executor │───▶│Verifier  │───▶│Reflection│
│  (LLM)   │    │  (Data)  │    │  (Math)  │    │  (Rules) │    │  (Meta)  │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
    │                │               │               │               │
    ▼                ▼               ▼               ▼               ▼
 ActionPlan     EvidenceData    EngineResults    Assertion        LoopDecision
                                                                     │
                                                          ┌──────────┴──────────┐
                                                          ▼                    ▼
                                                      "finalize"          "revise"
```

### Key Architecture Decisions

All documented as Architecture Decision Records in `docs/03-system-design/ADR/`:

| ADR | Decision |
|-----|----------|
| 001 | Layered cognitive runtime — planner (AI) → executor (deterministic) → verifier (rules) |
| 002 | Structured assertion model with 5 types and 4 support levels |
| 003 | Iterative plan-execute-verify-reflect loop, max 5 iterations |
| 004 | Golden dataset evaluation with nested expectations across all pipeline stages |
| 005 | LLM restricted to language generation only — all math is deterministic |

### Dependency Flow

```
apps/  →  agents/  →  finance/  →  shared/
```

`shared/` imports from nothing within the project. `finance/` imports only from `shared/`. Agents orchestrate domain logic. The API layer depends on everything below it.

### Decision Ownership

The five Ops disciplines answer different questions:

| Owner | Decision |
|-------|----------|
| **AgentOps** | What should happen because the score is 0.93? Retry? Escalate? Finalize? |
| **LLMOps** | Extract fields. Summarise. Explain. Draft narrative. |
| **MLOps** | Predict risk. Predict fraud. Forecast cash flow. |
| **DataOps** | Is the data valid? Complete? Trustworthy? Has lineage been preserved? |
| **DevSecOps** | Can this be deployed? Secure? Monitored? Rolled back? |

---

## How Correctness Is Validated

### Golden Dataset Benchmarks

22 scenarios across 4 categories, each specifying expected behaviour for all 5 pipeline stages:

| Category | Count | Example |
|----------|-------|---------|
| Financial Logic | 7 | Revenue growth, margin decline, budget variance, FX impact |
| Data Quality | 5 | Missing values, duplicate rows, malformed spreadsheets |
| Runtime Behaviour | 4 | Retry scenarios, replanning, missing evidence |
| Governance | 4 | Policy violations, contradictory evidence, forbidden claims |

### Metrics

**Business metrics** measure financial correctness:

| Metric | Measures |
|--------|----------|
| VarianceAccuracy | Variance records match expected by account_id and amount |
| KPIAccuracy | KPI values match expected within tolerance |
| ReportCoverage | Expected content appears in report sections |
| UnsupportedClaimRate | Proportion of assertions with adequate evidence |
| EvidenceCoverage | Average evidence items per assertion |
| PolicyCompliance | Assertions respecting max_allowed_action |

**Runtime metrics** measure the cognitive agent:

| Metric | Measures |
|--------|----------|
| PlanningAccuracy | Required/forbidden intent coverage |
| ReplanningFrequency | Iteration count vs budget |
| ActionSuccessRate | Fraction of actions completing successfully |
| RetryRate | Total retries per action |
| AverageLatency | Mean action latency vs budget |
| ToolFailureRate | Fraction of tool calls that failed |

### Regression Detection

Threshold-based comparator with warn and break levels per metric. Breaking changes automatically flagged in CI.

---

## Business Impact

### What this replaces

FP&A teams spend 60–80% of each close cycle on mechanical work — importing actuals, reconciling sources, computing variances, validating cross-foots, and formatting reports. This leaves 1–2 days for strategic analysis in a typical 10-day close.

**Before FinSight:** 6 of 12 analysts dedicated to spreadsheet computation. 3–5 calculation errors per quarter caught by audit. Zero evidence traceability — every report claim was unattributed. Root cause analysis was anecdotal, driven by tenure rather than data.

**After FinSight:**

| KPI | Before | After |
|-----|--------|-------|
| Variance analysis cycle time | 3 days | ~4 minutes |
| Analyst time on computation | 80% | &lt;10% |
| Calculation errors per quarter | 3–5 | 0 — Decimal arithmetic, zero float |
| Evidence traceability | 0% of claims | 100% — every assertion carries evidence IDs |
| Regression detection | Manual, reactive | Automated, proactive — breaking changes caught in CI |

### Why the LLM is intentionally restricted

| Can do | Cannot do |
|--------|-----------|
| Decompose query into ActionPlan | Compute financial figures |
| Generate narrative commentary from assertions | Access raw spreadsheet data directly |
| Suggest hypotheses for root cause analysis | Override deterministic confidence scores |

The architectural boundary is absolute: the LLM generates text from pre-validated assertions. All math, validation, verification, and reflection run through deterministic Python code. This guarantees:

- **Zero hallucination of financial figures.** The LLM never touches a number.
- **Audit-grade traceability.** Every claim in the output traces to source records via typed evidence IDs.
- **Deterministic correctness.** Decimal arithmetic eliminates floating-point errors.

### What this enables

- **Analysts shift from computation to analysis.** The system handles the mechanical loop (data validation, variance computation, KPI evaluation, materiality flagging). Analysts own the analytical loop (root cause, scenario modelling, strategic recommendations).
- **Reports become auditable.** Every assertion carries type, support level, confidence score, and evidence IDs. A reviewer can trace any claim to its source in seconds.
- **Breaking changes are caught before deployment.** 22 golden datasets × 12 metrics = 264 data points checked per regression run. YAML thresholds define warn/break boundaries per metric.

---

## Project Structure

```
finsight/
├── docs/
│   ├── 00-executive-summary/        # Business context, problem statement, success metrics
│   ├── 03-system-design/ADR/        # 5 Architecture Decision Records
│   ├── 07-ai-runtime/               # Planner, executor, verifier, reflection deep-dives
│   └── 08-evaluation/               # Benchmarks, golden datasets, metrics, regression
│
├── finance/
│   ├── cognition/                   # Cognitive runtime (harness, registry, state, action, telemetry)
│   │   └── nodes/                   # Planner, retriever, executor, verifier, reflection
│   ├── evaluation/                  # Evaluation framework (22 golden datasets, 12 metrics, regression)
│   │   ├── datasets/                # JSON scenario files by category
│   │   ├── scenarios/               # Python factory functions
│   │   └── thresholds/              # YAML threshold files (runtime + business)
│   ├── formula_engine/              # Deterministic formula definitions and evaluation
│   ├── variance_engine/             # Variance computation and materiality assessment
│   ├── validation/                  # Data quality checks, calendar, period validation
│   ├── driver_engine/               # Bridge analysis (variance decomposition)
│   ├── kpi_engine/                  # KPI evaluation
│   ├── scenario_engine/             # Scenario modelling
│   ├── forecast_engine/             # Forecasting
│   └── assertion_pipeline.py        # Tool results → typed assertions
│
├── docs/engagement/                # Consulting case study (end-to-end engagement narrative)
├── docs/diagrams/                  # Architecture, runtime lifecycle, and evaluation diagrams
│
├── agents/                          # LangGraph orchestration
├── apps/api/                        # FastAPI REST layer
├── shared/                          # Models, config, validators, utilities
├── tests/                           # 342 tests (unit, integration, agent, evaluation)
│
├── docs/adr/                        # Earlier ADRs (architecture, domain, guardrails)
├── pyproject.toml
└── docker-compose.yml
```

---

## Stack

| Layer | Technology |
|-------|-----------|
| Runtime | Python 3.12+ with Pydantic v2, mypy strict, ruff |
| API | FastAPI |
| Orchestration | LangGraph with custom ReasoningHarness |
| LLM Boundary | LiteLLM — only planner and report generation |
| Numeric | `decimal.Decimal` — zero float in monetary operations |
| Database | PostgreSQL 16 (asyncpg) |
| Testing | pytest (342 tests), ruff, mypy strict |
| Containerization | Docker Compose |

---

## Quick Start

```bash
# Install
uv sync

# Run tests (342)
uv run python -m pytest

# Type-check
uv run mypy .

# Lint
uv run ruff check .

# Open architecture diagrams
open docs/diagrams/system-architecture.html
open docs/diagrams/runtime-lifecycle.html
open docs/diagrams/evaluation-pipeline.html

# Read case study
cat docs/engagement/case-study.md

# Start API
uv run uvicorn apps.api.main:app --reload
```

---

## Key Outcomes

- **Architecture**: 5 ADRs documenting every major design decision
- **Evaluation**: 22 golden datasets × 12 metrics = 264 data points per regression run
- **Quality**: 342 tests, mypy strict clean, ruff clean, zero float in monetary operations
- **Runtime**: LLM restricted to 2 calls per pipeline (planning + report generation); all math is deterministic
- **Documentation**: Full consulting-style engagement artefacts (executive summary, ADRs, runtime deep-dives, evaluation docs, case study, architecture diagrams)
- **Cycle time reduction**: Variance analysis from 3 days to ~4 minutes
