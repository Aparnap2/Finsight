# LLM Evals (Manual / Controlled Only)

LLM evaluations live here eventually. They are **manual and controlled** —
never part of the dev loop, never run by unit/integration/e2e suites.

- No eval code exists here yet (stub only).
- Real LLM calls require explicit human approval, API keys, and a call
  budget; results are recorded, never asserted in CI.
- See `pyproject.toml` (`llm` marker) and `tests/llm/` for the existing
  provider smoke tests, which remain separate.
