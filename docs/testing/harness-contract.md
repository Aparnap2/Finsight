# Harness Contract — `ReasoningHarness`

Normative contract for `finance/cognition/harness.py`, locked by
`tests/unit/test_finance/test_cognition_harness.py::TestReasoningHarnessIntegrity`.

## Result shape

`HarnessResult` carries `state`, `run_id`, `success`, `stop_reason`,
`state_fingerprint`. `success` is `True` **only** when `stop_reason` is
`"finalize"`.

## Stop reasons (closed vocabulary)

| `stop_reason` | `success` | Meaning |
|---|---|---|
| `finalize` | `True` | A node set `loop_decision == "finalize"` |
| `max_iterations_exhausted` | `False` | Iteration cap hit with no finalize |
| `missing_node` | `False` | Pipeline names a node absent from the registry |
| `node_error` | `False` | A node's `execute` raised; the exception does not propagate |

Rules: a skipped node never silently passes; exhaustion never reports
success; a node exception is captured as `node_error`, not a traceback;
telemetry is still captured on failure paths.

## State fingerprint

`state_fingerprint` is the first 16 hex chars of SHA-256 over canonical
JSON (`sort_keys=True`) of query, context, iteration count, loop decision,
and overall confidence. Identical states fingerprint identically;
any change alters it. It is an integrity observable, not a clock.

## Determinism notes

`run_id` (uuid4) and step `duration_ms` (wall clock) remain
non-deterministic by design and are excluded from the fingerprint.
Production behavior depending on real clock semantics was deliberately
not frozen; only the outcome contract above is pinned.
