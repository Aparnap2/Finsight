# PRIVACY_BOUNDARY.md (P10-02 / P10-03)

Runtime privacy enforcement for model-facing and operator-facing
surfaces. Label: hardened, not compliant. Source of truth is code;
this document describes it.

## Surfaces and contracts

### `sanitize_for_log()` — strongest minimization (`shared/privacy/sanitize.py`)

PII becomes tenant-scoped irreversible hash tokens; secrets become
`[REDACTED_SECRET]`; financial values become `[FINANCIAL_SENSITIVE]`;
bodies/snippets become `[REDACTED]`; control characters collapse.
Test: `tests/unit/privacy/test_sanitize_contract.py`.

### `sanitize_for_llm()` — minimum necessary context

Evidence text kept, scrubbed inline, bounded to 500 chars; secret
shapes redacted even inside text; financial values preserved exactly
(Decimal fidelity, no coercion) when explicitly classified.
Test: `tests/unit/privacy/test_sanitize_contract.py`.

### `sanitize_for_eval()` — deterministic canonical form

Same transforms as `sanitize_for_llm()` with keys sorted. Determinism
is asserted by re-application equality.
Test: `tests/unit/privacy/test_sanitize_contract.py`.

### `sanitize_for_ui()` — operator display masks

Emails `r***@domain`, phones keep-first-3/last-4, accounts keep last 4,
names keep first character. Control characters flattened.
Test: `tests/unit/privacy/test_sanitize_contract.py`.

### `authorize_llm_context()` — purpose gate (`shared/privacy/boundary.py`)

Entry to every provider-bound prompt. Secrets (explicit or pattern)
and unclassified non-structural values raise `PolicyDeniedError`;
PERSONAL atomic values become tenant tokens, PERSONAL free text is
scrubbed inline; FINANCIAL_SENSITIVE passes only for commentary,
root-cause, and reasoning purposes; tenant mismatch raises; blank
tenant and unknown purpose raise `ValueError`. Injection text is inert
by construction (authorization is structural, never instructed).
Tests: `tests/unit/privacy/test_llm_boundary_contract.py`,
`tests/unit/privacy/test_llm_path_wiring.py`.

## Integration points (all five route through the gate)

- `agents/investigation/planner.py` (purpose INVESTIGATION, tenant from
  request; free-text window scrubbed)
- `agents/commentary/commentary_agent.py` (purpose COMMENTARY)
- `agents/driver/root_cause_agent.py` (purpose ROOT_CAUSE)
- `finance/reasoning/llm_boundary.py` (purpose REASONING)
- `finance/workflows/workflow.py` (purpose WORKFLOW, financial denied)
- `agents/reasoning/orchestrator.py` threads tenant into the provider

## Tenant boundary

Identity is `(tenant_id, key)` on execution and idempotency ledgers;
`execution_id` derives from both. Token scope is per tenant: the same
email under two tenants yields different, unlinkable tokens. Actor and
tenant survive sanitization for accountability; everything else
 identifying is transformed.

## PII and secrets handling

Secrets never reach prompts (deny, not redact-and-continue at the
gate). Secret-shaped values in logs/traces become `[REDACTED_SECRET]`;
emails become tokens (logs/LLM/eval) or masks (UI). Existing
primitives reused, not reinvented: `hash_pii`, `redact_mapping`,
`tracing/redaction.py` (untouched, P10-04 foundation).

## Status: Implemented

All behaviors above are executable specifications in the cited tests.
No token vault exists (ratified P10-01 decision); correlation uses
irreversible tenant-scoped hashes.
