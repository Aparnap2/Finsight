# INCIDENT_RESPONSE.md (P10-07)

Skeletal runbooks for representative FinSight incidents. Each runbook
declares its category on its own marker line. The sync test fails on
any category outside the code taxonomy. Severity words follow
the incident model (LOW/MEDIUM/HIGH/CRITICAL). Notification entries are
decision records only — no provider integrations exist.

Related code: `shared/privacy/incidents.py` (lifecycle, idempotent
report, notification matrix). Incident registry persistence is not part
of P10-07 and is a post-release/follow-up capability.

## Runbook 1: suspected PII leak in logs

category: DATA_LEAK

1. Detect: log/trace scan surfaces customer-shaped values outside the
   sanitized fields.
2. Triage (owner on record): confirm tenant scope from surrounding
   execution/audit ids; severity HIGH by default, CRITICAL if bulk.
3. Contain: rotate any exposed credential; quarantine the log sink
   (stop shipping, preserve files as evidence).
4. Investigate: identify the emitting call site; check whether the
   sanitizer boundary was bypassed or misclassified.
5. Recover: fix the emission, backfill redaction where the sink allows.
6. Notify: HIGH → owner + board per the notification matrix.
7. Close with outcome + lessons; recurrence opens a new incident
   referencing this id.

## Runbook 2: cross-tenant access suspicion

category: TENANT_ISOLATION

1. Detect: 403/404 anomaly, tenant-mismatch alert, or failed CAS with
   foreign identifiers.
2. Triage: identify both tenants; confirm no read/write crossed (audit
   trail + execution ledger are the evidence sources).
3. Contain: disable the suspect credential/actor; preserve audit rows
   (append-only, never delete).
4. Investigate: replay the request path in test; determine whether the
   boundary held (expected) or a new bypass exists.
5. Recover: patch the bypass; add a regression probe to the adversarial
   matrix.
6. Notify: CRITICAL → owner + board + affected principals.
7. Close with outcome + lessons; recurrence opens a new incident
   referencing this id.

## Runbook 3: exposed signing/API secret

category: SECRET_EXPOSURE

1. Detect: secret gate, scanner alert, or anomalous authenticated calls.
2. Triage: identify secret scope (webhook signing vs provider API vs
   LLM key); severity CRITICAL by default.
3. Contain: revoke/rotate immediately at the provider; preserve the
   exposure evidence (which logs/payloads carried it, redacted copies).
4. Investigate: determine first-exposure point and blast radius from
   audit + access logs.
5. Recover: deploy rotated secret; verify old secret rejected
   everywhere (401/403, no fallback acceptance).
6. Notify: CRITICAL → owner + board; principals only if customer data
   was reachable with the secret.
7. Close with outcome + lessons; recurrence opens a new incident
   referencing this id.
