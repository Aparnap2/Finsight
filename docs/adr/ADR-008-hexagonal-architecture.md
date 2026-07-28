# ADR-008: Hexagonal (Clean) Architecture — Inward Dependency Rule

**Status:** Accepted  
**Date:** 2026-07-28  
**Deciders:** Architecture Team  

---

## Context

FinSight's codebase has four natural layers (`shared/`, `finance/`, `agents/`, `apps/`) but without enforced dependency direction, they can drift into circular imports, cross-layer coupling, and untestable modules.

The project established a layered architecture in `CONTRIBUTING.md` with strict dependency flow:

```
apps  →  agents  →  finance  →  shared
        agents/finance  →  shared
```

And cardinal rules:
- `shared/` NEVER imports from `apps/`, `agents/`, or `finance/`
- `finance/` NEVER imports from `apps/` or `agents/`
- `agents/` NEVER imports from `apps/`
- `apps/` may import from all layers

However, these rules were implicit and not structurally enforced. As the codebase grows, violations will increase without mechanical enforcement. We need to formalise the architecture and make violations detectable at build time.

## Decision

Adopt a **Hexagonal (Clean) Architecture** pattern with explicit ports and adapters, enforced by automated tooling.

### Layer Definitions

| Layer | Directory | Description | Depends On |
|-------|-----------|-------------|------------|
| **Domain** | `shared/` | Enterprise-wide concepts: base models, enums, interfaces, value objects | Nothing internal |
| **Application (Finance)** | `finance/` | Financial domain logic: formulas, KPIs, variances, validation, assertions | `shared/` only |
| **Application (Agents)** | `agents/` | Orchestration: LangGraph state machines, LLM interaction | `finance/`, `shared/` |
| **Infrastructure** | `apps/api/` | Web framework, routes, request/response schemas, WebSocket | `agents/`, `finance/`, `shared/` |
| **Infrastructure (Persistence)** | `shared/models/database.py` | SQLAlchemy ORM, migrations | `shared/` models only |
| **Infrastructure (LLM)** | `shared/utils/llm_client.py` | LiteLLM client | `shared/` only |
| **Infrastructure (Tools)** | `shared/utils/tools/` | External system contracts | `shared/` only |

### Dependency Direction (Inward Rule)

```
apps/api/  ──→  agents/  ──→  finance/  ──→  shared/
  │                       (read-only)         (no internal deps)
  └───────────────────────→  finance/  ──→  shared/
  └──────────────────────────────────────→  shared/
```

**Code in an outer layer may depend on code in an inner layer, but never the reverse.**

### Ports and Adapters Pattern

| Concept | Implementation |
|---------|---------------|
| **Port (interface)** | Defined as abstract `Protocol` or `ABC` in `shared/` or `finance/` |
| **Adapter (implementation)** | Lives in `apps/api/` or `shared/utils/tools/` |
| **Dependency injection** | Wired in `apps/api/main.py` (the composition root) |

### Enforcement Tooling

1. **`ruff` import rules.** The `pyproject.toml` configuration includes per-module import restrictions that prevent reverse imports:

```toml
[tool.ruff.lint.flake8-tidy-imports.banned-api]
"shared" = { "msg" = "shared/ must not import from apps/, agents/, or finance/" }

[tool.ruff.lint.per-file-ignores]
# Not on by default — requires explicit config
```

2. **`mypy` strict mode.** No circular imports allowed. `mypy` will detect and fail on circular dependencies between layers.

3. **Manual code review checklist.** The `CONTRIBUTING.md` PR checklist includes:
   - "Imports follow the layered dependency rules (no reverse imports)"

### What This Means for Development

**An `apps/api/routes.py` developer:**
- Can import from `agents/`, `finance/`, and `shared/`
- Cannot create new imports in `shared/` or `finance/`
- When needing a new data transformation, implements an adapter in `apps/api/` — not in `finance/`

**A `finance/` developer:**
- Can import from `shared/` only
- Never imports from `apps/` or `agents/`
- Designs pure domain logic that is independent of web frameworks or LLM providers

**A `shared/` developer:**
- Never imports from any internal package
- Designs foundational types used everywhere — enums, base models, validated types
- Changes to `shared/` have the widest blast radius and require careful review

### Concrete Examples of the Pattern

| Need | Where It Lives | Why |
|------|---------------|-----|
| Define an `Assertion` model | `shared/models/assertions.py` | Used by all layers — must be innermost |
| Implement materiality logic | `finance/variance_engine/materiality.py` | Domain logic — depends only on `shared/models/` |
| Create a root-cause agent | `agents/driver/root_cause_agent.py` | Orchestration — depends on `shared/` and `finance/` |
| Expose a REST endpoint | `apps/api/routes.py` | Infrastructure — wires everything together |
| Add a Google Sheets reader | `shared/utils/tools/` via `ToolResult` contract | Tool contract — depends on `shared/` only |

## Consequences

### Positive

- **Testability in isolation.** Each layer can be tested independently — `shared/` has zero internal deps, `finance/` tests mock nothing internal, `agents/` tests mock LLM only, `apps/` tests mock everything beneath.
- **Framework independence for domain logic.** `finance/` has no FastAPI, no SQLAlchemy, and no LangGraph dependency. It can be used from any framework.
- **LLM provider independence.** The `shared/utils/llm_client.py` abstraction means agents never import `openai` or `litellm` directly. Provider swaps don't cascade through the codebase.
- **Data source independence.** Persistence (`shared/models/database.py`) is separated from domain logic (`finance/`). ORM changes don't affect financial calculations.
- **Parallel development.** Teams working on `apps/`, `agents/`, `finance/`, and `shared/` can develop independently with minimal merge conflicts — as long as the public interfaces (Pydantic schemas) don't change.

### Negative

- **Boilerplate for simple operations.** Wiring a new feature through all four layers requires: domain model in `shared/`, logic in `finance/`, agent step in `agents/`, endpoint in `apps/`. Simple features have high setup cost.
- **Layer violation detection is manual.** `ruff` can enforce import bans, but conceptual violations (e.g., using a domain model as a database row) require code review.
- **Not pure hexagonal architecture.** True hexagonal architecture requires ports and adapters for every external dependency. We relax this for pragmatic reasons — SQLAlchemy and LiteLLM are sufficiently stable that abstracting behind ports for every call would be over-engineering.

## Compliance

1. **`ruff` blocks reverse imports.** A CI step runs `ruff check .` which includes `flake8-tidy-imports` rules to enforce per-layer import restrictions.
2. **`mypy --strict` passes on every PR.** Circular imports between layers cause `mypy` failures.
3. **Code review checks dependency direction.** Every PR is reviewed against the dependency rules in `CONTRIBUTING.md`. Reverse imports are blocked.
4. **`shared/` has zero internal imports.** Verified by grep: `grep -r "^from (apps|agents|finance)" shared/` must return empty.
5. **`apps/` is the only composition root.** Dependency injection and wiring happen in `apps/api/main.py`. No other module instantiates cross-layer collaborators.
