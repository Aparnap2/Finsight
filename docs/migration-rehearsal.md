# Migration Rehearsal — Slice 2 Evidence (GitHub #98 / APA-73)

Rehearsal only. No production database was touched; all work ran on
two empty scratch databases in a throwaway `postgres:16-alpine`
container (`finsight-scratch-pg`, removed after the run).

## Recon

- Single head, linear history, no branches:
  `<base> -> 3e7131feb86b -> 4f8a2c1b3d9e -> 7a1c9e2b4f03
  -> c9d5e7f1a204 -> a3f6c1e8b2d4 (head)`.
- `alembic/env.py` sources the URL from `alembic.ini`
  (`postgresql://...`, psycopg2 dialect). The project stack uses
  `psycopg` v3, so rehearsal overrode the URL to
  `postgresql+psycopg://` via a scratch ini with an absolute
  `script_location`. The checked-in `alembic.ini` was not modified.
- One revision uses a Postgres-only type (`JSONB` in
  `c9d5e7f1a204`); SQLite rehearsal is not representative, hence the
  scratch Postgres.

## Path 1 — fresh database to head

```bash
docker run -d --rm --name finsight-scratch-pg \
  -e POSTGRES_USER=finsight -e POSTGRES_PASSWORD=finsight \
  -e POSTGRES_DB=scratch_fresh -p 5544:5432 postgres:16-alpine
alembic -c /tmp/alembic_scratch.ini upgrade head
alembic -c /tmp/alembic_scratch.ini current
```

Result: all five revisions applied, `current` reports
`a3f6c1e8b2d4 (head)`, 33 tables created.

## Path 2 — legacy database (pre-tenant revision) to head

```bash
CREATE DATABASE scratch_legacy;
alembic -c /tmp/alembic_legacy.ini upgrade c9d5e7f1a204
# legacy-shaped ledgers (single-key PK, no tenant_id — as the old
# runtime create_all produced), two rows each + one webhook_events row
alembic -c /tmp/alembic_legacy.ini upgrade head
```

Result: upgrade succeeded, `current` reports `a3f6c1e8b2d4 (head)`.

## Invariant verification (scratch_legacy, post-upgrade)

| Invariant | Result |
|---|---|
| Legacy rows preserved | 2/2 execution rows intact |
| Legacy backfill | `tenant_id=''` (invisible orphans per migration design, pending explicit remap) |
| Composite PKs | `PRIMARY KEY (tenant_id, idempotency_key)` on `execution_records` and `idempotency_keys` |
| Cross-tenant same key | `shared-key` coexists under `tenant-a` + `tenant-b` (the fixed semantics) |
| `webhook_events` intact | seeded row present; `(provider, event_id)` unique + tenant index |
| Destructive-op sweep | every `drop_table`/`drop_column` in the history lives in a `downgrade()`; the upgrade path is non-destructive |

Downgrade was deliberately not rehearsed: the `a3f6c1e8b2d4`
downgrade destroys the tenant boundary by design (documented in the
revision; production rollback is restore-from-backup / forward-fix).

## Backup/recovery assumptions (to carry into deployment slice)

- Postgres-level backup (`pg_dump` / volume snapshot) before any
  production migration; restore-from-backup is the only sanctioned
  rollback for the tenant-scoping revision.
- The tenant-scoping upgrade takes `ACCESS EXCLUSIVE` on the ledger
  tables: run with writers quiesced.

## Verdict

PASS — no blocker. No migration created, none modified, none needed.
