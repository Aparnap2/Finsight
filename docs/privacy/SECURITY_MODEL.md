# SECURITY_MODEL.md (P10)

What FinSight implements, with evidence. Status labels: Implemented /
Partially implemented / Not implemented. Language rule: controls are
"designed to support obligations" — this project claims no DPDP, GDPR,
UK GDPR, or PCI DSS compliance, certification, or legal opinion.

## Trust boundaries and data flow

```text
provider webhooks → HMAC verify → tenant resolve → idempotent persist
    → normalized records → deterministic controls → exception lifecycle
    → bounded cognition (LLM, advisory only) → validated output
    → policy/authorization → execution → verification → audit/close
```

LLM is advisory cognition; deterministic code is financial truth and
authority. Raw provider data may enter ingestion; raw personal data
does not automatically propagate downstream (see PRIVACY_BOUNDARY.md).

## Control matrix

| Control | Status | Evidence |
|---|---|---|
| Field data inventory (30 rows, 7 sources) | Implemented | `tests/unit/privacy/test_inventory_completeness.py` |
| Inventory↔doc synchronization | Implemented | `tests/unit/privacy/test_inventory_completeness.py` |
| Sanitizer surfaces (log/llm/eval/ui) | Implemented | `tests/unit/privacy/test_sanitize_contract.py` |
| LLM purpose gate + tenant threading (5 paths) | Implemented | `tests/unit/privacy/test_llm_boundary_contract.py`, `tests/unit/privacy/test_llm_path_wiring.py` |
| Atomic idempotency claims | Implemented | `tests/unit/security/test_idempotency_claim.py` |
| Execution/replay boundary | Implemented | `tests/unit/execution/test_execution_boundary.py` |
| Crash recovery without second mutation | Implemented | `tests/unit/execution/test_execution_failure_injection.py` |
| Tenant-scoped ledger + execution ids | Implemented | `tests/unit/execution/test_execution_boundary.py` |
| Persistence failure semantics | Implemented | `tests/unit/exceptions/test_repository_persistence_error.py` |
| Rollout leakage coverage (telemetry/audit/logs/errors/reads) | Implemented | `tests/unit/privacy/test_redaction_rollout.py`, `tests/integration/test_error_echo.py` |
| Adversarial qualification matrix | Implemented | `tests/unit/privacy/test_adversarial_marquee.py`, `tests/unit/privacy/test_boundary_enforcement.py` |
| Retention dispositions + expiry engine | Implemented | `tests/unit/privacy/test_retention.py`, `tests/unit/execution/test_expiry_recovery.py` |
| Incident lifecycle + runbooks | Implemented | `tests/unit/privacy/test_incidents.py` |
| DecisionResult abstention contract | Implemented | `tests/contract/test_p8_05_decision_result_red.py` |
| Observation API (read-only, tenant-scoped) | Implemented | `tests/integration/test_observations_api.py` |
| Incident registry persistence | Not implemented | Post-release; in-memory only by design (see `docs/privacy/INCIDENT_RESPONSE.md`) |
| Live-provider eval with real PII | Not implemented | Synthetic-only policy; manual scripts, not product paths |
| Background worker tenant propagation | Not implemented | No such surface exists; tripwire test guards introduction (`tests/unit/privacy/test_boundary_enforcement.py`) |
| RLS at the database layer | Not implemented | Enforcement today is application/query scoped |
| Log aggregation retention (180d direction) | Partially implemented | Call-site hygiene done; sink lifecycle is deploy scope |

## Residual risks and accepted limitations

1. 500-char truncation can split a PII fragment mid-value.
2. Unclassified free text is denied at the LLM gate, which can refuse
   legitimate flows until fields are classified (fail-closed by design).
3. Terminal + different-payload replay returns the prior outcome
   (pre-existing executor semantics, unchanged).
4. Telemetry trace partitioning by tenant is unestablished.
5. Sheets cell-to-tenant mapping is unknown.
6. Legacy S3 batch reader, Gmail live reader, and Slack approval I/O
   are declared but unimplemented; their inventory rows record absence.
7. Prompt logging is unaudited; approval persistence TBD.

## Operational responsibilities

- Rotate provider/LLM credentials on suspicion; never commit them
  (CI secret gate enforces).
- Apply the Alembic head on deploy; verify `a3f6c1e8b2d4` semantics on
  upgrade (tenant-scoped ledger keys).
- Expired bindings and tombstoned payloads are normal steady state;
  monitor purge/anonymize counts, not just failures.
- Incidents follow `docs/privacy/INCIDENT_RESPONSE.md`; recurrence
  opens a new incident referencing the prior id.

## What is explicitly NOT claimed

No DPDP compliance, no GDPR/UK GDPR compliance, no PCI DSS
compliance, no certification, no legal opinion, no SOC/SIEM operation.
FinSight implements controls designed to support privacy and security
obligations; obligations themselves are determined with counsel.
