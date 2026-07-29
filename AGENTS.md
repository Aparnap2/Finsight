<!-- OPENSPEC:START -->
# OpenSpec Instructions

These instructions are for AI assistants working in this project.

Always open `@/openspec/AGENTS.md` when the request:
- Mentions planning or proposals (words like proposal, spec, change, plan)
- Introduces new capabilities, breaking changes, architecture shifts, or big performance/security work
- Sounds ambiguous and you need the authoritative spec before coding

Use `@/openspec/AGENTS.md` to learn:
- How to create and apply change proposals
- Spec format and conventions
- Project structure and guidelines

Keep this managed block so 'openspec update' can refresh the instructions.
<!-- OPENSPEC:END -->

# FinSight Coding Agent Instructions

Operating instructions for the coding agent working on this FP&A cognitive runtime.

## Architecture Boundaries

This project uses a strict layered architecture. Violations cause review rejection.

```
apps/          → Web layer (FastAPI routes, WebSockets, serializers)
agents/        → AI orchestration (LangGraph pipelines)
finance/       → Domain logic (engines, formulae, validation, assertions)
shared/        → Cross-cutting utilities (config, models, LLM client)
tests/         → All tests, mirrored structure
```

**Dependency flow (one direction only):**
`shared` ← `finance` ← `agents` ← `apps`

Cardinal rules:
- `shared/` imports NOTHING from `apps/`, `agents/`, or `finance/`
- `finance/` imports NOTHING from `apps/` or `agents/`
- `agents/` imports NOTHING from `apps/`
- `apps/` may import from all layers below it

## Platform Stack (5 Orthogonal Ops Layers)

Beyond the code layers, think of the platform as 5 Ops disciplines:

| Layer | Role | Key Docs |
|-------|------|----------|
| **AgentOps** | Orchestration — decides WHAT agents do | `docs/09-platform/agentops.md` |
| **LLMOps** | LLM boundary — prompt registry, structured output, guardrails | `docs/09-platform/llmops.md` |
| **MLOps** | Inference Registry, RiskProvider protocol, CPU-first | `docs/09-platform/mlops.md` |
| **DataOps** | Data quality, Pandera + Pydantic, evidence lineage | `docs/09-platform/dataops.md` |
| **DevSecOps** | CI/CD gates, degraded mode, recovery | `docs/09-platform/devsecops.md` |

The Node.js backend (Next.js) orchestrates but NEVER manipulates dataframes — the **Python Compute Runtime** owns all validation, analytics, ML, exports.

## Before Editing — Investigation Workflow

1. **Read** the file to be edited first
2. **Grep** for related patterns across the codebase — naming, imports, conventions
3. **Check** neighboring files for style/pattern reference
4. **Verify** dependencies (imports, pyproject.toml, package.json) before introducing new libraries
5. **Only then** edit

## Coding Rules

- **Monetary values**: Must use `decimal.Decimal` — never `float`. The `MoneyDecimal` type alias is in `apps/api/schemas.py`
- **Imports**: stdlib → third-party → `shared` → `finance` → `agents` → `apps`
- **Naming**: modules `snake_case`, classes `PascalCase`, functions `snake_case`, constants `UPPER_SNAKE_CASE`
- **Docstrings**: Every module, public class, and public function
- **No print()**: Use `logging` instead
- **No secrets**: Never log or commit credentials

## Verification Gates

Run in order before every commit:

```bash
uv run ruff check .         # Lint (100-char line limit)
uv run mypy .               # Type-check (strict mode)
python -m pytest            # All tests
```

Confirm all pass before submitting.

## Tool Selection

| Task | Tool |
|------|------|
| Find files by pattern | Glob |
| Search code content | Grep |
| Read specific files | Read |
| Explore unknown scope | Task (with `research` or `general` subagent) |
| Write new files | Write (only when explicitly needed) |
| Edit existing files | Edit (preferred over Write) |
| External library docs | Context7 MCP (`resolve-library-id` → `context7_query-docs`) |
| Web research | WebSearch |

## Key Reference Files

- `CONTRIBUTING.md` — Full coding standards, folder architecture, PR checklist
- `openspec/AGENTS.md` — Spec-driven development workflow
- `openspec/project.md` — Project conventions and evidence
- `openspec/evaluation.md` — Evaluation impact template for AI-system changes
- `docs/09-platform/*.md` — Detailed platform layer documentation
