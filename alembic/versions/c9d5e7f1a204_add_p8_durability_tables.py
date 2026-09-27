"""add p8_run_states + p8_run_audit durability tables (Phase 4)

Revision ID: c9d5e7f1a204
Revises: 7a1c9e2b4f03
Create Date: 2026-09-27 00:00:00.000000

Postgres backing for the frozen P8-03 seam: durable run snapshots keyed by
(run_id, input_fingerprint), append-only audit events, quarantine flags.
No behavior change to existing tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9d5e7f1a204"
down_revision: str | Sequence[str] | None = "7a1c9e2b4f03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the P8 durability tables."""
    op.create_table(
        "p8_run_states",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("input_fingerprint", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("attempts", JSONB(), nullable=False),
        sa.Column("terminal_state", sa.String(), nullable=False, server_default=""),
        sa.Column("budget_usage", JSONB(), nullable=False),
        sa.Column("integrity_seal", sa.String(), nullable=False),
        sa.Column("quarantined", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("run_id", "input_fingerprint"),
    )
    op.create_table(
        "p8_run_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("input_fingerprint", sa.String(), nullable=False),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p8_run_audit_run", "p8_run_audit", ["run_id", "input_fingerprint"])


def downgrade() -> None:
    """Drop the P8 durability tables."""
    op.drop_index("ix_p8_run_audit_run", table_name="p8_run_audit")
    op.drop_table("p8_run_audit")
    op.drop_table("p8_run_states")
