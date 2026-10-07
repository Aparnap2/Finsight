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


def _ledger_tables() -> list[sa.Table]:
    """Frozen table definitions mirroring the runtime models.

    No migration before this revision creates ``execution_records`` or
    ``idempotency_keys`` (only runtime ``create_all`` does), so a fresh
    database reaches this revision without them. Definitions mirror
    ``finance.execution.models.ExecutionRow`` and
    ``shared.safety.idempotency.IdempotencyRow`` — the single source of
    truth for columns; keep in sync.
    """
    metadata = sa.MetaData()
    return [
        sa.Table(
            "execution_records",
            metadata,
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("idempotency_key", sa.String(), nullable=False),
            sa.Column("execution_id", sa.String(), nullable=False),
            sa.Column("exception_id", sa.String(), nullable=False),
            sa.Column("proposal_id", sa.String(), nullable=False),
            sa.Column("payload_hash", sa.String(), nullable=False),
            sa.Column("result", sa.String(), nullable=True),
            sa.Column("external_reference", sa.String(), nullable=True),
            sa.Column("post_verify", sa.String(), nullable=True),
            sa.PrimaryKeyConstraint("tenant_id", "idempotency_key"),
        ),
        sa.Table(
            "idempotency_keys",
            metadata,
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("idempotency_key", sa.String(), nullable=False),
            sa.Column("payload_hash", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("tenant_id", "idempotency_key"),
        ),
    ]


def _tenant_scoped(table_name: str) -> bool:
    """Return True when the table already carries the tenant_id column."""
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table_name):
        return False
    return "tenant_id" in {c["name"] for c in insp.get_columns(table_name)}


def upgrade() -> None:
    """Tenant-scope the execution record and idempotency ledger tables.

    Three states handled explicitly (never assume the table exists):
    fresh DB (create full new schema, no ALTERs), legacy single-key
    table (add column, backfill, set NOT NULL, swap PK), current
    schema (no-op).

    DEPLOY ONLY WITH WRITERS QUIESCED: every ALTER step below takes
    ACCESS EXCLUSIVE on its table (PK drop/recreate + full unique-index
    build are non-concurrent). Never run downgrade() in production —
    it destroys the tenant boundary; forward-fix only.
    """
    for table in _ledger_tables():
        table.create(bind=op.get_bind(), checkfirst=True)
    _scope_table("execution_records")
    _scope_table("idempotency_keys")


def _scope_table(table_name: str) -> None:
    """Upgrade one ledger table from single-key to tenant-scoped identity."""
    if _tenant_scoped(table_name):
        return
    with op.batch_alter_table(table_name) as batch:
        batch.add_column(sa.Column("tenant_id", sa.String(), nullable=True, server_default=""))
    op.execute(f"UPDATE {table_name} SET tenant_id = '' WHERE tenant_id IS NULL")
    with op.batch_alter_table(table_name) as batch:
        batch.alter_column(
            "tenant_id",
            existing_type=sa.String(),
            nullable=False,
            server_default=None,
        )
        batch.drop_constraint(f"{table_name}_pkey", type_="primary")
        batch.create_primary_key(f"{table_name}_pkey", ["tenant_id", "idempotency_key"])
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
