# Design Principles

These principles guide every architectural decision, code review, and design discussion in FinSight. They are listed in priority order — when principles conflict, the higher-ranked one wins.

---

## 1. Evidence over Intuition

**Every claim needs a source.**

The system must never assert a financial fact without traceable evidence. LLMs generate plausible-sounding text; FinSight validates every numeric claim against its source data.

**In practice:**
- Every `Assertion` carries `evidence_ids` pointing to specific source records.
- The commentary agent may arrange and paraphrase validated assertions but may not invent values or causes.
- Post-rendering validation cross-checks every `$` figure in commentary against the evidence context.
- If evidence is insufficient, the output degrades explicitly via `SupportLevel.WEAK` or `SupportLevel.INSUFFICIENT` — it never fabricates.

---

## 2. Deterministic over Probabilistic

**Math is never AI.**

Financial calculations — variances, growth rates, margins, materiality — are performed by pure Python functions with `Decimal` arithmetic. LLMs are reserved for rendering and explanation, never computation.

**In practice:**
- The formula registry (`finance/formula_engine/formula_registry.py`) evaluates all formulae deterministically.
- The materiality engine (`finance/variance_engine/materiality.py`) uses threshold comparison, not probability estimation.
- Bridge analysis (`finance/driver_engine/bridge_analysis.py`) decomposes variance through algebraic decomposition, not ML inference.
- LLMs receive pre-computed numeric values and may only render them into narrative text.

---

## 3. Typed over Dynamic

**Pydantic everywhere.**

Every data structure crossing a module boundary is a typed Pydantic model. No dictionaries, no `Any`, no runtime type guessing.

**In practice:**
- Request/response schemas in `apps/api/schemas.py` use `BaseModel` with `MoneyDecimal` for monetary fields.
- Agent nodes accept and return typed objects (`PipelineState`, `Variance`, `Assertion`, `CommentaryDraft`).
- Prompt inputs and outputs have explicit schemas (`VarianceCommentaryInput`, `VarianceCommentaryOutput`).
- Validation rules use typed input/output models (`CrossPeriodCheckInput`, `CrossPeriodCheckResult`).
- The `_reject_float_money` validator at the API boundary catches untyped data before it enters the system.

---

## 4. Explicit over Implicit

**No magic.**

Configuration is explicit. Dependencies are declared, not discovered. Side effects are visible, not hidden.

**In practice:**
- The formula registry requires explicit `Formula` registration — no decorator-based auto-discovery.
- Imports follow the layered architecture directly (`from finance.engine import ...`). No automatic module loading.
- The LangGraph state machine declares every state and transition explicitly in `agents/orchestrator.py`.
- Degraded mode is an explicit enum (`DegradedMode`) surfaced in pipeline state — not a hidden fallback.
- Configuration is loaded from typed settings (`shared/config/config.py`), not environment variable guessing.

---

## 5. Simple over Clever

**Readable code wins.**

Favor straightforward solutions over elegant abstractions. Code is read far more often than it is written.

**In practice:**
- The `FormulaRegistry.evaluate_all()` method uses Kahn's algorithm for topological sort — a standard algorithm with clear intent. A custom DAG solver would be "clever" but harder to audit.
- Bridge analysis uses explicit `if / elif` branches for each component type rather than a dynamic dispatch table. The mapping from component type to calculation is visible in one place.
- Materiality assessment uses a clear four-step function (classify → find rule → compare → assess) rather than a rule engine DSL.
- Prefer functions over classes when a function suffices. `compute_variances()` is a module-level function, not an object.

---

## 6. Context over Prompting

**Data quality > prompt engineering.**

A well-structured context pack produces better results than an elaborately crafted prompt. Invest in the data the LLM receives, not the instructions it follows.

**In practice:**
- Context builders (`finance/reporting/`, `agents/commentary/`) transform raw data into curated, filtered input for the LLM.
- Context packs are typed models with only the fields the prompt needs — no extraneous data.
- Raw financial data is never passed directly to an LLM. It is always aggregated, formatted, and scoped first.
- Prompt templates are short (< 50 lines). The heavy lifting is in the context builder.
- Context quality is tested through golden dataset evaluations, not prompt iteration.

---

## 7. Validation before Generation

**Guardrails gate AI output.**

The LLM is never the final authority on correctness. All AI-generated output must pass validation before it reaches the user.

**In practice:**
- The assertion pipeline (`finance/assertion_pipeline.py`) validates every claim against evidence before commentary receives it.
- The commentary agent has post-rendering validation that parses all `$` figures and cross-checks them against source data.
- Prompt output schemas (`VarianceCommentaryOutput`) are validated immediately after generation. Invalid output triggers degraded mode, not partial acceptance.
- The pipeline cannot advance past the commentary stage if post-generation validation fails.
- Validation rules are deterministic — they never depend on a second LLM call for verification.

---

## 8. Finance-First Modelling

**Domain drives architecture.**

The codebase is organized around financial concepts (variances, drivers, scenarios), not technical concepts (controllers, services, repositories).

**In practice:**
- Top-level directories reflect financial domains: `finance/`, `agents/`, `apps/`.
- The `finance/` subtree is organized by financial engine: `variance_engine/`, `formula_engine/`, `scenario_engine/`, `driver_engine/`, `forecast_engine/`, `recommendation_engine/`, `kpi_engine/`.
- Engine names match FP&A vocabulary. A finance domain expert can navigate the codebase without translation.
- The inner architecture of each engine mirrors the financial workflow, not a design pattern.
- Technical concerns (database models, configuration) live in `shared/` — they serve the domain, not the other way around.

---

## 9. Production over Prototype

**Tested code wins.**

No code is merged without tests. No pipeline change is merged without golden dataset regression tests. No prompt change is merged without LLM evaluation tests.

**In practice:**
- The test suite has 83+ tests across four layers: unit, integration, agent, and E2E.
- Financial calculations have extensive edge-case tests: zero values, negative variances, missing data, boundary thresholds.
- LLM evaluation tests measure structured output compliance and hallucination rates against golden datasets.
- The `CONTRIBUTING.md` checklist requires passing `ruff check .` and `mypy .` before every commit.
- Monetary tests use `Decimal` with explicit precision expectations — no floating-point comparisons.

---

## 10. Human Review over Autonomous Decisions

**No black-box AI.**

FinSight may investigate, analyze, and recommend — but it may not act without human approval. Every significant action routes through explicit review states.

**In practice:**
- The pipeline state machine includes explicit `review` and `remediation` states for human-in-the-loop approval.
- Policy decisions (`shared/utils/policy.py`) determine routing: auto-continue, route-for-review, or hard-stop.
- Degraded modes (low data quality, insufficient evidence, stale sources) always escalate to human review.
- The system is designed to be supervised incrementally: as trust builds, policies can be relaxed, but the architecture always preserves human oversight capability.
- Every action recommendation includes its supporting evidence, confidence score, and policy basis — so the human reviewer has full context for their decision.

---

## Applying These Principles

When facing a design decision, ask:

1. **Evidence**: Can every claim in this output be traced to a source record?
2. **Deterministic**: Is this calculation pure Python with `Decimal`, or does it depend on an LLM for math?
3. **Typed**: Are all data structures Pydantic models with explicit field types?
4. **Explicit**: Is the configuration, dependency, or side effect visible in the code?
5. **Simple**: Is this the most straightforward solution, or is it over-engineered?
6. **Context**: Have I optimized the input data before optimizing the prompt?
7. **Validation**: Is the LLM output checked before it reaches the user?
8. **Finance-first**: Does this structure reflect financial concepts or technical abstractions?
9. **Production**: Are there tests for the golden path and all edge cases?
10. **Human review**: Is there a human in the loop for consequential actions?
