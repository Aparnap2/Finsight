# Staging E2E Verification

## Overview

Level 1 (connected CI E2E) runs on every PR via `integration.yml` using a fake LLM provider.
Level 2 (live staging E2E) is triggered manually via `staging-e2e.yml` with real provider APIs.

## Level 1: Connected CI E2E

- Workflow: `.github/workflows/integration.yml`
- Test: `tests/integration/test_connected_workflow.py`
- Golden scenarios: `tests/fixtures/reconciliation/golden_scenarios.json`
- Provider: FakeLLM (no network, no cost)
- Proves: import → validate → reconcile → persist → context → investigate → decide → audit → export

## Level 2: Live Staging E2E

- Workflow: `.github/workflows/staging-e2e.yml` (manual `workflow_dispatch`)
- Requires GitHub Environment "staging" with secrets:
  - `STAGING_DATABASE_URL`
  - `STAGING_LLM_API_KEY`
  - `STAGING_OTLP_ENDPOINT`
  - `STAGING_TENANT_ID`
  - `STAGING_API_BASE_URL`
- Provider: Real LLM API (sandbox/test credentials only)
- Proves: real provider integration, tracing export, deployed app, migrations

## Golden scenarios

Located in `tests/fixtures/reconciliation/golden_scenarios.json`. Expected values are
agent-observed and require human verification before being treated as authoritative.

## Security

- Only trusted branches and manual authorized runs access staging secrets.
- Dedicated staging DB and tenant; synthetic financial data only.
- Provider call count and timeout limits enforced.
- No secrets printed in logs.
