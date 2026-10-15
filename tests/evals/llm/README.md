# LLM Evals (Manual / Controlled Only)

LLM evaluations live here eventually. They are **manual and controlled** —
never part of the dev loop, never run by unit/integration/e2e suites.

- No live-LLM eval code runs in CI (stub job only, manual `workflow_dispatch`).
- Real LLM calls require explicit human approval, API keys, and a call
  budget; results are recorded, never asserted in CI.
- See `pyproject.toml` (`llm` marker) and `tests/llm/` for the existing
  provider smoke tests, which remain separate.

## Deterministic golden gate (CI, no providers)

The frozen golden regression set (`regression_forecast_naive`,
`regression_anomaly_materiality`, `regression_duplicate_rows`) runs on
push/PR via the `golden-dataset` job in `ai-evals.yml` using reference
engines — no network, no keys, no provider calls. It fails on any
regression AND on zero-datasets/zero-reports/empty-metrics, so a
missing eval can never read as green. Entry point:
`python -m finance.evaluation.runner`. The wider 25-dataset catalogue
includes adversarial sets (e.g. `currency_mismatch`) that reference
engines legitimately fail; only the frozen three gate releases.
