"""P10-01 source registry and inventory completeness contract.

The registry names every data-bearing source; INVENTORY holds one row
per sensitive field with the full descriptor set. The completeness test
(``tests/unit/privacy/test_inventory_completeness.py``) fails until
every registered source is inventoried — unknowns are recorded as gap
strings by :func:`completeness_gaps`, never invented.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import StrEnum


class DataClassification(StrEnum):
    """Closed data-class vocabulary (see DATA_CLASSIFICATION.md)."""

    PUBLIC = "public"
    INTERNAL = "internal"
    PERSONAL = "personal"
    FINANCIAL_SENSITIVE = "financial_sensitive"
    SECRET = "secret"


REQUIRED_SOURCE_IDS: tuple[str, ...] = (
    "razorpay",
    "quickbooks",
    "legacy_financial",
    "sheets",
    "gmail",
    "slack",
    "finsight_derived",
)


@dataclass(frozen=True)
class SourceEntry:
    """One data-bearing source and where it enters the system."""

    source_id: str
    description: str
    module_refs: tuple[str, ...]


SOURCE_REGISTRY: tuple[SourceEntry, ...] = (
    SourceEntry(
        source_id="razorpay",
        description="Razorpay webhooks (HMAC-verified raw provider payloads).",
        module_refs=(
            "apps/api/webhooks.py",
            "apps/api/middleware.py",
            "shared/models/database.py",
            "finance/stripe/adapter.py",
        ),
    ),
    SourceEntry(
        source_id="quickbooks",
        description="QuickBooks accounting records via provider adapter/registry.",
        module_refs=("finance/accounting/mock.py", "finance/integration/registry.py"),
    ),
    SourceEntry(
        source_id="legacy_financial",
        description="COBOL legacy settlement batches (fixed-width result "
        "files; checksummed; company-isolated).",
        module_refs=("finance/legacy/protocol.py",),
    ),
    SourceEntry(
        source_id="sheets",
        description="Google Sheets ingestion adapter.",
        module_refs=("finance/ingestion/sheets_adapter.py",),
    ),
    SourceEntry(
        source_id="gmail",
        description="Gmail evidence gathering (capability surface; reader TBD).",
        module_refs=("agents/capabilities/capabilities.py",),
    ),
    SourceEntry(
        source_id="slack",
        description="Slack evidence gathering (capability surface; reader TBD).",
        module_refs=("agents/capabilities/capabilities.py",),
    ),
    SourceEntry(
        source_id="finsight_derived",
        description="FinSight-generated data: Postgres rows, LLM context, "
        "telemetry/traces, eval fixtures/reports, observation projections.",
        module_refs=(
            "finance/exceptions/models.py",
            "finance/execution/models.py",
            "shared/safety/idempotency.py",
            "shared/tracing/",
            "tests/fixtures/eval_golden/",
            "apps/api/observations.py",
        ),
    ),
)


@dataclass(frozen=True)
class InventoryRow:
    """One sensitive field with its full handling descriptor set."""

    source_id: str
    field: str
    classification: DataClassification
    purpose: str
    system_of_record: str
    storage: str
    derived_copies: str
    llm_exposure: str
    logging_exposure: str
    retention: str
    deletion_rule: str
    tenant_boundary: str


#: Field-level inventory. Empty until the P10-01 GREEN pass fills it;
#: the completeness test fails while any source is uncovered.
INVENTORY: tuple[InventoryRow, ...] = (
    # -- razorpay (apps/api/webhooks.py, shared/models/database.py) --
    InventoryRow(
        source_id="razorpay",
        field="envelope id/type",
        classification=DataClassification.INTERNAL,
        purpose="deduplicate + route provider events",
        system_of_record="provider",
        storage="webhook_events(id, event_id, event_type)",
        derived_copies="payload fingerprint (P1 stable hash)",
        llm_exposure="none: envelope ids only, never raw payload",
        logging_exposure="event ids only in logs",
        retention="unknown: no retention rule in repository",
        deletion_rule="unknown: no erasure path in repository",
        tenant_boundary="explicit tenant_id; unroutable quarantined",
    ),
    InventoryRow(
        source_id="razorpay",
        field="raw provider payload (verbatim JSON)",
        classification=DataClassification.PERSONAL,
        purpose="immutable audit of exactly what the provider sent",
        system_of_record="provider",
        storage="webhook_events.raw (verbatim, never mutated)",
        derived_copies="redacted event_data via secrets.redact_mapping",
        llm_exposure="none established: normalized records only",
        logging_exposure="never logged (ids only)",
        retention="unknown: no retention rule in repository",
        deletion_rule="unknown: no erasure path in repository",
        tenant_boundary="explicit tenant_id; unroutable quarantined",
    ),
    InventoryRow(
        source_id="razorpay",
        field="tenant map (account -> tenant)",
        classification=DataClassification.INTERNAL,
        purpose="resolve inbound events to owning tenant",
        system_of_record="finsight configuration",
        storage="tenant map config (in-memory at verify time)",
        derived_copies="TenantResolution outcome per envelope",
        llm_exposure="none",
        logging_exposure="account id appears in ambiguity warnings",
        retention="unknown: no retention rule in repository",
        deletion_rule="unknown: no erasure path in repository",
        tenant_boundary="IS the boundary mechanism for this source",
    ),
    InventoryRow(
        source_id="razorpay",
        field="payment_id / charge_event_id / refund ids",
        classification=DataClassification.INTERNAL,
        purpose="idempotency + lifecycle joins across events",
        system_of_record="provider",
        storage="StripePayment fold; webhook_events.event_id unique",
        derived_copies="payload_hash bindings in idempotency ledger",
        llm_exposure="reference ids may appear in evidence summaries",
        logging_exposure="ids in logs",
        retention="unknown: no retention rule in repository",
        deletion_rule="unknown: no erasure path in repository",
        tenant_boundary="tenant_id part of fold identity",
    ),
    InventoryRow(
        source_id="razorpay",
        field="gross/fee/refund amounts + currency",
        classification=DataClassification.FINANCIAL_SENSITIVE,
        purpose="reconciliation legs and variance math",
        system_of_record="provider",
        storage="StripePayment (Decimal-only) via adapter fold",
        derived_copies="PaymentRecord legs; evidence summaries",
        llm_exposure="amounts appear in evidence summaries by design",
        logging_exposure="controlled: amounts not logged (ids/codes only)",
        retention="unknown: no retention rule in repository",
        deletion_rule="unknown: no erasure path; financial record kept",
        tenant_boundary="tenant_id part of fold identity",
    ),
    InventoryRow(
        source_id="razorpay",
        field="webhook HMAC secret",
        classification=DataClassification.SECRET,
        purpose="verify envelope authenticity before persistence",
        system_of_record="provider dashboard + env",
        storage="environment only; never persisted",
        derived_copies="none permitted",
        llm_exposure="never",
        logging_exposure="never (mismatch logged without secret)",
        retention="never retained in application logs",
        deletion_rule="rotate at provider on suspicion",
        tenant_boundary="per-endpoint secret, not tenant data",
    ),
    # -- quickbooks (finance/accounting PaymentRecord) --
    InventoryRow(
        source_id="quickbooks",
        field="payment/ledger identifiers",
        classification=DataClassification.INTERNAL,
        purpose="join books legs to provider legs",
        system_of_record="quickbooks",
        storage="PaymentRecord (payment_id, provider_event_id, idempotency_key)",
        derived_copies="reconciliation legs; evidence summaries",
        llm_exposure="reference ids may appear in evidence summaries",
        logging_exposure="ids in logs",
        retention="unknown: no retention rule in repository",
        deletion_rule="unknown: no erasure path in repository",
        tenant_boundary="tenant_id on every record",
    ),
    InventoryRow(
        source_id="quickbooks",
        field="gross/fee/refund/net + currency + status + occurred_at",
        classification=DataClassification.FINANCIAL_SENSITIVE,
        purpose="books-side reconciliation legs",
        system_of_record="quickbooks",
        storage="PaymentRecord (Decimal-only, immutable)",
        derived_copies="reconciliation legs; evidence summaries",
        llm_exposure="amounts appear in evidence summaries by design",
        logging_exposure="controlled: amounts not logged",
        retention="unknown: no retention rule in repository",
        deletion_rule="unknown: no erasure path; financial record kept",
        tenant_boundary="tenant_id on every record",
    ),
    # -- legacy_financial (finance/legacy/protocol.py COBOL batches) --
    InventoryRow(
        source_id="legacy_financial",
        field="batch_id (LEGACY-YYYYMMDD-NNNN)",
        classification=DataClassification.INTERNAL,
        purpose="identify one settlement batch",
        system_of_record="legacy settlement system",
        storage="batch result file header (S3 per registry; reader TBD)",
        derived_copies="checksum/sequence validation artifacts",
        llm_exposure="none established",
        logging_exposure="batch ids in logs",
        retention="unknown: no retention rule in repository",
        deletion_rule="unknown: no erasure path in repository",
        tenant_boundary="company isolation enforced (CompanyIsolationError)",
    ),
    InventoryRow(
        source_id="legacy_financial",
        field="record result (sequence + accept/reject code + checksum)",
        classification=DataClassification.INTERNAL,
        purpose="per-record settlement verdict",
        system_of_record="legacy settlement system",
        storage="fixed-width result lines (reader TBD)",
        derived_copies="none established",
        llm_exposure="none established",
        logging_exposure="record counts/codes in logs",
        retention="unknown: no retention rule in repository",
        deletion_rule="unknown: no erasure path in repository",
        tenant_boundary="company isolation enforced (CompanyIsolationError)",
    ),
    InventoryRow(
        source_id="legacy_financial",
        field="record detail free text (<=50 chars)",
        classification=DataClassification.PERSONAL,
        purpose="operator note on the settlement record",
        system_of_record="legacy settlement system",
        storage="fixed-width result lines (reader TBD)",
        derived_copies="none established",
        llm_exposure="none established; free text must be treated as untrusted",
        logging_exposure="unknown: reader-dependent",
        retention="unknown: no retention rule in repository",
        deletion_rule="unknown: no erasure path in repository",
        tenant_boundary="company isolation enforced (CompanyIsolationError)",
    ),
    # -- sheets (finance/ingestion/sheets_adapter.py) --
    InventoryRow(
        source_id="sheets",
        field="expected settlement figure (one watched cell)",
        classification=DataClassification.FINANCIAL_SENSITIVE,
        purpose="expected leg for provider/books variance",
        system_of_record="spreadsheet owner",
        storage="read at verify time; not persisted by adapter",
        derived_copies="variance gaps in reconciliation output",
        llm_exposure="figure may appear in evidence summaries",
        logging_exposure="controlled: values not logged",
        retention="unknown: no retention rule in repository",
        deletion_rule="unknown: source-owned; no local copies to erase",
        tenant_boundary="unknown: cell-to-tenant mapping not in repository",
    ),
    InventoryRow(
        source_id="sheets",
        field="service credentials path",
        classification=DataClassification.SECRET,
        purpose="authenticate sheet reads",
        system_of_record="secret store / env",
        storage="credentials path only; key material never in repo",
        derived_copies="none permitted",
        llm_exposure="never",
        logging_exposure="never",
        retention="never retained in application logs",
        deletion_rule="rotate at provider on suspicion",
        tenant_boundary="per-deployment credential, not tenant data",
    ),
    # -- gmail (fixture-corpus capability; no live reader in repo) --
    InventoryRow(
        source_id="gmail",
        field="message subject + body snippet (<=280 chars)",
        classification=DataClassification.PERSONAL,
        purpose="refund/fee context evidence (untrusted DATA, never instruction)",
        system_of_record="mailbox (corpus fixture stands in; live reader absent)",
        storage="injected test corpus only; no mailbox persistence in repo",
        derived_copies="content_hash + snippet in capability hits",
        llm_exposure="snippets may enter evidence context; minimization required",
        logging_exposure="unknown: snippet logging not audited",
        retention="unknown: no retention rule in repository",
        deletion_rule="unknown: no erasure path in repository",
        tenant_boundary="corpus partitioned + filtered by tenant at runtime",
    ),
    InventoryRow(
        source_id="gmail",
        field="message_id",
        classification=DataClassification.INTERNAL,
        purpose="dedupe + provenance of evidence hits",
        system_of_record="mailbox (fixture stands in)",
        storage="capability hit records (transient)",
        derived_copies="content_hash fallback id",
        llm_exposure="reference ids may appear in evidence summaries",
        logging_exposure="ids in logs",
        retention="unknown: no retention rule in repository",
        deletion_rule="unknown: no erasure path in repository",
        tenant_boundary="corpus partitioned + filtered by tenant at runtime",
    ),
    # -- slack (declared approval signal; no I/O implementation in repo) --
    InventoryRow(
        source_id="slack",
        field="human approval decision (hash-pinned, declared-only)",
        classification=DataClassification.INTERNAL,
        purpose="human decision fact on a proposal hash",
        system_of_record="undeclared: no reader/writer module in repository",
        storage="none in repository",
        derived_copies="none established",
        llm_exposure="none established",
        logging_exposure="none established",
        retention="unknown: flow unimplemented",
        deletion_rule="unknown: flow unimplemented",
        tenant_boundary="unenforced: approval flow not implemented",
    ),
    InventoryRow(
        source_id="slack",
        field="approver identity (declared-only)",
        classification=DataClassification.PERSONAL,
        purpose="attribute the human decision",
        system_of_record="undeclared: no reader/writer module in repository",
        storage="none in repository",
        derived_copies="none established",
        llm_exposure="never: approver identity must not enter prompts",
        logging_exposure="none established",
        retention="unknown: flow unimplemented",
        deletion_rule="unknown: flow unimplemented",
        tenant_boundary="unenforced: approval flow not implemented",
    ),
    # -- finsight_derived (Postgres rows, LLM context, telemetry, eval, API) --
    InventoryRow(
        source_id="finsight_derived",
        field="exception identity (id, tenant, recon id, type, severity)",
        classification=DataClassification.INTERNAL,
        purpose="track one financial exception through its lifecycle",
        system_of_record="finsight postgres (exceptions)",
        storage="ExceptionRow incl. evidence_ids tuple",
        derived_copies="audit trail; execution links; observation projections",
        llm_exposure="ids may appear in evidence summaries",
        logging_exposure="ids in logs",
        retention="unknown: no retention rule in repository",
        deletion_rule="unknown: authoritative record; never auto-delete",
        tenant_boundary="tenant_id column; CAS predicates tenant-pinned",
    ),
    InventoryRow(
        source_id="finsight_derived",
        field="exception state + version + evidence_ids",
        classification=DataClassification.INTERNAL,
        purpose="lifecycle position and supporting evidence refs",
        system_of_record="finsight postgres (exceptions)",
        storage="ExceptionRow state/state_version/evidence_ids",
        derived_copies="audit trail; observation timeline",
        llm_exposure="state names may appear in evidence summaries",
        logging_exposure="states/versions in logs",
        retention="unknown: no retention rule in repository",
        deletion_rule="unknown: authoritative record; never auto-delete",
        tenant_boundary="tenant_id column; CAS predicates tenant-pinned",
    ),
    InventoryRow(
        source_id="finsight_derived",
        field="audit actor id + transition + reason",
        classification=DataClassification.PERSONAL,
        purpose="who moved the exception, from/to what, why",
        system_of_record="finsight postgres (exception_audits, append-only)",
        storage="ExceptionAuditRow (actor, from/attempted state, reason)",
        derived_copies="observation audit/timeline projections",
        llm_exposure="none established",
        logging_exposure="actor ids in logs",
        retention="unknown: no retention rule in repository",
        deletion_rule="unknown: append-only; never auto-delete",
        tenant_boundary="tenant_id column on audit rows",
    ),
    InventoryRow(
        source_id="finsight_derived",
        field="execution ledger (tenant+key, execution_id, refs, outcome)",
        classification=DataClassification.INTERNAL,
        purpose="exactly-once effect + replay without second mutation",
        system_of_record="finsight postgres (execution_records)",
        storage="ExecutionRow composite PK (tenant_id, idempotency_key)",
        derived_copies="terminal ExecutionResult replays",
        llm_exposure="none",
        logging_exposure="keys/ids in logs",
        retention="unknown: no retention rule in repository",
        deletion_rule="unknown: authoritative record; never auto-delete",
        tenant_boundary="composite PK; tenant-derived execution_id",
    ),
    InventoryRow(
        source_id="finsight_derived",
        field="idempotency bindings (key -> payload hash)",
        classification=DataClassification.INTERNAL,
        purpose="first-claim-wins duplicate suppression",
        system_of_record="finsight postgres (idempotency_keys)",
        storage="IdempotencyRow composite PK (tenant_id, key)",
        derived_copies="none",
        llm_exposure="none",
        logging_exposure="keys in logs",
        retention="unknown: no retention rule in repository",
        deletion_rule="unknown: no erasure path in repository",
        tenant_boundary="composite PK",
    ),
    InventoryRow(
        source_id="finsight_derived",
        field="HITL approval record (ids, content_hash, decision)",
        classification=DataClassification.INTERNAL,
        purpose="immutable fact of one terminal human decision",
        system_of_record="finsight (ApprovalRecord; persistence TBD)",
        storage="in-memory aggregate; repository TBD",
        derived_copies="exception audit APPLIED entries",
        llm_exposure="proposal hashes may appear in evidence summaries",
        logging_exposure="ids/hashes in logs",
        retention="unknown: no retention rule in repository",
        deletion_rule="unknown: authoritative record; never auto-delete",
        tenant_boundary="resolved via owning exception tenant",
    ),
    InventoryRow(
        source_id="finsight_derived",
        field="approver_id (human identity)",
        classification=DataClassification.PERSONAL,
        purpose="attribute the HITL decision",
        system_of_record="identity provider (login); mirrored on record",
        storage="ApprovalRecord.approver_id",
        derived_copies="exception audit actor field",
        llm_exposure="never: approver identity must not enter prompts",
        logging_exposure="actor ids in logs",
        retention="unknown: no retention rule in repository",
        deletion_rule="unknown: authoritative record; never auto-delete",
        tenant_boundary="resolved via owning exception tenant",
    ),
    InventoryRow(
        source_id="finsight_derived",
        field="LLM evidence summaries (amounts, refs, tenant names)",
        classification=DataClassification.FINANCIAL_SENSITIVE,
        purpose="grounded model reasoning over minimized evidence",
        system_of_record="derived per call from engine outputs",
        storage="transient prompt text; eval fixtures mirror the shape",
        derived_copies="model output (validated, never persisted raw)",
        llm_exposure="by design: the investigation input (minimize further)",
        logging_exposure="unknown: prompt logging not audited",
        retention="unknown: no retention rule in repository",
        deletion_rule="unknown: transient; eval copies need policy",
        tenant_boundary="single-tenant context per call (enforced by construction)",
    ),
    InventoryRow(
        source_id="finsight_derived",
        field="telemetry trace files (query, steps, results, assertions)",
        classification=DataClassification.PERSONAL,
        purpose="debug + replay reasoning runs",
        system_of_record="local trace files (ReasoningTelemetry)",
        storage="JSON files incl. full step result dicts",
        derived_copies="unknown: file lifecycle unmanaged",
        llm_exposure="n/a: post-hoc artifact, not prompt input",
        logging_exposure="unknown: trace content may carry query PII",
        retention="unknown: no retention rule in repository",
        deletion_rule="unknown: no erasure path in repository",
        tenant_boundary="unknown: tenant partitioning of trace files not established",
    ),
    InventoryRow(
        source_id="finsight_derived",
        field="eval fixtures/reports (tenant names, charge refs, amounts)",
        classification=DataClassification.INTERNAL,
        purpose="deterministic benchmark + regression evidence",
        system_of_record="tests/fixtures + /tmp reports (synthetic)",
        storage="committed JSON fixtures; ephemeral report files",
        derived_copies="CI logs; observation eval endpoints (future runs dir)",
        llm_exposure="fixtures ARE live-eval prompt inputs (synthetic data only)",
        logging_exposure="ids in logs",
        retention="fixtures versioned in git; reports ephemeral",
        deletion_rule="synthetic: no principal data; rotate on realism change",
        tenant_boundary="synthetic tenants only; must never carry real data",
    ),
    InventoryRow(
        source_id="finsight_derived",
        field="observation API projections",
        classification=DataClassification.INTERNAL,
        purpose="operator console reads",
        system_of_record="derived live from Postgres (no separate store)",
        storage="none: computed per request",
        derived_copies="none",
        llm_exposure="none",
        logging_exposure="ids in access logs",
        retention="n/a: no storage",
        deletion_rule="n/a: no storage",
        tenant_boundary="actor tenant enforced; 404 on foreign ids",
    ),
    InventoryRow(
        source_id="finsight_derived",
        field="application logs (ids, keys, codes, versions)",
        classification=DataClassification.INTERNAL,
        purpose="operations + audit support",
        system_of_record="log pipeline (stdout/files per deploy)",
        storage="sampled: ids/keys/codes only per current call sites",
        derived_copies="log aggregation per deploy (out of repo scope)",
        llm_exposure="none",
        logging_exposure="self-referential: this row describes log content",
        retention="unknown: 180-day CERT-In direction noted, not implemented",
        deletion_rule="unknown: no erasure path in repository",
        tenant_boundary="tenant ids logged, not used as filters",
    ),
    InventoryRow(
        source_id="finsight_derived",
        field="API keys / provider credentials",
        classification=DataClassification.SECRET,
        purpose="authenticate provider + LLM calls",
        system_of_record="environment / secret store (deploy-time)",
        storage="env-only; pydantic-settings; never persisted",
        derived_copies="none permitted",
        llm_exposure="never",
        logging_exposure="never (secret gate in CI)",
        retention="never retained in application logs",
        deletion_rule="rotate at provider on suspicion",
        tenant_boundary="per-deployment, not tenant data",
    ),
)


def completeness_gaps(
    inventory: tuple[InventoryRow, ...] = INVENTORY,
) -> list[str]:
    """List every coverage gap: unknown sources, uncovered sources, blanks.

    A row counts as complete only when all descriptor fields are
    non-blank; blank means "not yet inventoried", never "not applicable"
    (use an explicit N/A-with-reason string for the latter).
    """
    gaps: list[str] = []
    known_ids = {entry.source_id for entry in SOURCE_REGISTRY}
    for required in REQUIRED_SOURCE_IDS:
        if required not in known_ids:
            gaps.append(f"unregistered source: {required}")
    by_source: dict[str, list[InventoryRow]] = {}
    for row in inventory:
        if row.source_id not in known_ids:
            gaps.append(f"row for unknown source: {row.source_id}/{row.field}")
            continue
        by_source.setdefault(row.source_id, []).append(row)
    descriptor_names = [f.name for f in fields(InventoryRow) if f.name != "source_id"]
    for entry in SOURCE_REGISTRY:
        rows = by_source.get(entry.source_id, [])
        if not rows:
            gaps.append(f"uncovered source: {entry.source_id} ({entry.description})")
            continue
        for row in rows:
            for name in descriptor_names:
                value = getattr(row, name)
                text = value.value if isinstance(value, DataClassification) else value
                if not isinstance(text, str) or not text.strip():
                    gaps.append(f"blank {name}: {row.source_id}/{row.field}")
    return gaps
