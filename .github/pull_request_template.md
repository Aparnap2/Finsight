## What changed

<!-- One or two sentences. Link the contract or issue when one exists. -->

## Verification scope

The `PR verification` workflow reads the JSON array between the markers below.
It must list path prefixes (or globs) that cover **every** changed file. The
workflow fails closed when the block is missing, empty, malformed, or does not
cover the diff.

Replace `[]` before opening the pull request. Example for a finance change plus
its tests:

```json
["finance/", "tests/unit/finance/"]
```

<!-- verification-scope:start -->
[]
<!-- verification-scope:end -->

## Risk classification

The workflow derives the risk class from the changed paths. You do not choose
it. For reference:

| Risk class | Typical paths | Extra gates | Human review |
| --- | --- | --- | --- |
| `docs` | `docs/`, `*.md`, `openspec/` | baseline only | automatic |
| `tests-only` | `tests/` | baseline only | automatic |
| `apps-web` | `apps/` | postgres integration | automatic |
| `finance-domain` | `finance/`, `shared/`, `agents/` | postgres + golden dataset | automatic |
| `execution` | `finance/execution/`, `finance/accounting/` | postgres + LocalStack S3 + golden dataset | automatic |
| `migrations` | `alembic/`, `migrations/` | postgres integration | required |
| `dependencies` | lockfiles, `pyproject.toml`, `package.json` | all gates | required |
| `ci-infra` | `.github/`, `scripts/`, build config | all gates | required |
| `security-authz` | auth, permissions, tenancy | all gates | required |
| `unknown` | anything not matched above | fail closed | required |

The baseline gate is `lint / typecheck / unit+contract`. Changing
`.github/verification-policy.json` after bootstrap requires the `policy-change`
label.

## Human approval boundary

For `dependencies`, `migrations`, `ci-infra`, `security-authz`, and `unknown`,
record the required review here (dependency/CVE review, migration and rollback
plan, CI-owner review, or security-owner review). The workflow requires one
non-author approval at the head commit.

## Test results

<!-- Paste raw local gate output, not a summary. -->

```text
ruff check .
ruff format --check .
mypy .
pytest
```

## Unresolved issues / edge cases

- None.

## Links

<!-- Closes #123 or the tracker link. -->
