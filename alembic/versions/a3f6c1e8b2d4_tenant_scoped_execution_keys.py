"""tenant-scoped execution + idempotency ledger keys

Revision ID: a3f6c1e8b2d4
Revises: c9d5e7f1a204
Create Date: 2026-10-03 00:00:00.000000

Execution integrity was single-keyed by idempotency_key, so two tenants
with the same key collided on ExecutionRow or the idempotency store, and
a cross-tenant request could observe or graft another tenant's execution.

Identity is now the ordered pair (tenant_id, idempotency_key):

* ``execution_records``: add ``tenant_id`` column (NOT NULL,
  backfilled, server default removed after backfill), upgrade primary
  key to (tenant_id, idempotency_key).
* ``idempotency_keys``: same treatment.

Pre-existing rows keep ``tenant_id=''`` and must be tenant-remapped by
an explicit data pass before cutover: the application rejects empty
tenant ids, so unmapped rows are invisible orphans, not live data.

On Postgres, ``batch_alter_table`` emits plain ``ALTER TABLE``
statements; every step below takes ``ACCESS EXCLUSIVE``. Deploy only
with writers quiesced.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f6c1e8b2d4"
down_revision: str | Sequence[str] | None = "c9d5e7f1a204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Tenant-scope the execution record and idempotency ledger tables.

    DEPLOY ONLY WITH WRITERS QUIESCED: every statement below takes
    ACCESS EXCLUSIVE on its table (PK drop/recreate + full unique-index
    build are non-concurrent). Never run downgrade() in production —
    it destroys the tenant boundary; forward-fix only.
    """
    op.execute("UPDATE execution_records SET tenant_id = '' WHERE tenant_id IS NULL")
    with op.batch_alter_table("execution_records") as batch:
        batch.add_column(sa.Column("tenant_id", sa.String(), nullable=True, server_default=""))
    op.execute("UPDATE execution_records SET tenant_id = '' WHERE tenant_id IS NULL")
    with op.batch_alter_table("execution_records") as batch:
        batch.alter_column(
            "tenant_id",
            existing_type=sa.String(),
            nullable=False,
            server_default=None,
        )
        batch.drop_constraint("execution_records_pkey", type_="primary")
        batch.create_primary_key("execution_records_pkey", ["tenant_id", "idempotency_key"])
        batch.alter_column("idempotency_key", existing_type=sa.String(), nullable=False)

    with op.batch_alter_table("idempotency_keys") as batch:
        batch.add_column(sa.Column("tenant_id", sa.String(), nullable=True, server_default=""))
    op.execute("UPDATE idempotency_keys SET tenant_id = '' WHERE tenant_id IS NULL")
    with op.batch_alter_table("idempotency_keys") as batch:
        batch.alter_column(
            "tenant_id",
            existing_type=sa.String(),
            nullable=False,
            server_default=None,
        )
        batch.drop_constraint("idempotency_keys_pkey", type_="primary")
        batch.create_primary_key("idempotency_keys_pkey", ["tenant_id", "idempotency_key"])
        batch.alter_column("idempotency_key", existing_type=sa.String(), nullable=False)


def downgrade() -> None:
    """NEVER RUN IN PRODUCTION. Restores the single-key ledger, which
    destroys the tenant boundary and fails outright if any cross-tenant
    key collision exists. Production rollback is restore-from-backup /
    forward-fix only."""
    with op.batch_alter_table("idempotency_keys") as batch:
        batch.drop_constraint("idempotency_keys_pkey", type_="primary")
        batch.create_primary_key("idempotency_keys_pkey", ["idempotency_key"])
        batch.drop_column("tenant_id")

    with op.batch_alter_table("execution_records") as batch:
        batch.drop_constraint("execution_records_pkey", type_="primary")
        batch.create_primary_key("execution_records_pkey", ["idempotency_key"])
        batch.drop_column("tenant_id")
