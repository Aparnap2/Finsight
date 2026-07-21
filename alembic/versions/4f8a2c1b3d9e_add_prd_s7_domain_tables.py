"""add prd section 7 domain model tables

Revision ID: 4f8a2c1b3d9e
Revises: 3e7131feb86b
Create Date: 2026-07-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4f8a2c1b3d9e"
down_revision: Union[str, Sequence[str], None] = "3e7131feb86b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the 12 PRD §7 domain-model tables."""

    op.create_table(
        "review_decisions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("assertion_id", sa.String(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("reviewer", sa.String(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_decisions_tenant_id", "review_decisions", ["tenant_id"])

    op.create_table(
        "action_items",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("domain", sa.String(), nullable=False),
        sa.Column("target", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("impact_json", sa.JSON(), nullable=True),
        sa.Column("cited_assertion_ids", sa.JSON(), nullable=True),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_action_items_tenant_id", "action_items", ["tenant_id"])

    op.create_table(
        "commentary_versions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("author", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_commentary_versions_tenant_id", "commentary_versions", ["tenant_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("event_data", sa.JSON(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])

    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pipeline_runs_tenant_id", "pipeline_runs", ["tenant_id"])

    op.create_table(
        "assertions_db",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("assertion_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("value", sa.Numeric(precision=15, scale=6), nullable=True),
        sa.Column("support_level", sa.String(), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assertions_db_tenant_id", "assertions_db", ["tenant_id"])

    op.create_table(
        "tool_result_cache",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("tool_name", sa.String(), nullable=False),
        sa.Column("query_fingerprint", sa.String(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tool_result_cache_tenant_id", "tool_result_cache", ["tenant_id"])

    op.create_table(
        "data_quality_snapshots",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("report_json", sa.JSON(), nullable=True),
        sa.Column("overall_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_data_quality_snapshots_tenant_id",
        "data_quality_snapshots",
        ["tenant_id"],
    )

    op.create_table(
        "policy_decision_logs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("autonomy_level", sa.String(), nullable=True),
        sa.Column("routing_target", sa.String(), nullable=True),
        sa.Column("reasons_json", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_policy_decision_logs_tenant_id",
        "policy_decision_logs",
        ["tenant_id"],
    )

    op.create_table(
        "bridge_analysis_results",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("bridge_json", sa.JSON(), nullable=True),
        sa.Column("reconciles", sa.Boolean(), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bridge_analysis_results_tenant_id",
        "bridge_analysis_results",
        ["tenant_id"],
    )

    op.create_table(
        "variance_snapshots",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("variance_json", sa.JSON(), nullable=True),
        sa.Column("is_material", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_variance_snapshots_tenant_id", "variance_snapshots", ["tenant_id"])

    op.create_table(
        "root_cause_findings_db",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("finding_json", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_root_cause_findings_db_tenant_id",
        "root_cause_findings_db",
        ["tenant_id"],
    )


def downgrade() -> None:
    """Drop the 12 PRD §7 domain-model tables (reverse order)."""
    op.drop_table("root_cause_findings_db")
    op.drop_table("variance_snapshots")
    op.drop_table("bridge_analysis_results")
    op.drop_table("policy_decision_logs")
    op.drop_table("data_quality_snapshots")
    op.drop_table("tool_result_cache")
    op.drop_table("assertions_db")
    op.drop_table("pipeline_runs")
    op.drop_table("audit_logs")
    op.drop_table("commentary_versions")
    op.drop_table("action_items")
    op.drop_table("review_decisions")
