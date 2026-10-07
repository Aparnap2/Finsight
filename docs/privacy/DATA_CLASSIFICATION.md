# DATA_CLASSIFICATION.md (P10-01)

Source of truth: `shared/privacy/inventory.py` (`INVENTORY`). This
document is derived from it; `test_inventory_document_sync` fails if
they diverge. Classification vocabulary: PUBLIC / INTERNAL / PERSONAL /
FINANCIAL_SENSITIVE / SECRET. Label of this work: hardened, not
compliant (DPDP substantive provisions in force 13 May 2027).

Conventions: `retention: unknown` / `deletion_rule: unknown` means no
rule exists in the repository (a gap, not a policy). `tenant_boundary:
unenforced/unestablished` means no boundary code exists for that flow.

## Source: razorpay

- `envelope id/type` (INTERNAL): dedupe + routing; stored webhook_events(id, event_id, event_type); fingerprint derived; never raw to LLM; ids in logs; retention unknown; deletion unknown; explicit tenant_id, unroutable quarantined.
- `raw provider payload (verbatim JSON)` (PERSONAL): immutable audit of provider-sent bytes; stored webhook_events.raw verbatim; redacted event_data derived via secrets.redact_mapping; never to LLM; never logged; retention unknown; deletion unknown; explicit tenant_id.
- `tenant map (account -> tenant)` (INTERNAL): inbound tenant resolution; config at verify time; resolution outcome derived; never to LLM; account id in ambiguity warnings; retention unknown; deletion unknown; IS the boundary for this source.
- `payment_id / charge_event_id / refund ids` (INTERNAL): lifecycle joins; StripePayment fold + event_id unique; payload_hash bindings derived; refs may enter evidence summaries; ids in logs; retention unknown; deletion unknown; tenant_id part of fold identity.
- `gross/fee/refund amounts + currency` (FINANCIAL_SENSITIVE): reconciliation legs; StripePayment Decimal-only; PaymentRecord legs + evidence summaries derived; amounts in evidence by design; amounts not logged; retention unknown; deletion unknown (financial record kept); tenant_id part of fold identity.
- `webhook HMAC secret` (SECRET): envelope authentication; env-only, never persisted; no copies permitted; never to LLM; never logged; never retained in logs; rotate on suspicion; per-endpoint, not tenant data.

## Source: quickbooks

- `payment/ledger identifiers` (INTERNAL): join books legs to provider legs; PaymentRecord ids; reconciliation legs + evidence summaries derived; refs in evidence; ids in logs; retention unknown; deletion unknown; tenant_id on every record.
- `gross/fee/refund/net + currency + status + occurred_at` (FINANCIAL_SENSITIVE): books-side legs; PaymentRecord Decimal-only immutable; legs + evidence derived; amounts in evidence by design; amounts not logged; retention unknown; deletion unknown (financial record kept); tenant_id on every record.

## Source: legacy_financial

- `batch_id (LEGACY-YYYYMMDD-NNNN)` (INTERNAL): batch identity; result file header (S3 per registry; reader TBD); checksum/sequence artifacts derived; never to LLM; batch ids in logs; retention unknown; deletion unknown; company isolation enforced.
- `record result (sequence + accept/reject code + checksum)` (INTERNAL): per-record verdict; fixed-width lines (reader TBD); no copies established; never to LLM; counts/codes in logs; retention unknown; deletion unknown; company isolation enforced.
- `record detail free text (<=50 chars)` (PERSONAL): operator note; fixed-width lines (reader TBD); no copies established; never to LLM, treat as untrusted; logging reader-dependent; retention unknown; deletion unknown; company isolation enforced.

## Source: sheets

- `expected settlement figure (one watched cell)` (FINANCIAL_SENSITIVE): expected variance leg; read at verify time, not persisted; variance gaps derived; figure may enter evidence; values not logged; retention unknown; source-owned, nothing local to erase; cell-to-tenant mapping unknown in repository.
- `service credentials path` (SECRET): sheet read auth; path only, key material never in repo; no copies permitted; never to LLM; never logged; never retained in logs; rotate on suspicion; per-deployment, not tenant data.

## Source: gmail

- `message subject + body snippet (<=280 chars)` (PERSONAL): refund/fee context, untrusted DATA never instruction; fixture corpus stands in, no live reader in repo; content_hash + snippet derived; snippets may enter evidence (minimization required); snippet logging unaudited; retention unknown; deletion unknown; corpus partitioned + filtered by tenant.
- `message_id` (INTERNAL): dedupe + provenance; transient hit records; content_hash fallback id derived; refs in evidence; ids in logs; retention unknown; deletion unknown; corpus partitioned + filtered by tenant.

## Source: slack

- `human approval decision (hash-pinned, declared-only)` (INTERNAL): human decision fact on proposal hash; no store in repository (flow unimplemented); no copies established; never to LLM (declared); logging unestablished; retention/flow unimplemented; deletion/flow unimplemented; unenforced.
- `approver identity (declared-only)` (PERSONAL): attribute the decision; no store in repository (flow unimplemented); no copies established; must never enter prompts; logging unestablished; retention/flow unimplemented; deletion/flow unimplemented; unenforced.

## Source: finsight_derived

- `exception identity (id, tenant, recon id, type, severity)` (INTERNAL): lifecycle tracking; postgres exceptions; audit + execution links + observation projections derived; ids in evidence; ids in logs; retention unknown; deletion unknown (never auto-delete); tenant_id column, tenant-pinned CAS.
- `exception state + version + evidence_ids` (INTERNAL): lifecycle position + evidence refs; ExceptionRow; audit + timeline derived; state names in evidence; states/versions in logs; retention unknown; deletion unknown (never auto-delete); tenant_id column, tenant-pinned CAS.
- `audit actor id + transition + reason` (PERSONAL): who moved what, why; exception_audits append-only; observation projections derived; never to LLM (declared); actor ids in logs; retention unknown; deletion unknown (append-only); tenant_id on audit rows.
- `execution ledger (tenant+key, execution_id, refs, outcome)` (INTERNAL): exactly-once effect + replay; execution_records composite PK; terminal replays derived; never to LLM; keys/ids in logs; retention unknown; deletion unknown (never auto-delete); composite PK + tenant-derived execution_id.
- `idempotency bindings (key -> payload hash)` (INTERNAL): duplicate suppression; idempotency_keys composite PK; no copies; never to LLM; keys in logs; retention unknown; deletion unknown; composite PK.
- `HITL approval record (ids, content_hash, decision)` (INTERNAL): immutable human-decision fact; in-memory aggregate, repository TBD; audit APPLIED entries derived; hashes in evidence; ids/hashes in logs; retention unknown; deletion unknown (never auto-delete); via owning exception tenant.
- `approver_id (human identity)` (PERSONAL): attribute the decision; mirrored on record, owned by identity provider; audit actor field derived; must never enter prompts; actor ids in logs; retention unknown; deletion unknown (never auto-delete); via owning exception tenant.
- `LLM evidence summaries (amounts, refs, tenant names)` (FINANCIAL_SENSITIVE): grounded reasoning input; transient per-call text (+ fixture mirrors); validated output derived, raw never persisted; investigation input by design (minimize further); prompt logging unaudited; retention unknown; transient + fixture policy needed; single-tenant context per call.
- `telemetry trace files (query, steps, results, assertions)` (PERSONAL): debug + replay; local JSON files with full step results; file lifecycle unmanaged; post-hoc artifact, not prompt input; query PII may be present; retention unknown; deletion unknown; tenant partitioning unestablished.
- `eval fixtures/reports (tenant names, charge refs, amounts)` (INTERNAL): benchmark + regression evidence; committed JSON + ephemeral reports; CI logs + future runs dir derived; fixtures ARE live-eval inputs (synthetic only); ids in logs; fixtures versioned, reports ephemeral; synthetic, rotate on realism change; synthetic tenants only, never real data.
- `observation API projections` (INTERNAL): operator reads; computed per request, no store; no copies; never to LLM; ids in access logs; n/a (no storage); n/a (no storage); actor tenant enforced, 404 on foreign ids.
- `application logs (ids, keys, codes, versions)` (INTERNAL): operations + audit support; stdout/files per deploy, ids-only per call sites; deploy aggregation out of scope; never to LLM; self-describing; 180-day CERT-In direction noted, not implemented; no erasure path in repo; tenant ids logged, not filterable.
- `API keys / provider credentials` (SECRET): provider + LLM auth; env-only via pydantic-settings, never persisted; no copies permitted; never to LLM; never logged (CI secret gate); never retained in logs; rotate on suspicion; per-deployment, not tenant data.

## Product gaps (not inventory gaps: surfaces needing implementation)

1. Slack approval I/O unimplemented (declared-only integration).
2. Gmail live reader absent (fixture corpus only).
3. Legacy S3 batch reader TBD (protocol exists: finance/legacy/protocol.py).
4. Retention/erasure rules absent repo-wide (all `unknown` rows above).
5. Telemetry trace file lifecycle + tenant partitioning unestablished.
6. Sheets cell-to-tenant mapping unknown.
7. Prompt logging unaudited (LLM evidence row).
8. ApprovalRecord persistence TBD (in-memory aggregate).

## Token-vault vs keyed-hash decision matrix (P10-02 gate input)

Per use case, not global. Existing precedent: tenant-scoped
irreversible `hash_pii(value, tenant_id)` (shared/safety/secrets.py).

| Use case | Recover original? | Needed for execution? | Crosses trust boundary? | If mapping leaks? | Recommendation |
|---|---|---|---|---|---|
| Execution/idempotency keys | No (client supplies per request) | Yes, as lookup key | No (stays in ledger) | N/A (not secret) | Plain keys; no vault, no hash |
| payment_id for provider API calls | Yes (provider requires original) | Yes | Yes (to provider) | Provider-scoped linkage | Keep provider-scoped originals; never to LLM; no vault (provider is the vault) |
| Customer email/phone for investigation display | Only if shown to humans | No | Only on display | Identity linkage | **Unresolved: needs P10-03 evidence** — reversible vault iff review UI must show originals; else irreversible per-call tokens |
| Approver identity in audit | Yes (audit must attribute) | No | No (stays in audit store) | Attribution linkage | Keep in authoritative audit store with access control; no parallel vault |
| Evidence text correlation | No (stable match suffices) | No | Into prompts | Linkage across cases | Irreversible tenant-scoped hash (existing hash_pii pattern) |
| Tenant identifiers | No (routing key) | Yes, as scope | No | Tenant linkage (already visible) | Plain; it IS the boundary key |

**Decision:** no token-vault service now. Nothing in the evidenced flows requires storing reversible identity tokens in a new service: execution uses client-supplied keys, provider calls use provider-scoped originals, correlation is served by the existing irreversible tenant-scoped hash, and audit attribution stays in the authoritative store. Revisit iff P10-03 evidence shows live customer PII must enter prompts (then minimize first) or a review surface must display originals (then vault narrowly for that surface). P10-02 scope: minimization + keyed tokens where evidenced, no vault.
