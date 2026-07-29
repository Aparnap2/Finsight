# LLMOps — Language Intelligence Layer

**Document:** `docs/09-platform/llmops.md`
**Layer Stack:** LLMOps (Language Intelligence)
**Dependencies:** MLOps (downstream evaluation), DataOps (upstream context data), DevSecOps (CI gates)
**Status:** Active

---

## Purpose

LLMOps governs how FinSight deploys, routes, prompts, validates, evaluates, and
cost-manages the language model across the pipeline. It is the operational
discipline that ensures every LLM interaction is **typed, auditable,
budget-controlled, and confined to its architectural boundary** — language
generation only, zero arithmetic.

Unlike general-purpose LLM applications, FinSight's LLMOps layer operates under
an unusually tight constraint: **the LLM is never asked to compute**. Every
number the system surfaces has been pre-computed by deterministic Python code
operating on `Decimal` arithmetic. The LLM's job is exclusively linguistic —
decompose queries into action plans, generate explanatory narrative, and propose
hypotheses from structured data it is given, never from data it calculates.

This document covers the six pillars of LLMOps as implemented in the FinSight
codebase: prompt management, model routing, structured output generation,
response validation, evaluation, and cost/latency telemetry.

---

## The LLM Boundary

The defining architectural commitment of the FinSight platform is recorded in
**ADR-0005** (`docs/03-system-design/ADR/0005-deterministic-vs-llm.md`) and
reinforced by **ADR-007** (`docs/adr/ADR-007-no-llm-calculations.md`):

```
┌──────────────────────────────────────────────────────────┐
│                    LLM DOMAIN                             │
│                                                           │
│  Planner: query → ActionPlan (intent decomposition)      │
│  Commentary: assertions → narrative (text rendering)      │
│  Root-cause investigation: assertions → hypotheses        │
│  Scenario agent: context → parameter proposals            │
│                                                           │
│  RESTRICTED TO: language, intent, structure, narrative    │
│  NEVER: arithmetic, computation, fact generation          │
└──────────────────────────────────────────────────────────┘
                          │
                ActionPlan + Assertions
                          │
                          ▼
┌──────────────────────────────────────────────────────────┐
│                DETERMINISTIC DOMAIN                        │
│                                                           │
│  Formula evaluation (finance/formula_engine/)              │
│  Variance computation (finance/variance_engine/)           │
│  KPI computation (finance/kpi_engine/)                     │
│  Scenario projection (finance/scenario_engine/)            │
│  Confidence scoring (shared/utils/confidence.py)           │
│  Validation suite (finance/validation/)                    │
│  Policy engine (finance/policy/)                           │
│                                                           │
│  GUARANTEED: 100% reproducible, Decimal precision          │
└──────────────────────────────────────────────────────────┘
```

### Non-negotiable rules

| Rule | Enforcement |
|------|-------------|
| **No arithmetic in prompts** | CI gate scans all `finance/prompts/templates/` for arithmetic keywords (`calculate`, `sum`, `percentage`, `ratio`, `average`). Matches fail the build. |
| **No LLM in `finance/`** | The `finance/` package never imports `llm_client`. Enforced by `mypy` and code review. |
| **Exactly 2 LLM calls per pipeline run** | Planner (query → `ActionPlan`) + Commentary agent (assertions → narrative). Captured in telemetry; unexpected counts trigger alerts. |
| **No free-text LLM output** | Every LLM call passes a Pydantic `response_model`. No `json.loads()` on LLM responses. |
| **Every `$` figure is pre-computed** | LLM-rendered commentary references evidence IDs from deterministic engines. Enforced by `validate_commentary_claims()`. |

### What happens if the boundary is violated

The evaluation suite contains dedicated **governance datasets**
(`finance/evaluation/datasets/governance/`) that test for boundary violations:

- `forbidden_claim.json` — Detects absolute or definitive claims that cannot be
  supported by mixed evidence. The system must **qualify** its assertions.
- `policy_violation.json` — Detects LLM output that crosses from **analysis**
  into **enforcement recommendation** (e.g., "recommend disciplinary action").

The `PolicyCompliance` metric (`finance/evaluation/metrics.py`, line 145)
measures what fraction of assertions respected their `max_allowed_action`.
Assertions whose `max_allowed_action` is `block` or `escalate` count as
non-compliant. The business threshold for compliance is `break: 0.90`.

---

## Capabilities

The LLMOps layer delivers eight operational capabilities:

| # | Capability | Owner File(s) |
|---|-----------|---------------|
| 1 | **Provider-agnostic model routing** | `finance/llm/model_router.py` |
| 2 | **Structured output generation with retry** | `finance/llm/structured_generation.py` |
| 3 | **Response schema validation** | `finance/llm/response_validator.py` |
| 4 | **Per-call cost & latency telemetry** | `finance/llm/telemetry.py` |
| 5 | **Versioned prompt template management** | `finance/prompts/registry.py` |
| 6 | **Variable injection and rendering** | `finance/prompts/renderer.py` |
| 7 | **Pydantic input/output schemas** | `finance/prompts/schemas.py` |
| 8 | **Execution context capture** | `finance/prompts/execution_context.py` |

These capabilities are consumed through the `LLMClient` facade
(`finance/llm/client.py`), which wires routing, generation, and telemetry into a
single `generate()` call.

---

## Implementation Map

### 1. Provider-Agnostic Model Routing

**File:** `finance/llm/model_router.py`

The `ModelRouter` maintains a list of provider definitions with failover and
cooldown semantics:

```python
# Three providers configured by environment variables
_PROVIDER_DEFS = [
    {"name": "groq",       "model_env": "GROQ_CHAT_MODEL", ...},
    {"name": "openrouter", "model_env": "OPENROUTER_CHAT_MODEL", ...},
    {"name": "poolside",   "model_env": "POOLSIDE_CHAT_MODEL", ...},
]
```

- `select()` — Returns the first provider that has not failed within the
  cooldown window (default: 5 minutes). Providers are tried in order of
  definition.
- `record_failure(name)` — Marks a provider as failed, starting its cooldown
  timer. The router falls through to the next provider.
- `record_success(name)` — Clears a provider's failure state.

Failover behaviour: if all three providers are in cooldown, `select()` returns
`None`, and the `LLMClient` raises a `RuntimeError("No providers available")`.
No silent fallback, no degraded-mode LLM call — the pipeline halts with a clear
error.

### 2. Unified LLM Client

**File:** `finance/llm/client.py`

The `LLMClient` is the single entry point for all LLM interactions. It
orchestrates the router, generator, and telemetry in one call:

```python
class LLMClient:
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> BaseModel:
```

Workflow:

1. Call `router.select()` to get an available provider.
2. Instantiate `StructuredGeneration` with the provider's API key, base URL, and
   model name.
3. Call `gen.generate()` with up to 3 internal retries (exponential backoff:
   2s, 4s, 8s).
4. On success: record telemetry (`success=True`), call
   `router.record_success()`, return the validated Pydantic object.
5. On failure: record telemetry (`success=False`), call
   `router.record_failure()` (triggering cooldown loop), and retry with the next
   provider.

### 3. Structured Output Generation

**File:** `finance/llm/structured_generation.py`

The `StructuredGeneration` class wraps the OpenAI-compatible chat completion API
and enforces JSON output:

```python
class StructuredGeneration:
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        max_retries: int = 3,
    ) -> BaseModel:
```

- Sends `system_prompt` (role: system) and `user_prompt` (role: user) via
  `httpx` POST to `{base_url}/chat/completions`.
- Extracts JSON from the response text (handling markdown code fences via
  `_extract_json()`).
- Calls `response_model.model_validate(parsed)` to coerce the raw dict into a
  typed Pydantic instance.
- Retries up to `max_retries` times with exponential backoff on any error (HTTP
  failure, invalid JSON, Pydantic validation error).

### 4. Response Validation

**File:** `finance/llm/response_validator.py`

```python
class ValidationResult(BaseModel):
    is_valid: bool
    errors: list[str]
```

The `ResponseValidator` provides two validation paths:

| Method | Purpose | Used By |
|--------|---------|---------|
| `validate(output, expected_schema)` | Structural type conformance check | Post-generation gate |
| `validate_evidence(claim, evidence_ids, min_evidence=1)` | Evidence sufficiency check | Commentary agent output |

The evidence validator prevents unsupported claims: if the LLM produces a claim
with fewer than `min_evidence` evidence sources, it is flagged. This is the
operational gate for the `UnsupportedClaimRate` metric.

### 5. Telemetry and Cost Tracking

**File:** `finance/llm/telemetry.py`

Every LLM call records a telemetry entry with:

| Field | Source |
|-------|--------|
| `provider` | `ModelRouter` provider name |
| `model` | `ProviderConfig.model` |
| `prompt_name` | `response_model.__name__` |
| `latency_ms` | `time.monotonic()` delta |
| `success` | Whether the call succeeded |
| `timestamp` | `datetime.now()` |

The `Telemetry.summary()` method aggregates across calls:

```python
def summary(self) -> dict:
    # Returns: total_calls, total_tokens,
    #          success_rate (0.0–1.0),
    #          avg_latency_ms,
    #          by_provider (per-provider breakdown)
```

### 6. Prompt Template Registry

**File:** `finance/prompts/registry.py`

```python
class PromptRegistry:
    def register(self, name: str, version: str, template: str, description: str = "") -> None
    def get(self, name: str) -> PromptTemplate
    def has(self, name: str) -> bool
    def list_names(self) -> list[str]
```

Each `PromptTemplate` is a versioned, immutable object:

```python
class PromptTemplate(BaseModel):
    name: str
    version: str
    template: str        # "{variable}" placeholders
    description: str
    created_at: datetime
```

Templates are registered once (raises `ValueError` on duplicate name) and
retrieved by name. The registry provides no `update()` — template changes
require a new version registered under the same or different name.

### 7. Prompt Renderer

**File:** `finance/prompts/renderer.py`

```python
class PromptRenderer:
    def render(self, template: str, variables: dict[str, Any]) -> str
```

- Matches `{variable_name}` placeholders using regex.
- Raises `ValueError` on missing variables (all placeholders must be provided).
- Returns the fully rendered string ready for the LLM.

### 8. Prompt Schemas

**File:** `finance/prompts/schemas.py`

Defines typed input and output schemas for each prompt type:

| Schema Pair | Use |
|-------------|-----|
| `VarianceAnalysisInput` / `VarianceAnalysisOutput` | Single-account variance explanation |
| `ExecutiveSummaryInput` / `ExecutiveSummaryOutput` | Executive narrative |
| `BoardReportInput` | Board-level report context |

All monetary fields use the `MoneyDecimal` type alias:

```python
MoneyDecimal = Annotated[Decimal, BeforeValidator(_reject_float_money)]
```

This rejects `float` at the Pydantic boundary — only `Decimal`, `int`, or `str`
are accepted.

---

## Prompt Management

### Template Inventory

Six prompt templates are defined in `finance/prompts/templates/`:

| Template | File | Version | Purpose |
|----------|------|---------|---------|
| `board_report` | `templates/board_report.py` | 1.0.0 | Comprehensive board report from full context pack |
| `driver_investigation` | `templates/driver.py` | 1.0.0 | Root cause investigation behind a specific variance |
| `executive_summary` | `templates/executive_summary.py` | 1.0.0 | Executive narrative from aggregated financial data |
| `recommendation` | `templates/recommendation.py` | 1.0.0 | Actionable recommendations from variance analysis |
| `risk_assessment` | `templates/risk.py` | 1.0.0 | Financial risk assessment from variance and KPI data |
| `variance_analysis` | `templates/variance.py` | 1.0.0 | Single-account variance explanation |

### Render Flow

```
Raw Template ──→ PromptRenderer.render(template, variables) ──→ Rendered String
     │                                                              │
     │ {account_name}, {period_id}                                 │ "Analyze 'Product Revenue'
     │ {variance_amount}, ...                                      │  for 2026-Q1. Variance: $12,400..."
     │                                                              │
     ▼                                                              ▼
PromptRegistry.get(name)                                  LLMClient.generate(
                                      system_prompt=rendered, response_model=OutputSchema)
```

### Template Governance

All templates follow the same structure:

```
1. Role definition: "You are an FP&A analyst..."
2. Context block: structured data fields (no arithmetic instructions)
3. Instructions block: what to do with the data (linguistic tasks only)
4. Output format block: description of the expected structure
```

The CI arithmetic gate (`ADR-0005`, compliance item 4) scans all six template
files for prohibited keywords. None of the templates contain "calculate",
"sum", "subtract", "multiply", "divide", "percentage", "ratio", "average", or
"total" as a computational instruction.

---

## Structured Output Pipeline

Every LLM interaction flows through a five-stage pipeline:

```
┌─────────┐   ┌──────────┐   ┌──────────┐   ┌───────────┐   ┌────────┐
│ REQUEST │   │VALIDATE  │   │ GENERATE │   │  PARSE    │   │VALIDATE│
│         │──▶│  INPUT   │──▶│   LLM    │──▶│  JSON →   │──▶│OUTPUT  │
│ Prompt  │   │ Schema   │   │  Call    │   │ Pydantic  │   │ Schema │
│ + Model │   │ Conforms │   │ (max 3x │   │model_vali-│   │(typed) │
│         │   │          │   │ retries) │   │  date()   │   │        │
└─────────┘   └──────────┘   └──────────┘   └───────────┘   └────────┘
                                                                    │
                                                        ┌───────────┴──────────┐
                                                        ▼                      ▼
                                                   Valid ✓               Invalid ✗
                                                        │                      │
                                                        ▼                      ▼
                                              Use directly           Retry (3× max)
                                                                           │
                                                                  ┌─────────┴──────────┐
                                                                  ▼                    ▼
                                                            Succeeds            All retries fail
                                                                  │                    │
                                                                  ▼                    ▼
                                                            Use directly     Degraded mode:
                                                                           route_for_review
```

### Stage Details

1. **Request** — The caller selects a prompt template (via `PromptRegistry`),
   renders it with context variables (via `PromptRenderer`), and identifies the
   target `response_model`.

2. **Validate Input** — The input is validated against the Pydantic input schema
   (e.g., `VarianceAnalysisInput`). Rejects `float` monetary values, enforces
   required fields. This is a fast, deterministic check — no LLM involved.

3. **Generate** — `LLMClient.generate()` selects a provider via `ModelRouter`
   and calls `StructuredGeneration.generate()` with up to 3 retries on
   transient failures. The LLM receives system and user prompts and returns
   raw text.

4. **Parse** — The raw text is cleaned (markdown fence removal via
   `_extract_json()`) and parsed into a Python dict via `json.loads()`. If JSON
   parsing fails, this counts as a retry.

5. **Validate Output** — The parsed dict is coerced into the `response_model`
   via Pydantic's `model_validate()`. If validation fails (wrong types, missing
   fields, `MoneyDecimal` violations), the error is captured and the call is
   retried with the previous error message appended to the prompt.

### Retry and Degraded Mode

| Failure Mode | Retry Strategy | Fallback |
|-------------|----------------|----------|
| HTTP error (5xx, timeout) | Retry up to 3× with exponential backoff (2s, 4s, 8s) | Fail over to next provider |
| Invalid JSON in response | Retry up to 3× with error feedback in prompt | After 3 failures: `route_for_review` |
| Pydantic validation failure | Retry up to 3× with `validation_error` appended to prompt | After 3 failures: `route_for_review` |
| All providers in cooldown | None — `RuntimeError` raised immediately | Pipeline halts with clear error |

The degraded-mode fallback (`route_for_review`) ensures that **no malformed LLM
output enters the typed pipeline**. The assertion's `max_allowed_action` is set
to `route_for_review`, which the policy engine interprets as requiring human
intervention.

---

## Evaluation

### LLM-specific Metrics

The evaluation framework (`finance/evaluation/metrics.py`) defines six business
metrics and six runtime metrics. Three metrics are directly relevant to LLM
quality:

#### UnsupportedClaimRate (LLM Quality)

```python
class UnsupportedClaimRate:
    """Proportion of assertions with VERIFIED or PROBABLE support_level.
    Score of 1.0 = all assertions supported."""
```

**Threshold (from `finance/evaluation/thresholds/business.yaml`):**
- `warn`: 0.90
- `break`: 0.80

If fewer than 80% of assertions have sufficient evidence, the evaluation fails.
This is the primary guard against LLM overclaiming — it measures whether the
LLM's narrative assertions are backed by pre-computed deterministic evidence.

#### EvidenceCoverage (Attribution Quality)

```python
class EvidenceCoverage:
    """Average evidence items per assertion, normalised to a target."""
```

**Threshold:** `warn`: 0.80, `break`: 0.60

Measures whether the LLM is citing enough evidence sources per claim. Low
coverage suggests the LLM is making assertions without adequate supporting
context.

#### PolicyCompliance (Safety)

```python
class PolicyCompliance:
    """Fraction of assertions whose max_allowed_action was respected."""
```

**Threshold:** `warn`: 0.95, `break`: 0.90

An assertion with `max_allowed_action` of `block` or `escalate` (from the
policy engine) must not proceed. This catches cases where the LLM-generated
content crosses safety or policy boundaries.

#### ReportCoverage (Narrative Quality)

```python
class ReportCoverage:
    """Case-insensitive substring matching in report sections."""
```

**Threshold:** `warn`: 0.90, `break`: 0.80

Checks whether expected content (defined in golden datasets) appears in LLM-
generated report sections. This is a coarse quality gate for commentary output.

### Evaluation Datasets for LLM

Sixteen golden datasets in `finance/evaluation/datasets/` are relevant to LLM
quality:

| Category | Datasets | What They Test |
|----------|----------|---------------|
| `financial_logic/` | 7 datasets (fx_impact, budget_variance, negative_revenue, margin_decline, seasonality, revenue_growth, zero_budget) | LLM handles varied financial scenarios without numerical hallucination |
| `governance/` | 4 datasets (contradictory_evidence, low_confidence, policy_violation, forbidden_claim) | LLM respects policy boundaries, qualifies assertions, avoids definitive claims |
| `runtime_behaviour/` | 4 datasets (unsupported_assertions, missing_evidence, replanning_scenario, retry_scenario) | LLM response quality under degraded conditions |

### Run Cycle

```
Golden Datasets ──→ Harness ──→ HarnessResult ──→ EvaluationRunner ──→ EvaluationReport
                       │                                                │
                       │                                                ▼
                   Pipeline run                                    RegressionRunner
                  (LLM + deterministic)                     (compare vs baseline.json)
                                                                        │
                                                                        ▼
                                                                RegressionReport
                                                              (PASS / MINOR_REGRESSION /
                                                               REGRESSION_DETECTED)
```

The `RegressionRunner` (`finance/evaluation/regression.py`) stores baseline
evaluation results in `.regression_baseline/baseline.json`. Each run is compared
against the baseline, and a `REGRESSION_DETECTED` summary is produced if any
metric delta exceeds its `break_` threshold.

---

## Cost & Latency

### Per-Call Tracking

Every LLM call is recorded by `Telemetry.record()` with:

| Metric | Source |
|--------|--------|
| Provider | ModelRouter provider name |
| Model | ProviderConfig.model |
| Prompt name | `response_model.__name__` |
| Latency (ms) | `time.monotonic()` delta |
| Success | Boolean |
| Timestamp | `datetime.now()` |

Note: Token counts (`prompt_tokens`, `completion_tokens`) are currently stubbed
to `0` in `LLMClient` (`finance/llm/client.py`, lines 48-49, 62-63). The
telemetry schema accepts them, but the HTTP response body is not yet parsed for
`usage` fields. This is a planned enhancement: extracting `response.usage` from
the OpenAI-compatible API response to provide real token accounting.

### Budget Enforcement

The `AverageLatency` metric (`finance/evaluation/metrics.py`, line 241) provides
runtime budget enforcement:

```python
class AverageLatency:
    def __init__(self, budget_ms: int = 1000):
        self._budget_ms = budget_ms

    def compute(self, actions: list[Action]) -> float:
        # Score 1.0 if avg_latency <= budget_ms
        # Score 0.0 if avg_latency >= budget_ms * 2
        # Linear degradation in between
```

**Threshold (from `finance/evaluation/thresholds/runtime.yaml`):**
- `warn`: 0.80 (avg latency exceeds budget by ~20%)
- `break`: 0.60 (avg latency exceeds budget by ~40%)

### Provider Failover and Cost Implications

The router cycles through providers (groq → openrouter → poolside). Each
provider may have different pricing. The telemetry `by_provider` breakdown
enables:

- Cost allocation per provider (post token-count parsing implementation).
- Success-rate comparison for provider SLA management.
- Latency profiling to identify slow providers for optimisation.

### LLM Call Budget

A standard pipeline run makes exactly **two LLM calls**:

| Call | Purpose | Prompt Template | Response Model |
|------|---------|----------------|----------------|
| 1. Planner | Decompose user query into `ActionPlan` | N/A (generic system prompt) | `ActionPlan` |
| 2. Commentary | Render validated assertions into narrative | One of 6 templates based on output type | Commentary section schemas |

The executor, verifier, and reflection nodes make zero LLM calls. This budget
is enforced architecturally — those nodes import deterministic engines only and
have no access to `LLMClient`.

---

## Safety & Guardrails

### The No-Math Boundary

| Layer | Guardrail | Implementation |
|-------|-----------|---------------|
| **Prompt** | Zero arithmetic tokens | CI gate scans `finance/prompts/templates/*.py` |
| **Architecture** | No LLM in `finance/` | Dependency rules — `finance/` has no `llm_client` import |
| **Pipeline** | Exactly 2 LLM calls per run | Telemetry captures call count; unexpected values trigger alerts |
| **Output** | Every `$` figure references evidence | `validate_commentary_claims()` cross-checks LLM narrative |
| **Evaluation** | UnsupportedClaimRate ≥ 0.80 | Golden dataset governance tests + regression comparison |

### Forbidden Claims

The governance evaluation datasets (`forbidden_claim.json`,
`policy_violation.json`) test two safety axes:

1. **Overclaiming** — The LLM must not make definitive assertions when evidence
   is mixed. Example: "Revenue is definitely on track" is forbidden when cost
   data shows significant pressures. The expected behaviour is qualified
   language: "mixed signals: revenue growing 6.7%... but COGS up 16.7%".

2. **Policy enforcement** — The LLM must flag policy violations (e.g., travel
   spending 87.5% over budget) without making enforcement recommendations
   (e.g., "recommend disciplinary action"). The expected behaviour is factual
   reporting + routing for human review.

### `max_allowed_action` Enforcement

Every assertion carries a `max_allowed_action` field. The `PolicyCompliance`
metric measures whether this action was respected:

```python
assertion.max_allowed_action in ("block", "escalate")
    → counts as non-compliant
```

The policy engine (`finance/policy/`) determines `max_allowed_action` based on:

- Unsupported claim detection (from `ResponseValidator.validate_evidence()`)
- Confidence scoring (from `shared/utils/confidence.py`)
- Policy rule evaluation (from golden dataset governance rules)

### Safety Net: The Evaluation Regression Suite

The most important guardrail is the regression suite. Before any change to the
LLMOps layer is merged:

1. `EvaluationRunner.run_all()` executes all 16 golden datasets.
2. `RegressionRunner.run_and_compare()` compares results against
   `.regression_baseline/baseline.json`.
3. If any metric exceeds its `break_` threshold, the regression report summary
   is `REGRESSION_DETECTED` and the build fails.

This provides continuous protection against LLM regressions — a new prompt
template, a provider swap, or a router configuration change that degrades output
quality is caught before it reaches production.

---

## Summary of Files

| File | Role |
|------|------|
| `finance/llm/client.py` | Unified LLM client: router + generator + telemetry |
| `finance/llm/model_router.py` | Provider-agnostic routing with cooldown failover |
| `finance/llm/structured_generation.py` | OpenAI-compatible API call with JSON+Pydantic parsing |
| `finance/llm/response_validator.py` | Schema conformance + evidence sufficiency checks |
| `finance/llm/telemetry.py` | Per-call telemetry recording and summary aggregation |
| `finance/prompts/registry.py` | Versioned prompt template registry |
| `finance/prompts/renderer.py` | `{variable}` substitution in templates |
| `finance/prompts/schemas.py` | Pydantic input/output schemas + `MoneyDecimal` |
| `finance/prompts/execution_context.py` | Per-execution metadata capture |
| `finance/prompts/templates/*.py` | Six policy-defined prompt templates |
| `finance/evaluation/metrics.py` | UnsupportedClaimRate, EvidenceCoverage, PolicyCompliance |
| `finance/evaluation/runner.py` | Evaluation orchestration against golden datasets |
| `finance/evaluation/regression.py` | Baseline comparison + regression detection |
| `finance/evaluation/thresholds/business.yaml` | Business metric thresholds |
| `finance/evaluation/thresholds/runtime.yaml` | Runtime metric thresholds |
| `finance/evaluation/datasets/governance/` | Forbidden claim + policy violation test cases |
| `finance/evaluation/datasets/financial_logic/` | Financial scenario test cases |
| `docs/03-system-design/ADR/0005-deterministic-vs-llm.md` | No-math boundary ADR |
| `docs/adr/ADR-007-no-llm-calculations.md` | No-LLM-calculations reinforcement |
| `docs/adr/ADR-004-why-structured-outputs.md` | Pydantic-only output enforcement |

---

*This document is maintained by the FinSight architecture team. File issues and
PRs against `docs/09-platform/llmops.md`.*
