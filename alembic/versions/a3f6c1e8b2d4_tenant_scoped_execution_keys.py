"""tenant-scoped execution + idempotency ledger keys

Revision ID: a3f6c1e8b2d4
Revises: c9d5e7f1a204
Create Date: 2026-10-03 00:00:00.000000

Execution integrity was single-keyed by idempotency_key, so two tenants
with the same key collided on ExecutionRow or the idempotency store, and
a cross-tenant request could observe or graft another tenant's execution.

Identity is now the ordered pair (tenant_id, idempotency_key):

* ``execution_records``: add ``tenant_id`` column (NOT NULL, default ''),
  upgrade primary key to (tenant_id, idempotency_key).
* ``idempotency_keys``: same treatment.

In production, on an existing table ALTER would need to drop and recreate
the PK constraint; backfill ``tenant_id=''`` for rows pre-dating this
change and set the application tenant explicitly before importing new
rrows. In dev/sqlite, a rebuild of the table is required for the
constraint; the SQL that does this is below for Postgres and a table
swap-guarded variant for sqlite.
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
    """Tenant-scope the execution record and idempotency ledger tables."""
    with op.batch_alter_table("execution_records") as batch:
        batch.add_column(sa.Column("tenant_id", sa.String(), nullable=True))
        batch.execute("UPDATE execution_records SET tenant_id = '' WHERE tenant_id IS NULL")
        batch.alter_column("tenant_id", existing_type=sa.String(), nullable=False)
        batch.drop_constraint("execution_records_pkey", type_="primary")
        batch.create_primary_key("execution_records_pkey", ["tenant_id", "idempotency_key"])
        batch.alter_column("idempotency_key", existing_type=sa.String(), nullable=False)

    with op.batch_alter_table("idempotency_keys") as batch:
        batch.add_column(sa.Column("tenant_id", sa.String(), nullable=True))
        batch.execute("UPDATE idempotency_keys SET tenant_id = '' WHERE tenant_id IS NULL")
        batch.alter_column("tenant_id", existing_type=sa.String(), nullable=False)
        batch.drop_constraint("idempotency_keys_pkey", type_="primary")
        batch.create_primary_key("idempotency_keys_pkey", ["tenant_id", "idempotency_key"])
        batch.alter_column("idempotency_key", existing_type=sa.String(), nullable=False)


def downgrade() -> None:
    """Restore the single-key ledger (best-effort; tenant isolation lost)."""
    with op.batch_alter_table("idempotency_keys") as batch:
        batch.drop_constraint("idempotency_keys_pkey", type_="primary")
        batch.create_primary_key("idempotency_keys_pkey", ["idempotency_key"])
        batch.drop_column("tenant_id")

    with op.batch_alter_table("execution_records") as batch:
        batch.drop_constraint("execution_records_pkey", type_="primary")
        batch.create_primary_key("execution_records_pkey", ["idempotency_key"])
        batch.drop_column("tenant_id")
