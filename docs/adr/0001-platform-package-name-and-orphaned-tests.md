# ADR-0001: Platform Package Name and Orphaned Tests

**Status:** Accepted  
**Date:** 2026-08-01  
**Deciders:** Architecture Team (architect-agent; driven by contextscout read-only audit)  

---

## Context

The FinSight repo is a Python finance platform (FastAPI + SQLAlchemy + Next.js frontend). Plan v3 (`docs/14-platform/implementation-plan.md`) introduces a Layer-0 package for shared multi-tenant SaaS infrastructure (identity, rbac, abac, config, policies, registries, connectors, dispatcher, audit, observability).

A read-only audit (contextscout) found two **critical blockers** that every other build stream depends on:

1. **`platform` shadows the Python stdlib module.** A Layer-0 package was scaffolded at repo root as `platform/`, whose `__init__.py` was a prototype shim that exec'd the stdlib `platform.py` via `importlib` with four debug `print()`s. Because the repo root is on `sys.path` (see `tests/conftest.py`), `import platform` resolves to the repo's `platform/` package instead of the stdlib module. This breaks the `uuid → platform.system` import chain and `uv run python -m pytest` at bootstrap (collection aborts with `ModuleNotFoundError`/import failure).
2. **`tests/backend/` imports a nonexistent `backend.*` package.** The entire `tests/backend/**` tree (41 files: 34 test modules + 7 `__init__.py` markers under `agents/`, `api/`, `models/`, `tools/`, `data/`, `engine/`, `validators/`, `services/`) imports a `backend.*` package that has no corresponding source package in the repo. This makes `uv run python -m pytest` abort collection with `ModuleNotFoundError`. No live code (`apps/`, `agents/`, `finance/`, `shared/`, `business/`, `python_runtime/`, `tests/unit/`, `tests/integration/`, `tests/test_python_runtime/`) imports `tests.backend` or `backend.` — the subtree is fully orphaned. It is superseded by `tests/unit/`, `tests/integration/`, `tests/test_python_runtime/`, and `business/tests/`.

A third, non-blocking alignment issue surfaced in the same audit: the de-facto RLS session variable in every executable SQL file is `app.tenant_id` (`database/migrations/001_extensions.sql:12`, `006_rls.sql:46-183`, `007_audit_triggers.sql:41`), while `docs/12-database/rls.md:20` and plan v3 still refer to a `current_tenant_id` session variable.

## Decision

### Decision 1 — Layer-0 package is named `finplatform/`, NOT `platform/`

The Layer-0 package lives at repo root as **`finplatform/`** (sub-packages: `identity`, `rbac`, `abac`, `config`, `policies`, `registries`, `connectors`, `dispatcher`, `audit`, `observability`).

Rationale: a top-level package named `platform` shadows the Python stdlib `platform` module whenever the repo root is on `sys.path`, breaking `import platform` (the `uuid → platform.system` chain) and therefore `python -m pytest` at bootstrap. Renaming to `finplatform/` eliminates the collision entirely. The prototype shim (`platform/__init__.py` with importlib re-export + debug `print()`s) is deleted; the new `finplatform/__init__.py` contains only a docstring — no re-exports, no shim. Scratch artifact `tests/unit/test_platform/test_scratch_import.py` (which imported `platform.abac`) is removed; `tests/unit/test_platform/__init__.py` is kept for future tests.

Verification (must pass):

```bash
uv run python -c "import platform; print(platform.__file__)"        # STDLIB path
uv run python -c "import finplatform; print(finplatform.__file__)"  # repo finplatform/
uv run python -m pytest tests/unit/api/test_decimal_layer.py -q      # pass, no bootstrap crash
uv run pytest tests/unit/api/test_decimal_layer.py -q                # pass
uv run ruff check finplatform/ --fix                                 # clean
```

### Decision 2 — Delete the orphaned `tests/backend/` subtree

The `tests/backend/` subtree (41 files: 34 test modules + 7 `__init__.py` markers) is deleted via `git rm -r tests/backend`. It imports a `backend.*` package that does not exist and nothing in live code imports it back — it is fully orphaned and only aborts pytest collection with `ModuleNotFoundError`. The covered areas are superseded by `tests/unit/`, `tests/integration/`, `tests/test_python_runtime/`, and `business/tests/`.

Verification (must pass):

```bash
uv run python -m pytest --collect-only -q   # completes collection without ModuleNotFoundError
```

### Decision 3 — RLS session variable stays `app.tenant_id`; unification is a Phase-1 item

No SQL changes in this pass. The de-facto session variable everywhere in executable SQL is `app.tenant_id` (`001_extensions.sql`, `006_rls.sql`, `007_audit_triggers.sql`) — the code and `docs/12-database/rls.md` (SQL examples) already agree on it. The one stale prose line in `docs/12-database/rls.md:20` that said "will use a `current_tenant_id` session variable" is aligned to `app.tenant_id`. Plan v3's Phase-1/decision-table mention of `app.current_tenant_id` is left as-is (it is the future unify step) with a note: "(current codebase de-facto uses `app.tenant_id`; unify scheduled in Phase 1)". Also recorded in plan v3: the repo runs Next.js 16.2.10 (`frontend/package.json`) while the locked-stack table targets Next 15 — noted as "(repo currently on 16.2.10, lock remains 15 target)".

## Consequences

### Positive

- **Unblocks the test bootstrap.** `import platform` resolves to stdlib again; `uv run python -m pytest` no longer crashes at collection, unblocking every build stream that depends on the test suite.
- **No stdlib shadowing foot-gun.** Future code can safely `import platform` (used by `uuid`, `sysconfig` consumers, etc.).
- **Dead weight removed.** 41 files importing a nonexistent package are gone; no live code referenced them.
- **Docs match executable reality.** RLS prose, plan-v3 package references, and the locked-stack table now match the code and the repo.
- **ADRs/OpenSpec conventions honored.** The rename and deletions are recorded for future streams.

### Negative

- **History churn.** The package rename (from the short-lived `platform/` scaffold) and subtree deletion churn git history; the move is recorded with `git mv` to preserve history where applicable.
- **Future RLS rename cost.** When `app.current_tenant_id` unification lands in Phase 1, every RLS policy and `set_config`/`current_setting` call site must be updated in lockstep with the migrations — the cost is deferred by this decision.
- **Plan-v3 text carries a temporary inconsistency.** Phase-1 text still says `app.current_tenant_id` (with an explicit note that the code uses `app.tenant_id` today), so readers see both names until unification.

## Compliance

1. `finplatform/__init__.py` contains only a docstring — no re-exports, no importlib shim, no `print()`.
2. No live code imports `tests.backend` or `backend.` (grep-verified across `apps/`, `agents/`, `finance/`, `shared/`, `business/`, `python_runtime/`, `tests/unit/`, `tests/integration/`, `tests/test_python_runtime/`).
3. No `database/migrations/*.sql` content was changed.
4. Doc references to the package use `finplatform/`; general prose uses of "the platform" are untouched.

**References:** Plan v3 — `docs/14-platform/implementation-plan.md`; contextscout read-only audit findings; RLS doc — `docs/12-database/rls.md`; migrations — `database/migrations/001_extensions.sql`, `006_rls.sql`, `007_audit_triggers.sql`.
