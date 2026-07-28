# Contributing to FinSight

## Coding Standards

### Python Style
- Target Python 3.12+.
- Follow [PEP 8](https://peps.python.org/pep-0008/) with a 100-character line limit.
- Lint with `ruff` (configured in `pyproject.toml`). Run before every commit:
  ```bash
  uv run ruff check .
  ```
- Type-check with `mypy` in strict mode. All public functions and methods **must** have type annotations:
  ```bash
  uv run mypy .
  ```

### Monetary Values
- **All monetary values use `decimal.Decimal` — never `float`.**
- The `MoneyDecimal` type alias (`apps/api/schemas.py`) rejects floats at the Pydantic boundary.
- Mathematical operations on monetary values must use `Decimal` arithmetic.

### Imports
- Standard library → third-party → internal (`shared` → `finance` → `agents` → `apps`).
- Use absolute imports within the project.

### Naming
- **Modules**: `snake_case` (e.g., `formula_registry.py`, `root_cause_agent.py`).
- **Classes**: `PascalCase`.
- **Functions/methods**: `snake_case`.
- **Constants**: `UPPER_SNAKE_CASE`.
- **Private/internal**: prefixed with `_`.

### Documentation
- Every module must have a docstring explaining its purpose.
- Every public class, function, and method must have a docstring.
- Complex business logic requires inline comments explaining the "why" (not the "what").

---

## Folder Architecture & Dependency Rules

The project follows a strict layered architecture. Violating these rules will fail review.

```
apps/          → Web layer (FastAPI routes, WebSockets, serializers)
agents/        → AI orchestration (LangGraph pipelines)
finance/       → Domain logic (engines, formulae, validation, assertions)
shared/        → Cross-cutting utilities (config, models, validators, LLM client)
tests/         → All tests, mirrored structure
```

### Dependency Flow (ONE DIRECTION ONLY)

```
apps  →  agents  →  finance  →  shared
        agents/finance  →  shared
```

### Cardinal Rules

| Rule | Description |
|------|-------------|
| **`shared/` NEVER imports from `apps/`, `agents/`, or `finance/`** | Shared is the foundation layer. Circular imports will break the build. |
| **`finance/` NEVER imports from `apps/` or `agents/`** | Domain logic must be independent of web and AI orchestration concerns. |
| **`agents/` NEVER imports from `apps/`** | Agents orchestrate domain and shared — never the web layer. |
| **`apps/` may import from all layers** | The API layer depends on everything below it. |

### What Lives Where

| Folder | Responsibility |
|--------|---------------|
| `apps/api/` | FastAPI routes, request/response schemas, serializers, WebSocket handlers. |
| `apps/frontend/` | Frontend application (if applicable). |
| `agents/` | LangGraph state machine, agent nodes (commentary, variance, root cause, scenario). |
| `finance/` | All financial domain logic — formula engine, KPI engine, variance engine, scenario engine, forecast engine, driver engine, recommendation engine, validation, assertion pipeline, ingestion. |
| `shared/` | Config, base models (database, assertions, state), utilities (LLM client, confidence, tools, validators), shared prompts and schemas. |
| `tests/` | Tests mirroring the source structure — unit, integration, agent, e2e. |

---

## Dependency Rules (Python Packages)

- `shared/` has zero internal dependencies beyond the standard library and third-party packages.
- `finance/` depends on `shared/` only.
- `agents/` depends on `finance/` and `shared/`.
- `apps/` depends on `agents/`, `finance/`, and `shared/`.

Adding a new dependency to `pyproject.toml` requires team consensus. Prefer standard library solutions where practical.

---

## Pull Request Checklist

Before submitting a PR, verify:

- [ ] Code passes `ruff check .` with no warnings.
- [ ] Code passes `mypy .` with no errors.
- [ ] All existing tests pass (`python -m pytest`).
- [ ] New code has corresponding tests (unit or integration as appropriate).
- [ ] Monetary values use `Decimal`, not `float`.
- [ ] No `print()` statements remain (use `logging` instead).
- [ ] Docstrings added for all new modules, classes, and public functions.
- [ ] No secrets, keys, or credentials in code or committed files.
- [ ] Imports follow the layered dependency rules (no reverse imports).
- [ ] Branch is rebased on latest `main`.
- [ ] PR title follows Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, etc.).

---

## Code Review Checklist

Reviewers must verify:

1. **Correctness**: Does the logic produce the right result for all edge cases?
2. **Type safety**: Are all types correct? Is `Decimal` used for money? Are Optional fields handled?
3. **Layered architecture**: No reverse imports or layer violations.
4. **Test coverage**: Are there unit tests for new logic? Integration tests for pipelines?
5. **Error handling**: Are errors caught and reported gracefully? Are degraded modes handled?
6. **Security**: No secrets, no injection vectors, no excessive logging of sensitive data.
7. **Performance**: Are database queries efficient? Are LLM calls minimized where deterministic logic suffices?
8. **Documentation**: Are new concepts, schemas, or workflows documented?

---

## Testing Checklist

- [ ] Tests are added alongside new code (same PR, same branch).
- [ ] Unit tests cover pure logic: formulas, validation rules, materiality calculations, date arithmetic.
- [ ] Integration tests cover pipelines and agent orchestration against test databases.
- [ ] Golden dataset tests pass before and after changes (regression protection).
- [ ] LLM evaluation tests verify structured output compliance and hallucination rates.
- [ ] Edge cases are covered: zero values, negative variances, missing data, boundary thresholds.
- [ ] Tests are deterministic (no flaky tests depending on LLM nondeterminism — mock LLM calls).
- [ ] Test run: `python -m pytest` (not `pytest` directly — use the module invocation).

### Running Tests

```bash
# Run all tests
python -m pytest

# Run with coverage
python -m pytest --cov=finance --cov=agents --cov=apps --cov=shared

# Run specific test file
python -m pytest tests/unit/test_finance/test_formula_engine.py

# Run integration tests only
python -m pytest tests/integration/

# Run agent tests (mocked LLM)
python -m pytest tests/backend/agents/
```

There are currently **83 tests** in the test suite (unit, integration, and agent tests combined).

---

## Commit Conventions

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add revenue growth rate KPI to formula engine
fix: correct fiscal period overlap detection for Q4
docs: add testing strategy documentation
refactor: extract monetary validation into shared validator
test: add edge case tests for zero-budget variance
chore: update ruff configuration
```

---

## Development Workflow

1. **Create a branch** from `main`: `git checkout -b feat/my-feature`.
2. **Write tests first** (where practical) following test-driven development.
3. **Implement** the feature.
4. **Run the full test suite**: `python -m pytest`.
5. **Lint and type-check**: `ruff check . && mypy .`.
6. **Commit** using conventional commit format.
7. **Push and open a PR** against `main`.
8. **Address review feedback** with additional commits (squash before merge).
