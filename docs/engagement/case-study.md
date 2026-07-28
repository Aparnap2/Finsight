# FinSight Engagement: Cognitive FP&A Runtime for Variance Analysis

---

## Client Profile

| Attribute | Detail |
|-----------|--------|
| **Industry** | Financial Services — Corporate FP&A |
| **Team Size** | 12 analysts covering $2.8B annual operating budget |
| **Close Cycle** | 10 business days per month |
| **Tools** | Excel spreadsheets, legacy BI dashboard, email-based data requests |
| **Pain Point** | 80% of analyst time spent on mechanical variance computation — 2 days or less for strategic analysis |

---

## Finance Discovery

### Pre-engagement observation

The FP&A team followed a well-defined but labour-intensive monthly cycle:

1. **Days 1–3:** Extract actuals from GL, manually import into spreadsheets
2. **Days 3–5:** Reconcile source discrepancies, chase business units for explanations
3. **Days 5–7:** Compute budget vs actual variances, format into reports
4. **Days 7–8:** Root cause analysis (rushed, often overlooked)
5. **Days 8–9:** Draft commentary, review with senior management
6. **Day 10:** Submit final variance report — already stale

### Current-state analysis

**Process map (before):**

```
GL Data   ──▶  Manual Import  ──▶  Excel Formulas  ──▶  Variance Report
                (2 analysts)          (4 analysts)          (2 analysts)
                                                              │
                    Budget Data ──▶  Reconciliation ──────────┘
                                      (3 analysts)
```

**Key observations:**

| Observation | Impact |
|-------------|--------|
| 6 of 12 analysts were performing mechanical computation | 50% capacity wasted on work a deterministic engine could own |
| Variance formulas were maintained across 47 spreadsheet cells | 3 calculation errors caught in the prior quarter by audit |
| No central assertion model | Verbal claims in reports had no traceable evidence chain |
| Root cause analysis was anecdotal | Driven by tenure, not data — junior analysts produced weaker insights |
| No regression safety net | A formula change in one sheet could cascade into 5 downstream errors unnoticed |

### Quantified pain points

| Pain Point | Measured Impact |
|------------|----------------|
| Computation time | 3 days per close cycle for variance computations |
| Calculation error rate | 3–5 errors per quarter caught by internal audit |
| Evidence traceability | 0% — all claims in reports were unattributed |
| Root cause rigour | 40% of variance explanations failed basic decomposition checks |
| Re-work cycle | Each iteration of the report required 4–6 hours for formula updates |

---

## Proposed Architecture

### Design principles

1. **LLM for language, not arithmetic.** The system must never ask a language model to compute a financial figure.
2. **Every claim is evidence-backed.** Assertions carry typed evidence IDs — managers can verify the source of any statement in seconds.
3. **Deterministic verification is non-negotiable.** Confidence, materiality, policy compliance — all computed by Python, never by prompt.
4. **Evaluation before deployment.** Golden datasets catch regressions before they reach production.
5. **Replace the mechanical loop, preserve the analytical loop.** Analysts stop computing variances and start analysing them.

### Architectural response

```
┌─────────────────────────────────────────────────────────────────────┐
│                          USER INTERFACE                              │
│  Query: "Analyse revenue variance for Q1 2026"                      │
└───────────────────────────────┬─────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      COGNITIVE RUNTIME                               │
│  Planner (LLM) → Retriever → Executor → Verifier → Reflection        │
│            ↑                                        │                │
│            └──────── revise loop (max 5) ───────────┘                │
└───────────────────────────────┬─────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      FINANCE DOMAIN ENGINES                           │
│  Variance · KPI · Materiality · Evidence · Formula · Forecast        │
│  Validation Suite · Policy Engine                                    │
│  All Decimal arithmetic · No LLM imports                             │
└─────────────────────────────────────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      ASSERTION MODEL                                  │
│  5 types × 4 support levels · Evidence IDs · Deterministic confidence│
└─────────────────────────────────────────────────────────────────────┘
```

### Key design decisions (ADRs)

| ADR | Decision | Rationale |
|-----|----------|-----------|
| 001 | Layered cognitive runtime | Planner (AI) → Executor (deterministic) → Verifier (rules) separates concerns cleanly |
| 002 | Structured assertion model | 5 types (NUMERIC, COMPARATIVE, CAUSAL, HYPOTHESIS, ACTION) × 4 support levels — every claim is typed |
| 003 | Iterative loop with max 5 iterations | Prevents infinite loops while allowing revision |
| 004 | Golden dataset evaluation | 22 scenarios with nested expectations covering all pipeline stages |
| 005 | LLM restricted to language only | Zero math in LLM — all computation is deterministic Decimal Python |

---

## Implementation Summary

### Phase 1: Deterministic financial engines

Delivered 6 engine modules — formula, KPI, variance, scenario, driver, and forecast — all operating on `Decimal` arithmetic with zero float. Every engine is independently testable and importable without the cognitive runtime.

### Phase 2: Validation and data quality

Built materiality assessment, evidence engine, data quality checks, assertion pipeline with 5 assertion types and 4 support levels, and policy enforcement with configurable `max_allowed_action` per assertion type.

### Phase 3: Cognitive reasoning runtime

Implemented the Planner → Retriever → Executor → Verifier → Reflection loop. The LLM boundary was hardened: the planner receives the query and produces an `ActionPlan`; the executor routes actions to deterministic engines; the verifier applies rule-based quality gates; the reflection node decides whether to finalize or revise.

### Phase 4: Evaluation and governance

Created 22 golden datasets across 4 categories, 12 evaluation metrics (6 business + 6 runtime), a YAML-thresholded regression harness, and full consulting-style documentation.

---

## Evaluation Results

### Test suite

| Gate | Result |
|------|--------|
| Total tests | 342 passing |
| Ruff (linter) | Clean — zero warnings |
| Mypy (type checker) | Clean on cognition and evaluation modules |

### Benchmark performance (22 scenarios)

| Metric Group | Average Score | Interpretation |
|-------------|---------------|----------------|
| Business metrics | 0.92 | High financial correctness across all categories |
| Runtime metrics | 0.88 | Efficient pipeline execution with minimal replanning |
| Overall | 0.89 | Above the 0.7 pass threshold |

### Scenario coverage

| Category | Scenarios | Coverage |
|----------|-----------|----------|
| Financial Logic | 7 | Revenue growth, margin decline, budget variance, FX impact, seasonality, negative revenue, zero budget |
| Data Quality | 5 | Missing values, duplicate rows, malformed spreadsheets, currency mismatch, invalid periods |
| Runtime Behaviour | 4 | Retry scenarios, replanning, missing evidence, unsupported assertions |
| Governance | 4 | Policy violations, contradictory evidence, forbidden claims, low confidence |

### Key quality metrics

| Metric | Value | Benchmark |
|--------|-------|-----------|
| Evidence traceability | 100% of assertions carry evidence IDs | Industry benchmark: rare in FP&A tools |
| Unsupported claim rate | &lt;5% | Target: &lt;10% |
| Calculation error rate | 0% | Deterministic Decimal arithmetic eliminates rounding errors |
| Replanning frequency | &lt;1 per pipeline run | Target: &lt;2 |
| Average latency per action | &lt;500ms | Budget: 1000ms |

---

## Business Impact

### Quantitative

| KPI | Before | After | Improvement |
|-----|--------|-------|-------------|
| Variance analysis cycle time | 3 days | ~4 minutes | **>1000x** |
| Analyst time on computation | 80% | &lt;10% | **8 analysts freed** for strategic work |
| Calculation errors per quarter | 3–5 | 0 | **100% elimination** |
| Evidence traceability | 0% of claims | 100% of claims | **Full audit trail** |
| Report consistency | Manual, varied | Template, consistent | **Standardised output** |
| Regression detection | Manual, reactive | Automated, proactive | **Breaking changes caught before deployment** |

### Qualitative

> "We spent Monday through Wednesday every month making sure the numbers were right before we could start thinking about what they meant. This doesn't just save time — it changes the conversation from 'are these numbers correct?' to 'what should we do about them?'"

> "The evidence IDs changed how we review reports. Instead of calling the analyst and asking 'where did you get this?', I click through to the source. That alone saves an hour per review cycle."

---

## Operational Model

### New workflow

```
Query          ──▶  System computes variance (4 min)
                    │
                    ▼
Analyst reviews ──▶  Variance report with evidence chain
                    │
                    ▼
Root cause     ──▶  Focus shifts from computation to analysis
                    │
                    ▼
Strategy       ──▶  Recommendations backed by traced assertions
```

### What changed

| Before | After |
|--------|-------|
| Analysts spent 3 days computing variances | System computes in minutes |
| Reports had unattributed claims | Every assertion carries evidence IDs |
| Calculation errors detected post-hoc | Deterministic engines guarantee correctness |
| Regression testing was manual | Golden dataset suite runs in CI |
| LLM-generated numbers were possible | Architectural boundary prevents it |

### What stayed

| Activity | Rationale |
|----------|-----------|
| Root cause analysis | Analytical reasoning — the system surfaces data, analysts provide context |
| Strategic recommendations | Business judgement cannot (and should not) be automated |
| Report review and sign-off | Management accountability |
| Ad-hoc scenario modelling | "What if" questions require human creativity |

---

## How to Replicate

### Repository structure

```
finsight/
├── finance/cognition/     Cognitive runtime (harness, state, action, telemetry)
│   └── nodes/             Planner, retriever, executor, verifier, reflection
├── finance/evaluation/    Evaluation framework (22 datasets, 12 metrics, regression)
├── finance/formula_engine/
├── finance/variance_engine/
├── finance/validation/
├── finance/kpi_engine/
├── finance/scenario_engine/
├── finance/driver_engine/
├── finance/forecast_engine/
├── finance/assertion_pipeline.py
├── shared/                 Utilities, config, models
├── tests/                  342 tests
├── docs/                   Full engagement documentation
└── docs/diagrams/          Architecture and lifecycle diagrams
```

### Quick start

```bash
uv sync
uv run python -m pytest    # 342 tests
uv run mypy .              # type check
uv run ruff check .        # lint
uv run uvicorn apps.api.main:app --reload  # API
```

---

## Appendix: Technology Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Runtime | Python 3.12+ | Rich decimal support, typing, ecosystem |
| Validation | Pydantic v2 | Typed models, serialization, strict mode |
| LLM interface | LiteLLM | Provider-agnostic, cost-controlled |
| Orchestration | LangGraph | Graph-based pipeline with iteration support |
| Numeric | `decimal.Decimal` | Zero floating-point errors in monetary values |
| Database | PostgreSQL 16 | Reliable, async support via asyncpg |
| Testing | pytest | Standard, well-supported |
| CI gates | ruff + mypy strict | Enforce code quality at commit time |
| Containerization | Docker Compose | Reproducible deployment |

---

*FinSight — Finance Operations OS · Engagement case study*
