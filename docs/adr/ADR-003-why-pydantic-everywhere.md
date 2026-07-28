# ADR-003: Why Pydantic v2 Across All Boundaries

**Status:** Accepted  
**Date:** 2026-07-28  
**Deciders:** Architecture Team  

---

## Context

FinSight has four distinct architectural layers (`shared/`, `finance/`, `agents/`, `apps/`) plus external boundaries (API, database, LLM). Data flows across these layers constantly. In early prototypes, we used a mix of patterns:

- TypedDicts for pipeline state
- Raw `dict` for function returns
- `dataclass` for internal models
- `BaseModel` (Pydantic v1) for API schemas

This heterogeneity caused recurring problems:
- **No type enforcement at boundaries.** A function returning `dict` could silently drop keys, add unexpected keys, or change value types. Crashes appeared at runtime in unrelated code.
- **Monetary value drift.** Without Pydantic validation, `float` values leaked into `Decimal` fields, causing rounding errors in financial calculations.
- **LLM response parsing fragility.** LLM outputs parsed with regex or raw JSON parsing failed silently when structure changed — producing `None` fields or wrong types.
- **No serialisation guarantees.** Converting between `dict`, JSON, and Python objects required ad-hoc encoder/decoder functions. The `DecimalEncoder` in `shared/utils/encoders.py` was necessary because models didn't handle their own serialisation.
- **Schema drift between layers.** The API schema, the pipeline state schema, and the database schema could (and did) diverge — a field added to the database was forgotten in the API response.

## Decision

Every data structure that crosses a system boundary **must** be a **Pydantic v2 `BaseModel`**.

### Where Pydantic Is Required

| Boundary | Model | Enforcement |
|----------|-------|-------------|
| **API request/response** | `apps/api/schemas.py` | FastAPI validates using Pydantic automatically |
| **Pipeline state** | `shared/models/state.py` (`Variance`, `EvidenceItem`, `RootCauseFinding`, `CommentaryDraft`, `Scenario`) | Type-checked by `mypy` in strict mode. `PipelineState` itself is a `TypedDict` (for LangGraph compatibility) but all value objects within it are `BaseModel`. |
| **Assertions** | `shared/models/assertions.py` (`Assertion`, `AssertionType`, `SupportLevel`) | All assertion types are Pydantic enums and models |
| **Domain models** | `finance/validation/models.py` (`FiscalPeriod`), `finance/variance_engine/materiality.py` (`MaterialityRule`, `MaterialityConfig`, `MaterialityAssessment`) | Every domain object validates at construction |
| **Tool contracts** | `shared/utils/tools/tool_result.py` (`ToolResult`) | Immutable `BaseModel` with frozen config |
| **Policy decisions** | `shared/utils/policy.py` (`PolicyDecision`) | Structured output with typed fields |
| **LLM structured outputs** | Pydantic models define the schema for LLM responses via `response_model` | The LLM client enforces structural compliance |
| **Configuration** | `shared/config/config.py` (Pydantic `Settings`) | Environment variable loading and validation |
| **Database ORM** | `shared/models/database.py` (SQLAlchemy `DeclarativeBase`) | SQLAlchemy models are separate — Pydantic is used at the API boundary for serialisation |

### Banned Patterns

The following patterns are **not allowed** anywhere in the codebase:

```
❌ Any - never use Any as a type annotation
❌ dict - never use bare dict without a TypeAlias or TypedDict
❌ raw JSON parsing - never use json.loads() on untrusted data
❌ dataclass for boundary types - dataclass is allowed only for purely internal implementation details
❌ NamedTuple - never use NamedTuple
❌ TypedDict for value objects - TypedDict is allowed only for PipelineState (LangGraph requirement)
```

### Monetary Value Enforcement

The `MoneyDecimal` type alias in `apps/api/schemas.py` demonstrates the pattern:

```python
from decimal import Decimal
from pydantic import field_validator
from typing import TypeAlias

# Fields use Decimal
# Field validators reject float at the API boundary
```

Every Pydantic model that contains a monetary field **must** include a `field_validator` that rejects `float`:

```python
@field_validator("amount", mode="before")
@classmethod
def reject_float(cls, v: object) -> object:
    if isinstance(v, float):
        raise ValueError("Float values not allowed for monetary fields")
    return v
```

## Consequences

### Positive

- **Type safety at every boundary.** If it crosses a layer, it's validated. Invalid data is caught at the edge, not in the middle of computation.
- **No more float leakage.** The `field_validator` on monetary fields creates a hard `float` rejection barrier. A `float` entering the API, a tool result, or a domain model is immediately rejected.
- **LLM structural compliance.** The LLM client uses `response_model` to force LLM outputs into Pydantic schemas. Malformed responses trigger retries, not silent data corruption.
- **Serialisation for free.** Every `BaseModel` has `.model_dump()` and `.model_dump_json()`. The custom `DecimalEncoder` is eliminated.
- **Documentation from types.** FastAPI generates OpenAPI docs from Pydantic schemas. The type annotations serve as living documentation.
- **mypy strict mode compatibility.** Pydantic v2 works well with `mypy --strict`. Generic types, `Optional`, and `Union` are all supported.

### Negative

- **Boilerplate for simple types.** Even a two-field struct requires a full `BaseModel` class definition with type annotations.
- **Performance overhead.** Pydantic validation has a cost — especially for deeply nested models. Mitigated by using `model_validate()` for bulk operations and avoiding validation in hot loops.
- **Migration cost for new team members.** Developers accustomed to `dict`-based Python need to learn Pydantic patterns.
- **Third-party integration friction.** Some libraries expect bare dicts. Mitigated by adding `.model_dump()` calls at integration boundaries.

## Compliance

1. **`mypy --strict` passes on every PR.** No `Any`, no untyped dicts, no `json.loads()` — these would cause type-check failures.
2. **Every monetary field has a `reject_float` validator.** Code review checklist item. Linting rule under consideration for `ruff`.
3. **LLM response parsing uses `response_model`.** No regex parsing of LLM output for structured data. The only regex allowed is in `claim_validator.py` for post-rendering commentary validation (which is a secondary cross-check, not a primary parsing path).
4. **No `dataclass` in `shared/models/` or `apps/api/schemas.py`.** Dataclasses are confined to implementation details within `finance/driver_engine/bridge_analysis.py` where the `@dataclass` is used for `BridgeDecomposition` and `BridgeAnalysis` (internal computational types that never cross a boundary).
5. **Schema generation is explicit.** Every Pydantic model used at an API boundary must be listed in `apps/api/schemas.py`. No implicit schema generation.
