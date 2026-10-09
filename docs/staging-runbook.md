# Staging Bootstrap + Qualification Runbook (Slice 4, Gates 3–4)

Reproducible path from zero to a qualified staging deployment. Every
step records evidence; no step requires secrets in chat, Git, issues,
or logs. Assumes `gcloud` authenticated via workload identity
federation or a local login — never a checked-in key.

## 0. Inputs (record before starting)

```text
GCP_PROJECT      = <dedicated non-production project id>
GCP_REGION       = <e.g. europe-west1>
SQL_INSTANCE     = finsight-staging (PostgreSQL 15+)
SQL_VERSION      = <output of SELECT version();>
RUN_SERVICE      = finsight-staging
BUCKET           = gs://<project>-finsight-staging (private, no public access)
```

Record also: Cloud SQL edition/HA setting, connector vs private IP
choice, and the deployment identity (human or CI federated principal).

## 1. Provision (one-time, auditable commands)

```bash
# Project scoping (every command below repeats --project=$GCP_PROJECT)
gcloud services enable run.googleapis.com sqladmin.googleapis.com \
  secretmanager.googleapis.com storage.googleapis.com --project=$GCP_PROJECT

# PostgreSQL: private connectivity preferred; no public IPv4 unless justified
gcloud sql instances create $SQL_INSTANCE --project=$GCP_PROJECT \
  --region=$GCP_REGION --database-version=POSTGRES_15 \
  --tier=db-custom-2-7680 --no-assign-ip --network=<vpc> \
  --backup-start-time=02:00 --enable-point-in-time-recovery \
  --retained-backups-count=7 --retained-transaction-log-days=7

gcloud sql databases create finsight --instance=$SQL_INSTANCE --project=$GCP_PROJECT

# Least-privilege roles (never superuser for the app)
gcloud sql users create finsight_migrate --instance=$SQL_INSTANCE \
  --project=$GCP_PROJECT --password=<from Secret Manager, never CLI history>
gcloud sql users create finsight_app --instance=$SQL_INSTANCE \
  --project=$GCP_PROJECT --password=<from Secret Manager, never CLI history>

# Secrets (values entered via prompt or file, never echoed)
printf '%s' "$MIGRATE_PW" | gcloud secrets create db-migrate-pw \
  --data-file=- --project=$GCP_PROJECT --replication-policy=automatic
printf '%s' "$APP_PW" | gcloud secrets create db-app-pw \
  --data-file=- --project=$GCP_PROJECT --replication-policy=automatic

# Private bucket
gcloud storage buckets create $BUCKET --project=$GCP_PROJECT \
  --location=$GCP_REGION --uniform-bucket-level-access --no-public-access-prevention-bypass
```

IAM (narrowly scoped deployment identity `$DEPLOY_ID`):

```text
roles/run.admin              on the service only
roles/secretmanager.secretAccessor on db-migrate-pw, db-app-pw only
roles/storage.objectAdmin    on $BUCKET only
roles/cloudsql.client        on $SQL_INSTANCE
```

## 2. Database roles and grants (via the migrate user)

```sql
-- Owners: migrate user owns schema objects (created by migrations).
-- Runtime needs data access without DDL:
GRANT CONNECT ON DATABASE finsight TO finsight_app;
GRANT USAGE ON SCHEMA public TO finsight_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO finsight_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE ON TABLES TO finsight_app;
-- No DELETE except where the application requires it (narrow later).
-- finsight_app must NOT be superuser, owner, or replication role:
SELECT rolname, rolsuper, rolreplication FROM pg_roles
  WHERE rolname IN ('finsight_app', 'finsight_migrate');
```

## 3. Migrate (migration identity only)

```bash
export MIGRATION_POSTGRES_URI="postgresql+psycopg://finsight_migrate:<pw>@/<socket-or-proxy>/finsight"
uv run alembic upgrade head
uv run alembic current   # expect: a3f6c1e8b2d4 (head)
# SQL chain 000-013 (idempotent, version-tracked):
uv run python - <<'EOF'
import psycopg
from shared.migrations import MigrationRunner, discover_migrations
from pathlib import Path
with psycopg.connect("<migrate-dsn>", autocommit=True) as conn:
    results = MigrationRunner(conn).apply(
        discover_migrations(Path("database/migrations")))
print({r.status: sum(1 for x in results if x.status == r.status) for r in results})
EOF
```

## 4. Deploy (Cloud Run, least privilege)

```bash
# Build with repo Dockerfile (Cloud Build keeps the image out of laptops):
gcloud builds submit --project=$GCP_PROJECT --tag $GCP_REGION-docker.pkg.dev/$GCP_PROJECT/finsight/svc:<sha>
gcloud run deploy $RUN_SERVICE --project=$GCP_PROJECT --region=$GCP_REGION \
  --image $GCP_REGION-docker.pkg.dev/$GCP_PROJECT/finsight/svc:<sha> \
  --no-allow-unauthenticated \
  --service-account=<runtime-sa with ONLY the IAM above> \
  --add-cloudsql-instances=$GCP_PROJECT:$GCP_REGION:$SQL_INSTANCE \
  --set-secrets=POSTGRES_URI=db-app-pw:latest \
  --set-env-vars=APP_ENV=staging,LOG_LEVEL=INFO \
  --concurrency=20 --max-instances=10 --min-instances=0 \
  --timeout=60s \
  --cpu=1 --memory=1Gi \
  --health-check=/live
```

Pool sizing check (Slice 3 residual): `db_pool_size=5`,
`db_pool_max_overflow=5` → worst case 10 conns/instance × 10
instances = 100 ≪ Cloud SQL default max_connections. Record the
actual instance limit alongside.

## 5. Qualify (evidence for every line)

```bash
BASE=https://$RUN_SERVICE-<hash>-<region>.run.app
SERVICE_URL=$BASE FINSIGHT_TEST_DSN="<app-dsn>" uv run pytest -q \
  tests/integration/test_ledger_rls.py \
  tests/integration/test_tenant_isolation.py \
  tests/integration/test_db_degradation.py \
  tests/integration/test_orphan_visibility.py \
  tests/integration/test_observations_api.py \
  tests/integration/test_stripe_idempotency_restart.py
curl -s $BASE/live                      # {"status":"alive"}
curl -s -o /dev/null -w "%{http_code}\n" $BASE/ready   # 200
```

| Check | Command / evidence | Pass criterion |
|---|---|---|
| Migrations at head | `alembic current` | `a3f6c1e8b2d4 (head)` |
| RLS on ledger | ledger suite (4) | pass as limited role |
| Tenant isolation | tenant suites | pass, no cross-tenant rows |
| Degradation | degradation suite | 200/503 matrix as coded |
| Orphans | orphan suite | interrupted visible, `''` invisible |
| Duplicates | idempotency restart | one row, one result |
| Storage | write-then-read tenant-keyed object; revoke test | private, tenant-scoped |
| Recovery | backup → restore to isolated instance → head + RLS + data | zero errors, invariants hold |
| Secrets | `gcloud run services describe` env dump | no secret values, only references |
| Logs | emit + inspect | no PII/secrets, request IDs present |

## 6. Cleanup / teardown

```bash
gcloud run services delete $RUN_SERVICE --project=$GCP_PROJECT --region=$GCP_REGION --quiet
gcloud sql instances delete $SQL_INSTANCE --project=$GCP_PROJECT --quiet
gcloud storage rm --recursive $BUCKET --project=$GCP_PROJECT
# Secrets: destroy versions when staging is torn down, or retain with rotation noted.
```

## Stop rule

Any row above failing on managed infrastructure is a release
blocker: stop, fix, re-run from step 3. Local success is never
substituted for a managed result.
