"""reconciliation schema + demo tenant seed

Revision ID: d4e5f6a7b8c9
Revises: c9d5e7f1a204
Create Date: 2026-11-23

Adds the 13 reconciliation tables from docs/specs/DATABASE_SCHEMA.md §3,
Row-Level Security policies on every tenant-scoped table, append-only
triggers on exception_decisions and audit_events, and a deterministic,
idempotent seed of the three demo tenants.

Seed data is a reviewed constant baked into this migration. It is NOT read
from tenants/demo/*/tenant.yaml at runtime, so migration execution does not
depend on mutable application configuration or arbitrary filesystem
contents. Re-running the migration is a no-op for existing tenant rows.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "b7e2d9f4a516"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_SCOPED_TABLES: Sequence[str] = (
    "import_sessions",
    "source_files",
    "import_rows",
    "reconciliation_runs",
    "reconciliation_matches",
    "payout_allocations",
    "allocation_legs",
    "reconciliation_exceptions",
    "exception_decisions",
    "investigations",
    "audit_events",
    "export_artifacts",
)

_UUID_DEFAULT = sa.text("gen_random_uuid()")
_NOW_DEFAULT = sa.text("now()")


def upgrade() -> None:
    """Upgrade schema."""
    # --- tenants (new; FP&A schema uses 'entities', not 'tenants') ---
    op.create_table(
        "reconciliation_tenants",
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default=_UUID_DEFAULT),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW_DEFAULT
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'ACTIVE'")),
        sa.PrimaryKeyConstraint("tenant_id"),
        sa.UniqueConstraint("name", name="uq_tenants_name"),
        sa.CheckConstraint("status IN ('ACTIVE', 'SUSPENDED')", name="ck_tenants_status"),
    )

    # --- import_sessions ---
    op.create_table(
        "import_sessions",
        sa.Column("session_id", sa.String(36), nullable=False, server_default=_UUID_DEFAULT),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'CREATED'")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW_DEFAULT
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW_DEFAULT
        ),
        sa.PrimaryKeyConstraint("session_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["reconciliation_tenants.tenant_id"]),
        sa.CheckConstraint(
            "status IN ('CREATED', 'UPLOADING', 'VALIDATING', 'READY', 'REJECTED')",
            name="ck_import_sessions_status",
        ),
        sa.CheckConstraint("period_end >= period_start", name="ck_import_sessions_period"),
    )
    op.create_index("idx_import_sessions_tenant", "import_sessions", ["tenant_id"])
    op.create_index("idx_import_sessions_status", "import_sessions", ["status"])

    # --- source_files ---
    op.create_table(
        "source_files",
        sa.Column("file_id", sa.String(36), nullable=False, server_default=_UUID_DEFAULT),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("storage_ref", sa.String(512), nullable=False),
        sa.Column(
            "uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW_DEFAULT
        ),
        sa.Column("uploaded_by", sa.String(36), nullable=False),
        sa.PrimaryKeyConstraint("file_id"),
        sa.ForeignKeyConstraint(["session_id"], ["import_sessions.session_id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["reconciliation_tenants.tenant_id"]),
        sa.UniqueConstraint("session_id", "source_type", name="uq_source_files_session_type"),
        sa.UniqueConstraint(
            "tenant_id", "source_type", "content_hash", name="uq_source_files_tenant_type_hash"
        ),
        sa.CheckConstraint(
            "source_type IN ('INVOICE', 'STRIPE', 'BANK')", name="ck_source_files_type"
        ),
        sa.CheckConstraint("file_size_bytes > 0", name="ck_source_files_size"),
        sa.CheckConstraint("row_count >= 0", name="ck_source_files_rows"),
    )
    op.create_index("idx_source_files_tenant", "source_files", ["tenant_id"])
    op.create_index("idx_source_files_session", "source_files", ["session_id"])

    # --- import_rows ---
    op.create_table(
        "import_rows",
        sa.Column("row_id", sa.String(36), nullable=False, server_default=_UUID_DEFAULT),
        sa.Column("file_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("raw_data", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("normalized", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("validation_status", sa.String(10), nullable=False),
        sa.Column("reject_reason", sa.String(50), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW_DEFAULT
        ),
        sa.PrimaryKeyConstraint("row_id"),
        sa.ForeignKeyConstraint(["file_id"], ["source_files.file_id"]),
        sa.ForeignKeyConstraint(["session_id"], ["import_sessions.session_id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["reconciliation_tenants.tenant_id"]),
        sa.CheckConstraint(
            "validation_status IN ('VALID', 'INVALID')", name="ck_import_rows_status"
        ),
        sa.CheckConstraint("line_number >= 1", name="ck_import_rows_line"),
    )
    op.create_index("idx_import_rows_file", "import_rows", ["file_id"])
    op.create_index("idx_import_rows_session", "import_rows", ["session_id"])
    op.create_index("idx_import_rows_tenant", "import_rows", ["tenant_id"])
    op.create_index("idx_import_rows_status", "import_rows", ["validation_status"])

    # --- reconciliation_runs ---
    op.create_table(
        "reconciliation_runs",
        sa.Column("run_id", sa.String(36), nullable=False, server_default=_UUID_DEFAULT),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'QUEUED'")),
        sa.Column("engine_version", sa.String(64), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("input_snapshot_ref", sa.String(512), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW_DEFAULT
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW_DEFAULT
        ),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("run_id"),
        sa.ForeignKeyConstraint(["session_id"], ["import_sessions.session_id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["reconciliation_tenants.tenant_id"]),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_reconciliation_runs_tenant_key"
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'VALIDATING', 'PROCESSING', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="ck_reconciliation_runs_status",
        ),
    )
    op.create_index("idx_reconciliation_runs_tenant", "reconciliation_runs", ["tenant_id"])
    op.create_index("idx_reconciliation_runs_session", "reconciliation_runs", ["session_id"])
    op.create_index("idx_reconciliation_runs_status", "reconciliation_runs", ["status"])
    op.create_index("idx_reconciliation_runs_created", "reconciliation_runs", ["created_at"])

    # --- reconciliation_matches ---
    op.create_table(
        "reconciliation_matches",
        sa.Column("match_id", sa.String(36), nullable=False, server_default=_UUID_DEFAULT),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("invoice_id", sa.String(255), nullable=False),
        sa.Column("charge_id", sa.String(255), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("expected_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("observed_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("difference", sa.Numeric(19, 4), nullable=False),
        sa.Column("variance", sa.Numeric(19, 4), nullable=False),
        sa.Column("tolerance_applied", sa.Numeric(19, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("exception_code", sa.String(50), nullable=True),
        sa.Column("materiality", sa.String(12), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW_DEFAULT
        ),
        sa.PrimaryKeyConstraint("match_id"),
        sa.ForeignKeyConstraint(["run_id"], ["reconciliation_runs.run_id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["reconciliation_tenants.tenant_id"]),
        sa.CheckConstraint(
            "outcome IN ('MATCHED', 'TOLERANCE_MATCHED', 'EXCEPTION', 'PENDING_EVIDENCE')",
            name="ck_reconciliation_matches_outcome",
        ),
        sa.CheckConstraint("expected_amount >= 0", name="ck_reconciliation_matches_expected"),
        sa.CheckConstraint("observed_amount >= 0", name="ck_reconciliation_matches_observed"),
        sa.CheckConstraint("variance >= 0", name="ck_reconciliation_matches_variance"),
        sa.CheckConstraint("tolerance_applied >= 0", name="ck_reconciliation_matches_tolerance"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_reconciliation_matches_currency"),
        sa.CheckConstraint(
            "materiality IN ('MATERIAL', 'IMMATERIAL')",
            name="ck_reconciliation_matches_materiality",
        ),
        sa.CheckConstraint(
            "(outcome != 'EXCEPTION' OR exception_code IS NOT NULL) AND "
            "(outcome = 'EXCEPTION' OR exception_code IS NULL)",
            name="ck_reconciliation_matches_exception_code",
        ),
    )
    op.create_index("idx_reconciliation_matches_run", "reconciliation_matches", ["run_id"])
    op.create_index("idx_reconciliation_matches_tenant", "reconciliation_matches", ["tenant_id"])
    op.create_index("idx_reconciliation_matches_invoice", "reconciliation_matches", ["invoice_id"])
    op.create_index("idx_reconciliation_matches_charge", "reconciliation_matches", ["charge_id"])

    # --- payout_allocations ---
    op.create_table(
        "payout_allocations",
        sa.Column("allocation_id", sa.String(36), nullable=False, server_default=_UUID_DEFAULT),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("deposit_id", sa.String(255), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("allocated_total", sa.Numeric(19, 4), nullable=False),
        sa.Column("eligible_net_total", sa.Numeric(19, 4), nullable=False),
        sa.Column("open_balance", sa.Numeric(19, 4), nullable=False),
        sa.Column("unallocated_deposit", sa.Numeric(19, 4), nullable=False),
        sa.Column("fee_total", sa.Numeric(19, 4), nullable=False),
        sa.Column("refund_total", sa.Numeric(19, 4), nullable=False),
        sa.Column("exception_code", sa.String(50), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW_DEFAULT
        ),
        sa.PrimaryKeyConstraint("allocation_id"),
        sa.ForeignKeyConstraint(["run_id"], ["reconciliation_runs.run_id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["reconciliation_tenants.tenant_id"]),
        sa.CheckConstraint(
            "outcome IN ('MATCHED', 'TOLERANCE_MATCHED', 'EXCEPTION', "
            "'PENDING_EVIDENCE', 'REQUIRES_HUMAN')",
            name="ck_payout_allocations_outcome",
        ),
        sa.CheckConstraint("allocated_total >= 0", name="ck_payout_allocations_allocated"),
        sa.CheckConstraint("eligible_net_total >= 0", name="ck_payout_allocations_eligible"),
        sa.CheckConstraint("open_balance >= 0", name="ck_payout_allocations_open"),
        sa.CheckConstraint("unallocated_deposit >= 0", name="ck_payout_allocations_unallocated"),
        sa.CheckConstraint("fee_total >= 0", name="ck_payout_allocations_fee"),
        sa.CheckConstraint("refund_total >= 0", name="ck_payout_allocations_refund"),
        sa.CheckConstraint(
            "(outcome != 'EXCEPTION' OR exception_code IS NOT NULL) AND "
            "(outcome = 'EXCEPTION' OR exception_code IS NULL)",
            name="ck_payout_allocations_exception_code",
        ),
    )
    op.create_index("idx_payout_allocations_run", "payout_allocations", ["run_id"])
    op.create_index("idx_payout_allocations_tenant", "payout_allocations", ["tenant_id"])
    op.create_index("idx_payout_allocations_deposit", "payout_allocations", ["deposit_id"])

    # --- allocation_legs ---
    op.create_table(
        "allocation_legs",
        sa.Column("leg_id", sa.String(36), nullable=False, server_default=_UUID_DEFAULT),
        sa.Column("allocation_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("payment_id", sa.String(255), nullable=False),
        sa.Column("gross", sa.Numeric(19, 4), nullable=False),
        sa.Column("fee", sa.Numeric(19, 4), nullable=False),
        sa.Column("refund", sa.Numeric(19, 4), nullable=False),
        sa.Column("net", sa.Numeric(19, 4), nullable=False),
        sa.Column("allocated", sa.Numeric(19, 4), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("leg_id"),
        sa.ForeignKeyConstraint(["allocation_id"], ["payout_allocations.allocation_id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["reconciliation_tenants.tenant_id"]),
        sa.CheckConstraint("gross >= 0", name="ck_allocation_legs_gross"),
        sa.CheckConstraint("fee >= 0", name="ck_allocation_legs_fee"),
        sa.CheckConstraint("refund >= 0", name="ck_allocation_legs_refund"),
        sa.CheckConstraint("allocated > 0", name="ck_allocation_legs_allocated"),
        sa.CheckConstraint("net = gross - fee - refund", name="ck_allocation_legs_net"),
        sa.CheckConstraint("allocated <= net", name="ck_allocation_legs_allocated_le_net"),
    )
    op.create_index("idx_allocation_legs_allocation", "allocation_legs", ["allocation_id"])
    op.create_index("idx_allocation_legs_tenant", "allocation_legs", ["tenant_id"])
    op.create_index("idx_allocation_legs_payment", "allocation_legs", ["payment_id"])

    # --- reconciliation_exceptions ---
    op.create_table(
        "reconciliation_exceptions",
        sa.Column("exception_id", sa.String(36), nullable=False, server_default=_UUID_DEFAULT),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("exception_code", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'OPEN'")),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "evidence_refs",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("assigned_to", sa.String(36), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW_DEFAULT
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW_DEFAULT
        ),
        sa.PrimaryKeyConstraint("exception_id"),
        sa.ForeignKeyConstraint(["run_id"], ["reconciliation_runs.run_id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["reconciliation_tenants.tenant_id"]),
        sa.CheckConstraint(
            "severity IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')",
            name="ck_reconciliation_exceptions_severity",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'INVESTIGATING', 'UNDER_REVIEW', 'RESOLVED', 'REOPENED')",
            name="ck_reconciliation_exceptions_status",
        ),
    )
    op.create_index("idx_reconciliation_exceptions_run", "reconciliation_exceptions", ["run_id"])
    op.create_index(
        "idx_reconciliation_exceptions_tenant", "reconciliation_exceptions", ["tenant_id"]
    )
    op.create_index("idx_reconciliation_exceptions_status", "reconciliation_exceptions", ["status"])
    op.create_index(
        "idx_reconciliation_exceptions_severity", "reconciliation_exceptions", ["severity"]
    )

    # --- exception_decisions (append-only) ---
    op.create_table(
        "exception_decisions",
        sa.Column("decision_id", sa.String(36), nullable=False, server_default=_UUID_DEFAULT),
        sa.Column("exception_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("decision_type", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_refs", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("previous_status", sa.String(20), nullable=False),
        sa.Column("new_status", sa.String(20), nullable=False),
        sa.Column(
            "decided_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW_DEFAULT
        ),
        sa.PrimaryKeyConstraint("decision_id"),
        sa.ForeignKeyConstraint(["exception_id"], ["reconciliation_exceptions.exception_id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["reconciliation_tenants.tenant_id"]),
        sa.CheckConstraint(
            "decision_type IN ('APPROVE', 'REJECT', 'REOPEN', 'ASSIGN')",
            name="ck_exception_decisions_type",
        ),
    )
    op.create_index("idx_exception_decisions_exception", "exception_decisions", ["exception_id"])
    op.create_index("idx_exception_decisions_tenant", "exception_decisions", ["tenant_id"])
    op.create_index("idx_exception_decisions_decided", "exception_decisions", ["decided_at"])

    op.execute(
        sa.text("""
        CREATE OR REPLACE FUNCTION prevent_exception_decision_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'exception_decisions is append-only: UPDATE and DELETE are prohibited';
        END;
        $$ LANGUAGE plpgsql;
    """)
    )
    op.execute(
        sa.text("""
        CREATE TRIGGER trg_exception_decisions_append_only
            BEFORE UPDATE OR DELETE ON exception_decisions
            FOR EACH ROW
            EXECUTE FUNCTION prevent_exception_decision_mutation();
    """)
    )

    # --- investigations ---
    op.create_table(
        "investigations",
        sa.Column("investigation_id", sa.String(36), nullable=False, server_default=_UUID_DEFAULT),
        sa.Column("exception_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("prompt_fingerprint", sa.String(64), nullable=True),
        sa.Column("result_text", sa.Text(), nullable=True),
        sa.Column(
            "evidence_refs",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW_DEFAULT
        ),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.PrimaryKeyConstraint("investigation_id"),
        sa.ForeignKeyConstraint(["exception_id"], ["reconciliation_exceptions.exception_id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["reconciliation_tenants.tenant_id"]),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name="ck_investigations_status",
        ),
    )
    op.create_index("idx_investigations_exception", "investigations", ["exception_id"])
    op.create_index("idx_investigations_tenant", "investigations", ["tenant_id"])
    op.create_index("idx_investigations_status", "investigations", ["status"])

    # --- audit_events (append-only) ---
    op.create_table(
        "audit_events",
        sa.Column("event_id", sa.String(36), nullable=False, server_default=_UUID_DEFAULT),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=True),
        sa.Column("previous_state", sa.String(50), nullable=True),
        sa.Column("new_state", sa.String(50), nullable=True),
        sa.Column("metadata", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("correlation_id", sa.String(36), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW_DEFAULT
        ),
        sa.PrimaryKeyConstraint("event_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["reconciliation_tenants.tenant_id"]),
    )
    op.create_index("idx_audit_events_tenant", "audit_events", ["tenant_id"])
    op.create_index("idx_audit_events_entity", "audit_events", ["entity_type", "entity_id"])
    op.create_index("idx_audit_events_created", "audit_events", ["created_at"])
    op.create_index("idx_audit_events_correlation", "audit_events", ["correlation_id"])

    op.execute(
        sa.text("""
        CREATE OR REPLACE FUNCTION prevent_audit_event_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only: UPDATE and DELETE are prohibited';
        END;
        $$ LANGUAGE plpgsql;
    """)
    )
    op.execute(
        sa.text("""
        CREATE TRIGGER trg_audit_events_append_only
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW
            EXECUTE FUNCTION prevent_audit_event_mutation();
    """)
    )

    # --- export_artifacts ---
    op.create_table(
        "export_artifacts",
        sa.Column("export_id", sa.String(36), nullable=False, server_default=_UUID_DEFAULT),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column("storage_ref", sa.String(512), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW_DEFAULT
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.PrimaryKeyConstraint("export_id"),
        sa.ForeignKeyConstraint(["run_id"], ["reconciliation_runs.run_id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["reconciliation_tenants.tenant_id"]),
        sa.CheckConstraint(
            "status IN ('PENDING', 'GENERATING', 'COMPLETED', 'FAILED')",
            name="ck_export_artifacts_status",
        ),
        sa.CheckConstraint(
            "format IN ('CSV', 'JSON', 'MARKDOWN')", name="ck_export_artifacts_format"
        ),
    )
    op.create_index("idx_export_artifacts_run", "export_artifacts", ["run_id"])
    op.create_index("idx_export_artifacts_tenant", "export_artifacts", ["tenant_id"])
    op.create_index("idx_export_artifacts_status", "export_artifacts", ["status"])

    # --- Row-Level Security on every tenant-scoped table ---
    for table_name in _TENANT_SCOPED_TABLES:
        op.execute(sa.text(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;"))
        op.execute(sa.text(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;"))
        op.execute(
            sa.text(
                f"CREATE POLICY tenant_isolation_{table_name} ON {table_name} "
                f"USING (tenant_id::uuid = current_setting('app.tenant_id', true)::uuid);"
            )
        )

    # --- Deterministic demo tenant seed (reviewed constant, not runtime config) ---
    # IDs are uuid5(NAMESPACE_DNS, 'finsight-demo-tenant:<slug>') so they are
    # stable and reproducible without reading tenants/demo/*/tenant.yaml.
    op.execute(
        sa.text("""
        INSERT INTO reconciliation_tenants (tenant_id, name, status) VALUES
            ('7d6f8b65-5e40-55b5-967f-69b85912dd87', 'Acme Corporation', 'ACTIVE'),
            ('ea7639b2-4a8e-5954-84a2-f8630e89d206', 'Globex Corporation', 'ACTIVE'),
            ('f954b80c-b345-5714-985a-6e2f46251ff6', 'Initech', 'ACTIVE')
        ON CONFLICT (tenant_id) DO NOTHING;
    """)
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop RLS policies + disable RLS.
    for table_name in _TENANT_SCOPED_TABLES:
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_{table_name} ON {table_name};"))
        op.execute(sa.text(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY;"))

    # Drop append-only triggers/functions.
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_audit_events_append_only ON audit_events;"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS prevent_audit_event_mutation();"))
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS trg_exception_decisions_append_only ON exception_decisions;"
        )
    )
    op.execute(sa.text("DROP FUNCTION IF EXISTS prevent_exception_decision_mutation();"))

    # Drop tables in reverse dependency order.
    for table_name in (
        "export_artifacts",
        "audit_events",
        "investigations",
        "exception_decisions",
        "reconciliation_exceptions",
        "allocation_legs",
        "payout_allocations",
        "reconciliation_matches",
        "reconciliation_runs",
        "import_rows",
        "source_files",
        "import_sessions",
    ):
        op.drop_table(table_name)

    # Demo tenant seed: remove only the seeded demo rows, preserving any
    # tenant created after this migration.
    op.execute(
        sa.text("""
        DELETE FROM reconciliation_tenants
        WHERE tenant_id IN (
            '7d6f8b65-5e40-55b5-967f-69b85912dd87',
            'ea7639b2-4a8e-5954-84a2-f8630e89d206',
            'f954b80c-b345-5714-985a-6e2f46251ff6'
        );
    """)
    )
    op.drop_table("reconciliation_tenants")
