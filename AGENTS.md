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

## Scope Philosophy

**Build a production-quality portfolio application, not an enterprise-ready SaaS
platform.** Complete one workflow end to end; make financial behavior correct
and explainable; make failures predictable and recoverable; make the code
understandable and maintainable; demonstrate security boundaries honestly;
document what is deliberately not implemented.

### Feature categories

| Category | Treatment |
|---|---|
| Essential | Must implement before portfolio release |
| Risk-dependent | Implement only when the actual architecture or threat model requires it |
| Enterprise-grade | Explicitly out of scope unless justified |

### Before adding any feature, answer

1. Does the defined workflow actually need it?
2. What concrete failure or risk does it prevent?
3. Can an existing component already handle it?
4. Is there a simpler implementation?
5. Can we defer it without compromising financial correctness or security?

If the answer to the first two is weak, do not build it.

### Minimum security and reliability baseline

Tenant isolation, financial precision, and auditability are non-negotiable even
for a portfolio project when the application claims to support multiple
tenants. But an enterprise IAM platform is not required to demonstrate them.

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

## Testing Standard (Anti-Slop)

Tests must independently establish product behavior, not merely confirm current implementation details. A passing test is not proof unless its assertions can detect representative incorrect behavior.

### Behavioral assertions
- Assert observable behavior and meaningful side effects: financial results, state transitions, persisted records, API responses, exception classifications, audit evidence, authorization outcomes.
- Avoid: private helper invocation assertions, internal call-order assertions without contractual reason, tests that merely assert successful execution, excessive mocking of the system under test.

### Independent expected outcomes
- Expected results must NOT be calculated using the production function under test or a duplicate of its implementation.
- Use: explicitly specified financial examples, independently derived mathematical invariants, trusted fixture values, metamorphic properties.
- Do not let tests reproduce an implementation bug as expected behavior.

### Input variation
- Test normal, boundary, invalid, missing, duplicate, and conflicting inputs.
- Use Hypothesis for meaningful financial properties (allocation conservation, permutation invariance, replay determinism).
- Do not generate random data merely to increase test counts.

### Metamorphic testing
- Verify behavior under transformations: permuting input order, adding unrelated records, replaying identical requests, repeating imports.
- Define which transformations preserve results and which change them.

### Mutation testing
- Identify representative defects in important business logic (wrong operator, omitted fee, duplicate allocation, missing refund, currency mismatch, premature settlement, tenant filter bypass).
- Verify the corresponding test fails for the correct reason.
- Record surviving mutations as testing gaps. Do not optimize for a percentage score without reviewing survivors.

### Test resilience
- Tests should survive behavior-preserving refactors (renaming variables/helpers, moving modules, changing internal data structures).
- Tests must fail when externally observable behavior or a financial invariant is violated.
- Do not couple tests to: local variable names, private function names, internal module layout, incidental call ordering, unordered collection ordering.

### Test review before deletion
1. Identify the behavior the test protects.
2. Determine whether the behavior is obsolete or still required.
3. Identify unrelated assertions in the same test.
4. Preserve useful assertions.
5. Remove only assertions that exclusively protect deleted functionality.

### Constraints
- Do not weaken existing financial assertions.
- Do not regenerate golden evidence to make tests pass.
- Do not inflate test counts.
- Do not add dependencies without justification.
- Do not introduce flaky random tests.
- Do not treat coverage as proof of correctness.

### Required report per slice
- Behavioral assertions added, modified, removed.
- Expected outcomes and their independent source.
- Input variation and boundary cases.
- Metamorphic properties tested.
- Mutations attempted and killed.
- Surviving mutations.
- Tests dependent on internal implementation details.
- Test-count change with explanation.

## Evidence-Gated Response Protocol (EGRP)

EGRP is an engineering standard, not a separate specification document. It governs
every factual claim an agent or developer makes about this repository.

### Mandatory rules

1. **Provenance.** Every financial, security, or CI claim must trace to source
   evidence: an exact commit SHA, file at that SHA, CI run and job conclusion, or
   database/execution result. No evidence record means no factual assertion.
2. **No stale evidence.** For GitHub reviews, fetch the current PR head, base SHA,
   actual diff, CI runs for that exact head, individual job conclusions, and PR
   merge state. A green run on an older commit does not prove the current commit
   passes.
3. **Abstention.** Missing or ambiguous evidence produces an explicit unresolved
   result (`UNKNOWN`, `INSUFFICIENT_EVIDENCE`), never an invented answer.
4. **Determinism is authoritative.** LLM output cannot alter reconciliation
   outcomes, authorization decisions, or financial results.
5. **Tests challenge behavior.** Tests must detect representative incorrect
   behavior, not merely confirm expected behavior. Universal negatives
   ("no defects", "all tests pass") require the inspection scope to be stated.
6. **Independent verification.** Critical financial and security boundaries
   require two different verification mechanisms (for example, database
   constraints plus cross-tenant integration tests). A second LLM agreeing with
   the first is not independent proof.

### Claim categories

Use four explicit categories and never promote one to another silently:

- **Verified** — directly established through evidence.
- **Derived** — logical conclusion from verified evidence.
- **User-reported** — supplied by the user, not independently checked.
- **Unverified** — not established.

### Action evidence

A tool invocation is not proof of successful execution. Never claim a PR is
approved because a review comment was posted, merged because it is mergeable, a
deployment completed because a workflow started, or a file exists because its path
appeared in generated text.

### Formal versioning

EGRP stays an engineering standard. A separate H0 specification is introduced
only if the protocol becomes a separately consumed contract.

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

## Linear Workflow (Solo-Agent Engineering Loop)

Linear, GitHub, and OpenCode each own exactly one authority. Never blur them.

| System | Authority |
|--------|-----------|
| **Linear** | What we're building and why (slice, contract, acceptance, status) |
| **GitHub** | What actually changed and was reviewed (diff, CI, merge) |
| **OpenCode** | Implementation executor (this agent) |

Rules:
- **Neither Linear nor any LLM declares code correct.** Only GitHub/CI + human review does.
- **Linear stays lean.** Each issue answers: slice, why, contract link, acceptance criteria, dependencies, status, outcome. Detailed artifacts live in the repo, never in Linear.
- **Pull before building.** At slice start, read the Linear issue (`linear_get_issue`) for contract + acceptance; the repo spec doc remains the normative technical source if they ever disagree — flag the divergence instead of guessing.
- **Update after merging.** Move the issue through Todo → In Progress → In Review → Done with this audit trail: contract commit, implementation commit(s), PR URL, merge commit, test gate numbers, important adjudications, known pre-existing failures, next dependency.
- **Update without being asked.** Every slice moves Linear on its own: pull the issue at slice start and set status to reality; post lean progress comments at milestones (contract done / engine done / PR open); full audit-trail comment at merge → Done.
- **Done means pushed.** Never report a branch/commit as done while it exists only locally. Every slice report states remote state explicitly (branch + SHA resolvable on GitHub). Push first, then report.
- **Workspace facts.** Project `FinSight`, team key `APA`. Statuses `Todo/In Progress/In Review/Done` exist — use them, don't invent states.
- **History backfill** (P6-01 → P6-05 slices as Linear issues) is the human's cleanup pass, not this agent's job unless explicitly asked.

## PR Creation Checklist (GitHub Boxes)

Fill every box at creation time, not after:
- **Assignees:** `@Aparnap2`
- **Reviewers:** request review per standing instruction (CodeRabbit auto-reviews; add human reviewer when asked)
- **Labels:** apply the repo's workstream label for the slice
- **Projects:** add to the FinSight project board
- **Milestone:** set the active milestone when one exists
- **Development:** link the Linear issue (e.g. `APA-5`) in the PR body so merge state syncs
