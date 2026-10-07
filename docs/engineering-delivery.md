# FIN-ENG-001: Engineering Delivery Standard

Every production-affecting change must be traceable:

```text
Linear (what + why) → GitHub Issue (technical contract) → branch
  → RED tests → implementation → atomic commits → PR (evidence)
  → CI (authority) → main → deployment → Notion (durable record)
```

No orphan production changes. The coding agent executes slices; it does
not declare them correct — GitHub/CI + human review do.

## Authority map

| System | Owns |
|---|---|
| Linear | Initiative / milestone / slice: objective, scope, acceptance, status |
| GitHub Issues | Implementation contract (goal, non-goals, artifacts, tests, gates) |
| GitHub PRs | Change + evidence + review discussion |
| GitHub Actions | Whether the change is acceptable (ruff, format, mypy ratchet, unit, contract, Postgres, MiniStack, secrets) |
| Git history | Exactly what changed (atomic, conventional commits) |
| Notion | Durable architecture, decisions, policies, runbooks |
| Coding agent | Executes the issue-defined slice, nothing more |

## Slice requirements

1. Linear work item with objective, scope, acceptance criteria, dependencies.
2. GitHub issue with the technical contract (template below).
3. Explicit acceptance criteria, including stop conditions.
4. Dedicated branch (`feat/…`, `fix/…`, `chore/…`, `docs/…`).
5. Tests before implementation where practical (RED → GREEN).
6. Atomic commits (conventional messages; test and implementation separate).
7. Pull request against `main` with evidence.
8. Required CI checks green (no merging red).
9. Security/migration impact stated explicitly (or "none" with reason).
10. Merge preserves history (merge commit for multi-commit slices).
11. Documentation updated when architecture, policy, or contracts change.
12. Linear status + outcome updated after merge.

## Agent operating loop

```text
READ ISSUE → inspect repo → RED tests → implement → local gates
  → atomic commits → push → PR → CI green (diagnose + fix until green)
  → merge (only when authorized) → update Linear → record docs
```

Local gates before every push: `uv run ruff check .`,
`uv run ruff format --check .`, scoped `pytest`, and the mypy ratchet
must not gain entries (`scripts/mypy_baseline_check.py`).

## Ceremony threshold

Full ceremony is required for changes to runtime behavior, financial
state, authorization, tenant boundaries, persistence, migrations, LLM
boundaries, security/privacy, or deployment. Typo fixes, comment-only
edits, and local tooling notes do not need a Linear item — use judgment
and say so in the PR.

## GitHub issue template

```text
Goal / Scope / Non-goals / Inputs / Expected artifacts /
Acceptance tests / Security requirements /
Migration requirements / CI requirements /
Evidence required / Stop conditions
```

## PR template

```text
## Summary / ## Linear (id) / ## GitHub Issue (id)
## Changes / ## Tests (unit, contract, integration, security)
## CI (ruff, format, mypy ratchet, secrets, Postgres, MiniStack)
## Security impact / ## Migration impact / ## Evidence
## Rollback / ## Acceptance criteria ([ ] ...)
```
