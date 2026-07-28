# ADR-001: Hybrid AI Architecture — Deterministic + LLM

**Status:** Accepted  
**Date:** 2026-07-28  
**Deciders:** Architecture Team  

---

## Context

FinSight must provide financial analysis — variance commentary, root-cause investigation, scenario modelling, and KPI reporting — that FP&A teams can trust with actual budget decisions. Pure LLM approaches hallucinate numbers, produce inconsistent arithmetic, and cannot guarantee correctness of financial calculations. Pure deterministic systems produce accurate numbers but cannot generate the narrative explanations, causal hypotheses, and free-text commentary that FP&A teams depend on for board reporting.

The core tension: LLMs excel at language generation, summarisation, and causal reasoning from unstructured context — but they fail at exact financial arithmetic. We need both capabilities in a single system without letting LLM weaknesses compromise numerical integrity.

Project constraints reinforce this:
- Monetary values use `decimal.Decimal` — never `float` — enforced at Pydantic boundaries
- All financial assertions must carry evidence references and confidence scores
- The system must support human-in-the-loop review with auditable provenance

## Decision

We adopt a **Hybrid AI Architecture** with a strict separation of concerns:

### Layer 1: Deterministic Finance Engine (Zero LLM)

All mathematical computation lives in `finance/` — a pure Python package with zero LLM calls:

| Engine | Responsibility |
|--------|---------------|
| `formula_engine/` | Declarative formula definitions, topological evaluation, KPI computation |
| `variance_engine/` | Actual-vs-budget variance computation, materiality assessment |
| `validation/` | Fiscal calendar generation, period lifecycle, data quality |
| `driver_engine/` | Bridge variance decomposition (price/volume/mix, timing/scope) |
| `ingestion/` | Data ingestion from databases and files |
| `assertion_pipeline/` | Tool results → typed, validated, confidence-scored assertions |

**Rules:**
- No LLM call originates from `finance/`
- All monetary arithmetic uses `Decimal` with exact precision
- Every computation is deterministic — same inputs always produce same outputs
- Unit tests verify exact output values (not ranges or approximations)

### Layer 2: LLM Layer (Read-Only, Rendering Only)

LLMs operate only in `agents/` and are strictly constrained:

| Agent | Role | Constraint |
|-------|------|------------|
| Root-Cause Agent | Investigate material variances | Read-only tool access. Produces hypotheses with evidence citations. Never generates numbers. |
| Commentary Agent | Render narrative from assertions | Truth/render separation — LLM receives only validated assertions. Cannot invent values. Prohibited from upgrading hypotheses to facts. Post-render claim validation cross-checks every `$` figure. |
| Scenario Agent | What-if analysis | Deterministic projection engine. LLM proposes scenario parameters only. |

### Layer 3: Assertion Pipeline (Bridge Layer)

Between deterministic engines and LLM rendering sits the **assertion pipeline** (`finance/assertion_pipeline.py`):

1. Deterministic engines produce `ToolResult` objects
2. Pipeline converts results into typed `Assertion` objects with `AssertionType.NUMERIC`, `COMPARATIVE`, `CAUSAL`, `HYPOTHESIS`, `ACTION`
3. Each assertion receives a deterministic confidence score and support level
4. Only passing assertions reach the commentary agent
5. Policy engine (`shared/utils/policy.py`) decides autonomy level based on assertion confidence and degraded modes

```
Deterministic Engine → ToolResult → Assertion Pipeline → Typed Assertions → LLM Renderer
                                                                                ↓
                                                                       Claim Validator
                                                                       (cross-check)
```

## Consequences

### Positive

- **Mathematical correctness guaranteed.** Every `$` value originates from deterministic code. LLMs never calculate.
- **Auditable provenance.** Every assertion carries evidence IDs, source type, and confidence score. Reviewers can trace any number back to its source.
- **Controlled LLM risk.** LLM failure modes are contained to language quality and hypothesis generation — never numerical error.
- **Testable by layer.** `finance/` tests verify exact outputs. Agent tests verify structured output compliance. Integration tests verify the full pipeline.
- **Degraded-mode resilience.** When data quality is low, the policy engine routes to human review before LLM rendering occurs.

### Negative

- **More code to maintain.** Two parallel processing layers instead of one end-to-end LLM pipeline.
- **Rigid interface between layers.** The assertion schema (`Assertion`, `AssertionType`, `SupportLevel`) becomes a critical shared contract — changes require coordination across `finance/`, `shared/`, and `agents/`.
- **LLM rendering is still non-deterministic.** The commentary agent can produce different wording for the same assertions on different calls. Claim validation catches numerical drift but not stylistic variation.
- **Higher latency.** Full pipeline execution (deterministic → assertion → LLM → validation) takes longer than either layer alone.

## Compliance

1. **No arithmetic in LLM prompts.** Every prompt template in `shared/prompts/` is audited — no `$` calculation, no percentage computation, no formula execution requested of the LLM.
2. **`finance/` imports zero LLM dependencies.** The `finance/` package must not import `litellm`, `openai`, `langgraph`, or any LLM-related library. Enforced via `ruff` import rules.
3. **Assertion pipeline is mandatory.** No route exists for raw data to reach the commentary agent without passing through the assertion pipeline.
4. **Claim validator runs post-rendering.** Every commentary draft produced by the LLM must pass through `validate_commentary_claims()` before it can be returned to the user.
5. **CI gate.** Any PR that adds an LLM call to `finance/` is automatically rejected. Any PR that bypasses the assertion pipeline is automatically rejected.
