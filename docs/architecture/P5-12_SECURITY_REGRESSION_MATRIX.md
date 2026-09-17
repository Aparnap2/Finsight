# P5-12 Security Regression Matrix — Meridian Commerce

Golden dataset: **FS-2026-0916-00231** (₹10,000 legacy variance,
batch `LEGACY-20260916-0042`, 499/500 accepted, `INVALID_ACCOUNT_CODE 4812`).

## Boundaries × Controls

| # | Boundary (threat) | Control (mechanism) | Suite | Count |
|---|-------------------|---------------------|-------|-------|
| 1 | Tenant escape via evidence text | `build_context` tenant/case from trusted request only | tenant_isolation_matrix | 16 |
| 2 | Cross-tenant oracle (existence leak) | Uniform `unknown_evidence_id` | grounding_ladder | 3 |
| 3 | Uncited FACT / fabricated claim | Ladder: cite → exists → tenant → provenance → supported | grounding_ladder | 5 |
| 4 | VERIFIED stamp by LLM | Claim-classification never-markers + grounding | grounding_ladder | 3 |
| 5 | Confidence as authority (0.99) | Confidence caps; tier independent of confidence | grounding_ladder + verifier | 2 |
| 6 | Prompt injection × 8 attacks | UNTRUSTED_CONTENT fence, DATA-only | prompt_injection | 56 combos |
| 7 | Injection via tool results | ToolResult preserved with hash, no auto-invoke | prompt_injection | 2 |
| 8 | Injection as planning directive | Verifier rejects ungrounded ids | prompt_injection | 2 |
| 9 | Secret in audit row | `_audit` redact_mapping pre-persist | secret_leak | 1 |
| 10 | Secret in trace span | sanitize_input/args/output in tracers | secret_leak | 2 |
| 11 | Secret in logs | scrub_text before log emission | secret_leak | 1 |
| 12 | PII join across tenants | hash_pii tenant-scoped | secret_leak | 4 |
| 13 | Secret literal in repo | CI rg gate (sk_live/Bearer in prompts/traces/fixtures) | ci.yml | 1 |
| 14 | Trajectory leaks bodies | Ledger holds ids + codes only | harness | 13 |
| 15 | Live LLM in unit tests | FINSIGHT_ALLOW_LIVE_LLM gate + socket block fixtures | all suites | — |
| 16 | Golden FS-231 end-to-end | test_security_regression.py (all four layers, one flow) | regression | 7 |

## Regression rule

Suite-count pins in `test_security_regression.py` fail loudly on deletion.
Golden FS-231 must stay green: tenant-scoped, VERIFIED-eligible, fenced,
redacted. SQS stays closed; Postgres remains authority; S3 is transport.
