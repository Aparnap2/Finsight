"""add webhook_events ingestion boundary

Revision ID: 7a1c9e2b4f03
Revises: 4f8a2c1b3d9e
Create Date: 2026-09-08 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7a1c9e2b4f03"
down_revision: str | Sequence[str] | None = "4f8a2c1b3d9e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the webhook_events table."""
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("fingerprint", sa.String(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "event_id", name="uq_webhook_events_provider_event"
        ),
    )
    op.create_index("ix_webhook_events_tenant_id", "webhook_events", ["tenant_id"])
    op.create_index("ix_webhook_events_fingerprint", "webhook_events", ["fingerprint"])


def downgrade() -> None:
    """Drop the webhook_events table."""
    op.drop_index("ix_webhook_events_fingerprint", table_name="webhook_events")
    op.drop_index("ix_webhook_events_tenant_id", table_name="webhook_events")
    op.drop_table("webhook_events")
