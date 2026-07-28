# Testing Strategy

This document describes the comprehensive testing strategy for FinSight. The testing approach follows a layered pyramid: unit tests at the base, integration tests in the middle, and end-to-end (E2E) tests at the top, supplemented by golden dataset regression tests and LLM evaluation tests.

---

## Test Runner

All tests use **pytest** with the `asyncio_mode = "auto"` setting (configured in `pyproject.toml`). Run tests using the module invocation:

```bash
python -m pytest
```

The test suite currently contains **83 tests** across unit, integration, and agent test categories.

---

## Test Layers

```
        ┌───────────┐
        │    E2E    │  ← Full-stack, infrastructure-dependent
        ├───────────┤
        │   Agent   │  ← Mocked LLM, real pipeline wiring
        ├───────────┤
        │Integratio │  ← Component interaction, test DB
        ├───────────┤
        │   Unit    │  ← Pure logic, no I/O, fastest
        └───────────┘
```

---

## 1. Unit Tests

Unit tests cover pure logic with no I/O dependencies. They are the fastest tests and form the foundation of quality assurance.

### Location
`tests/unit/`

### What We Unit Test

| Area | Files | What's Tested |
|------|-------|---------------|
| Formula Engine | `tests/unit/test_finance/test_formula_engine.py` | Formula registration, dependency resolution, evaluation order, partial evaluation, error collection. |
| Materiality | `tests/unit/test_finance/test_materiality.py` | Materiality thresholds, percentage-based and absolute thresholds, edge values, zero boundaries. |
| Calendar / Periods | `tests/unit/test_finance/test_calendar.py` | Fiscal period generation, overlap detection, gap detection, period linking, prior-year references. |
| Decimal Layer | `tests/unit/api/test_decimal_layer.py` | `MoneyDecimal` validation, float rejection, Pydantic boundary enforcement. |

### Patterns

- **Deterministic inputs**: Hardcoded `Decimal` values, known period ranges, fixed formula definitions.
- **Expected outputs**: Assert exact `Decimal` equality (not `float`), boolean flags, error collections.
- **Edge cases**: Zero values, `None` inputs, empty lists, boundary thresholds.
- **No mocking**: Unit tests test real implementations directly.

### Example

```python
def test_formula_evaluator_respects_evaluation_order():
    registry = FormulaRegistry()
    registry.register(Formula(name="revenue", expression="price * quantity"))
    registry.register(Formula(name="price", expression="100"))
    registry.register(Formula(name="quantity", expression="50"))
    resolver = DependencyResolver(registry)
    evaluator = FormulaEvaluator(registry, resolver)
    context = evaluator.evaluate({})
    assert context.values["price"] == Decimal("100")
    assert context.values["quantity"] == Decimal("50")
    assert context.values["revenue"] == Decimal("5000")
```

---

## 2. Integration Tests

Integration tests verify that components work together correctly, including database interactions.

### Location
`tests/integration/`

### What We Integration Test

- Pipeline end-to-end flows against a test PostgreSQL database.
- Agent orchestration wiring (ingestion → variance → root cause → commentary → scenario).
- Data quality pipelines with real schema validation.
- API endpoint behavior with real request/response cycles.

### Infrastructure Dependencies

Integration tests require:
- A test PostgreSQL instance (provided via `docker-compose`).
- Test data fixtures configured in `tests/conftest.py`.

### Fixtures

Shared fixtures live in `tests/conftest.py`:
- `test_db`: Creates and tears down test database tables.
- `seed_data`: Loads known test datasets (18 GL accounts, 18 months for tenant CF001).
- `client`: FastAPI `TestClient` instance wired to the test database.

---

## 3. Golden Dataset Tests

Golden dataset tests provide **regression protection** by comparing outputs against known-correct baselines.

### Principle

For a given input set (the "golden dataset"), the system must produce outputs that match the stored baseline within an acceptable tolerance. Any deviation indicates either a bug or an intentional change that requires review.

### What's Covered

- Variance calculations against seeded CloudForge Inc. data.
- Formula engine evaluation results for standard KPI calculations.
- Materiality classifications for all 18 GL accounts across 18 months.
- Period validation results for the standard fiscal calendar.

### Running Golden Dataset Tests

```bash
python -m pytest tests/backend/agents/ -k "golden"
```

### When to Update the Golden Dataset

Update the golden dataset when:
- A new financial period is added to the seed data.
- A formula definition is intentionally changed.
- A materiality threshold is adjusted.
- A validation rule is modified.

All golden dataset updates require peer review.

---

## 4. LLM Evaluation Tests

LLM evaluation tests verify that agent-generated outputs meet quality, safety, and structural requirements. These tests use **mocked LLM responses** for deterministic execution.

### Location
`tests/backend/agents/`

### What We Evaluate

| Test Area | Focus | Files |
|-----------|-------|-------|
| Structured Output Compliance | Agents return valid, schema-conforming JSON | `test_agentic_formatting.py` |
| Hallucination Resistance | Claims made in commentary match source data | `test_agentic_hallucination_resistance.py` |
| Type Safety | Monetary values use Decimal, not float | `test_agentic_type_safety.py` |
| Tool Call Accuracy | Agents call correct tools with correct params | `test_agentic_tool_calls.py` |
| Decision Making | Agent routing decisions (material → root_cause) | `test_agentic_decision_making.py` |
| RAG Quality | Retrieval quality and relevance | `test_agentic_rag.py` |

### Measuring Hallucination Rate

The assertion pipeline and claim validator (`shared/utils/validators/claim_validator.py`) provide quantified hallucination detection:

- **NUMERIC claims**: Cross-referenced against database facts with tolerance thresholds. Claims outside tolerance are flagged.
- **COMPARATIVE claims**: Verified against known ranking/order from candidate data.
- **CAUSAL claims**: Never verified from prose alone — must link to driver tree and evidence.
- **ACTION claims**: Must map to approved taxonomy, cite validated causes, satisfy policy.

### Running LLM Evaluation Tests

```bash
python -m pytest tests/backend/agents/ -v
```

---

## 5. Edge Case Coverage

The test suite must cover these edge cases across all layers:

### Monetary & Numeric Edge Cases
| Edge Case | Where Tested |
|-----------|-------------|
| Zero values | Materiality tests, formula engine tests |
| Negative values (e.g., revenue correction) | Variance tests, schema validation |
| Very large values (overflow boundaries) | Formula engine stress tests |
| Precision edge cases (3+ decimal places) | Decimal layer tests |

### Data Quality Edge Cases
| Edge Case | Where Tested |
|-----------|-------------|
| Missing data (null fields) | Validation tests, ingestion tests |
| Empty datasets | Pipeline state machine tests |
| Partial period coverage | Calendar tests, integration tests |
| Duplicate records | Data quality validation tests |

### Temporal Edge Cases
| Edge Case | Where Tested |
|-----------|-------------|
| Fiscal year boundaries | Calendar tests |
| Leap year periods | Calendar tests |
| Period overlap | Period validator tests |
| Prior-year reference chains | Calendar linking tests |

### Pipeline Edge Cases
| Edge Case | Where Tested |
|-----------|-------------|
| No material variances → skip root cause | Agent decision tests |
| Critical degraded mode → skip root cause | Orchestrator tests |
| HITL review → remediation cycle | State machine tests |
| Pipeline retry after failure | Orchestrator tests |

---

## Running Tests

```bash
# Run all tests
python -m pytest

# Run with coverage report
python -m pytest --cov=finance --cov=agents --cov=apps --cov=shared

# Run unit tests only
python -m pytest tests/unit/

# Run integration tests
python -m pytest tests/integration/

# Run agent tests (mocked LLM)
python -m pytest tests/backend/agents/

# Run specific test file
python -m pytest tests/unit/test_finance/test_formula_engine.py

# Run with verbose output
python -m pytest -v

# Run tests matching a keyword
python -m pytest -k "materiality"
```

---

## Test Structure

```
tests/
├── conftest.py                 # Shared fixtures (test DB, seed data, client)
├── unit/
│   ├── api/
│   │   └── test_decimal_layer.py
│   └── test_finance/
│       ├── test_calendar.py
│       ├── test_formula_engine.py
│       └── test_materiality.py
├── integration/
│   └── (integration test files)
├── backend/
│   ├── agents/                  # Agent evaluation tests
│   ├── api/                     # API endpoint tests
│   ├── validators/              # Claim validator tests
│   ├── data/                    # Data pipeline tests
│   └── models/                  # Model tests
└── e2e/
    └── (end-to-end test files)
```
