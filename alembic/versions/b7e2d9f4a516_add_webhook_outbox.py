"""Add webhook_outbox dispatch table (issue #113).

Revision ID: b7e2d9f4a516
Revises: a3f6c1e8b2d4
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7e2d9f4a516"
down_revision: str | Sequence[str] | None = "a3f6c1e8b2d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhook_outbox",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("webhook_event_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payload_hash", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("leased_until", sa.DateTime(), nullable=True),
        sa.Column("claim_token", sa.String(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("execution_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["webhook_event_id"], ["webhook_events.id"], name="fk_webhook_outbox_event"
        ),
        sa.PrimaryKeyConstraint("id", name="webhook_outbox_pkey"),
        sa.UniqueConstraint("webhook_event_id", name="uq_webhook_outbox_event"),
    )
    op.create_index(
        "ix_webhook_outbox_tenant_status",
        "webhook_outbox",
        ["tenant_id", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_webhook_outbox_tenant_id"), "webhook_outbox", ["tenant_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_outbox_tenant_status", table_name="webhook_outbox")
    op.drop_index(op.f("ix_webhook_outbox_tenant_id"), table_name="webhook_outbox")
    op.drop_table("webhook_outbox")
