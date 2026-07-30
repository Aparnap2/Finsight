# Database Migrations

Run in numeric order against PostgreSQL 15+.

## Order

| Step | File | What |
|------|------|------|
| 0 | `000_init.sql` | CREATE TABLE IF NOT EXISTS for all 27 ORM models (legacy + PRD §7) |
| 1 | `001_extensions.sql` | `pgcrypto`, `btree_gist`, session context functions |
| 2 | `002_not_null.sql` | NOT NULL constraints (~40 columns) |
| 3 | `003_check_constraints.sql` | CHECK constraints (57 total), GENERATED ALWAYS columns |
| 4 | `004_indexes.sql` | Performance indexes (92 total: covering, partial, BRIN, composite) |
| 5 | `005_unique_constraints.sql` | UNIQUE constraints + partial unique indexes for nullable columns |
| 6 | `006_rls.sql` | Row-Level Security (27 policies, 1 per tenant-scoped table) |
| 7 | `007_audit_triggers.sql` | Append-only, data-change audit, soft-delete triggers (75 total) |
| 8 | `008_state_machines.sql` | State machine enforcement triggers (4: invoice, agent_run, pipeline, action) + `updated_at` auto-update for action_items |

## Run

```bash
docker compose up -d postgres
for f in database/migrations/0*.sql; do
  echo "=== $f ==="
  docker compose exec -T postgres psql -U finsight -d finsight -f "/migrations/$(basename $f)"
done
```

Copy files into container first:
```bash
docker compose cp database/migrations postgres:/migrations
```

## Idempotent

All statements use `IF NOT EXISTS` or `DO $$` blocks — safe to re-run.
