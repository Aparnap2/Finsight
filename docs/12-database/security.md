# Database Security — Encryption, Roles, Secrets

> **Layer:** 5 (Database Constraints)  
> **Scope:** PostgreSQL 15-alpine deployment in docker-compose  
> **Design Principle:** Defense-in-depth. Encryption, least privilege, and secrets management work together — no single layer is a panacea.

---

## 1. Encryption at Rest

### 1.1 PostgreSQL 15-alpine Limitation

The official `postgres:15-alpine` image does not include `pg_tde` (Transparent Data Encryption) or filesystem-level encryption. Therefore, encryption at rest must be handled at the infrastructure layer.

### 1.2 Recommended Approach: Filesystem-Level Encryption

```yaml
# docker-compose.yml — overlay for production
services:
  postgres:
    image: postgres:15-alpine
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: finsight
      POSTGRES_USER: finsight
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    # Production overlay:
    # - Mount encrypted filesystem volume (LUKS / dm-crypt)
    # - Or use EBS encryption (AWS) / managed disk encryption (GCP/Azure)
```

**Production checklist:**

| Layer | Technology | Responsibility |
|-------|-----------|---------------|
| Disk | LUKS/dm-crypt or cloud-provider encryption | Infrastructure / DevOps |
| Filesystem | ext4 or xfs with encryption support | Infrastructure / DevOps |
| PostgreSQL data | Encrypted automatically when filesystem is encrypted | None (transparent) |
| WAL | Encrypted automatically (same filesystem) | None (transparent) |
| Temp files | Encrypted automatically | None (transparent) |

### 1.3 Column-Level Encryption (pgcrypto)

For highly sensitive columns that need application-layer encryption:

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Encrypt sensitive vendor information
UPDATE vendor_invoices
SET vendor_name = pgp_sym_encrypt(vendor_name, current_setting('app.encryption_key'))
WHERE id = 'some-invoice-id';

-- Decrypt when reading
SELECT pgp_sym_decrypt(vendor_name, current_setting('app.encryption_key')) AS vendor_name
FROM vendor_invoices;
```

**Tables with sensitive data that may need column-level encryption:**

| Table | Sensitive Columns | Recommendation |
|-------|------------------|---------------|
| `vendor_invoices` | vendor_name | Encrypt at rest (filesystem) is sufficient |
| `headcount_data` | total_compensation | Encrypt at rest is sufficient |
| `root_causes` | evidence_json | May contain PII — review before enabling |
| `action_items` | description, cited_assertion_ids | Encrypt at rest is sufficient |
| `commentary_versions` | content | May contain business-sensitive commentary |

**Decision:** Column-level encryption adds query complexity and prevents indexing. Use filesystem-level encryption for all data at rest. Only use column-level encryption for specific compliance requirements (e.g., PII in `evidence_json`).

---

## 2. TLS Enforcement

### 2.1 PostgreSQL TLS Configuration

```conf
# postgresql.conf — TLS settings
ssl = on
ssl_cert_file = '/etc/ssl/certs/server.crt'
ssl_key_file = '/etc/ssl/private/server.key'
ssl_ca_file = '/etc/ssl/certs/ca.crt'
ssl_min_protocol_version = 'TLSv1.3'
ssl_ciphers = 'HIGH:!aNULL:!eNULL:!MD5'
ssl_prefer_server_ciphers = on

# Require TLS for all connections
hostssl all all 0.0.0.0/0 md5
# Remove any non-SSL host entries
# host    all all 0.0.0.0/0 md5  ← DELETE THIS LINE
```

### 2.2 Docker Compose TLS Setup

```yaml
# docker-compose.production.yml overlay
services:
  postgres:
    volumes:
      - ./certs/server.crt:/etc/ssl/certs/server.crt:ro
      - ./certs/server.key:/etc/ssl/private/server.key:ro
      - ./certs/ca.crt:/etc/ssl/certs/ca.crt:ro
      - ./postgresql.prod.conf:/etc/postgresql/postgresql.conf:ro
    command:
      - "-c"
      - "config_file=/etc/postgresql/postgresql.conf"
```

### 2.3 Application TLS Configuration

```python
# config.py — TLS connection string
settings.postgres_uri = "postgresql://finsight:finsight@localhost:5432/finsight?sslmode=verify-full&sslrootcert=./certs/ca.crt"
```

| SSL Mode | When to Use |
|----------|-------------|
| `disable` | Never — local development only |
| `prefer` | Development with occasional TLS |
| `require` | Production minimum |
| `verify-ca` | Production — verify server cert is signed by trusted CA |
| `verify-full` | **Recommended** — verify server hostname matches cert |

### 2.4 Certificate Rotation

```bash
# Generate new self-signed CA and server certs (production should use proper CA)
openssl req -new -x509 -days 365 -nodes -text -out ca.crt \
  -subj "/CN=FinSightCA"
openssl req -new -nodes -text -out server.csr \
  -subj "/CN=*.finsight.internal"
openssl x509 -req -in server.csr -days 365 -CA ca.crt -CAkey ca.key \
  -CAcreateserial -out server.crt

# Rotate: generate new certs, update volumes, restart PostgreSQL
# Add to calendar: certificate expiry check every 60 days
```

---

## 3. Least Privilege Roles

### 3.1 Role Hierarchy

```
                    ┌──────────────────┐
                    │  finsight_admin   │  BYPASSRLS, CREATEDB, CREATEROLE
                    └────────┬─────────┘
                             │
                    ┌──────────────────┐
                    │   finsight_owner  │  Table owner (DDL changes)
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────┴───────┐ ┌───┴──────┐ ┌─────┴──────┐
     │  finsight_app   │ │ finsight_│ │ finsight_   │
     │ (read/write)    │ │ reader   │ │ migration   │
     └────────────────┘ └──────────┘ └────────────┘
```

### 3.2 Role Definitions

```sql
-- 1. Admin role — schema changes, user management
CREATE ROLE finsight_admin WITH
    LOGIN
    SUPERUSER NOCREATEDB CREATEROLE CREATEREPLICATION
    BYPASSRLS
    PASSWORD '<admin-password>';

-- 2. Owner role — owns all FinSight objects
CREATE ROLE finsight_owner WITH
    LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE
    INHERIT
    PASSWORD '<owner-password>';

-- 3. Application role — daily read/write operations
CREATE ROLE finsight_app WITH
    LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOBYPASSRLS
    INHERIT
    PASSWORD '<app-password>';

-- 4. Read-only role — reporting, dashboards, analytics
CREATE ROLE finsight_reader WITH
    LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOBYPASSRLS
    INHERIT
    PASSWORD '<reader-password>';

-- 5. Migration role — Alembic/schema migrations
CREATE ROLE finsight_migration WITH
    LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOBYPASSRLS
    INHERIT
    PASSWORD '<migration-password>';
```

### 3.3 Schema-Level Privileges

```sql
-- Grant schema usage to all roles
GRANT USAGE ON SCHEMA public TO finsight_owner;
GRANT USAGE ON SCHEMA public TO finsight_app;
GRANT USAGE ON SCHEMA public TO finsight_reader;
GRANT ALL ON SCHEMA public TO finsight_admin;

-- Owner: full DDL control
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO finsight_owner;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO finsight_owner;

-- Application role: SELECT, INSERT, UPDATE on financial tables
-- (DELETE not granted — use soft-delete or status change)
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO finsight_app;
REVOKE DELETE ON ALL TABLES IN SCHEMA public FROM finsight_app;

-- Reader role: read-only
GRANT SELECT ON ALL TABLES IN SCHEMA public TO finsight_reader;

-- Migration role: DDL + data changes
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO finsight_migration;
```

### 3.4 Revoke DELETE from Application Role

```sql
-- Explicitly revoke DELETE from all tables
DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOR tbl IN
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public'
          AND tablename NOT IN ('audit_logs')  -- already blocked by trigger
    LOOP
        EXECUTE format('REVOKE DELETE ON %I FROM finsight_app', tbl);
    END LOOP;
END $$;
```

### 3.5 Default Privileges for Future Tables

```sql
-- Ensure new tables created by migration role get correct permissions
ALTER DEFAULT PRIVILEGES FOR ROLE finsight_migration IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE ON TABLES TO finsight_app;

ALTER DEFAULT PRIVILEGES FOR ROLE finsight_migration IN SCHEMA public
    GRANT SELECT ON TABLES TO finsight_reader;

-- Revoke DELETE by default
ALTER DEFAULT PRIVILEGES FOR ROLE finsight_migration IN SCHEMA public
    REVOKE DELETE ON TABLES FROM finsight_app;
```

### 3.6 Row-Level Privileges (Column Security)

For tables with PII or sensitive financial data:

```sql
-- Create a view that exposes non-sensitive columns only
CREATE VIEW public_gl_accounts AS
SELECT id, account_number, account_name, account_type
FROM gl_accounts;

-- Grant reader access to the view only
GRANT SELECT ON public_gl_accounts TO finsight_reader;
REVOKE SELECT ON gl_accounts FROM finsight_reader;
```

---

## 4. Secrets Manager Integration

### 4.1 HashiCorp Vault Integration

```python
# shared/config/vault.py
import hvac
from functools import lru_cache

@lru_cache()
def get_db_credentials() -> dict:
    """Fetch ephemeral database credentials from Vault."""
    client = hvac.Client(
        url=settings.vault_url,
        token=settings.vault_token,
    )
    creds = client.secrets.database.generate_credentials(
        mount_point="postgres",
        role_name="finsight_app",
    )
    return {
        "username": creds["data"]["username"],
        "password": creds["data"]["password"],
    }
```

### 4.2 AWS Secrets Manager / GCP Secret Manager

```python
# shared/config/secrets.py
import boto3
from botocore.exceptions import ClientError

def get_db_password() -> str:
    """Fetch database password from AWS Secrets Manager."""
    session = boto3.session.Session()
    client = session.client(service_name="secretsmanager")

    try:
        response = client.get_secret_value(SecretId="finsight/postgres")
        return json.loads(response["SecretString"])["password"]
    except ClientError as e:
        logger.error("Failed to fetch database secret: %s", e)
        raise
```

### 4.3 Environment Variables (Development Only)

```env
# .env — NEVER commit to version control
POSTGRES_URI=postgresql://finsight_app:${DB_PASSWORD}@localhost:5432/finsight?sslmode=verify-full
DB_PASSWORD=<rotated-password>
```

### 4.4 Password Rotation Strategy

| Password | Rotation Frequency | Method |
|----------|-------------------|--------|
| `finsight_admin` | Every 90 days | Manual (break-glass procedure) |
| `finsight_owner` | Every 90 days | Manual |
| `finsight_app` | Every 30 days | Automated via Vault dynamic secrets |
| `finsight_reader` | Every 180 days | Manual |

---

## 5. Network Security

### 5.1 Docker Compose Network Isolation

```yaml
# docker-compose.yml — network configuration
services:
  postgres:
    networks:
      - finsight_backend
    # No port mapping in production — only accessible via internal network
    # ports: ["5432:5432"]  ← REMOVE in production

  compute-runtime:
    networks:
      - finsight_backend

networks:
  finsight_backend:
    internal: true  # No external access to backend network
```

### 5.2 pg_hba.conf Rules

```conf
# pg_hba.conf — host-based authentication
# TYPE  DATABASE  USER            ADDRESS          METHOD

# Local admin access (Unix socket only)
local   all       finsight_admin                    peer

# Application connections (internal Docker network)
hostssl finsight  finsight_app   172.16.0.0/12     md5
hostssl finsight  finsight_reader 172.16.0.0/12    md5

# Migration connections (CI/CD runner IP)
hostssl finsight  finsight_migration 10.0.0.0/8    md5

# Deny everything else
hostssl all       all             0.0.0.0/0        reject
```

---

## 6. Audit Logging for Security Events

### 6.1 PostgreSQL Audit Extension (pgaudit)

```sql
-- Requires pgaudit extension (not available in alpine by default)
-- If using timescaledb/postgres image:
CREATE EXTENSION IF NOT EXISTS pgaudit;

-- postgresql.conf
shared_preload_libraries = 'pgaudit'
pgaudit.log = 'write,ddl,role'
pgaudit.log_level = 'notice'
pgaudit.log_catalog = off
pgaudit.log_relation = on
```

### 6.2 Connection Logging

```conf
# postgresql.conf
log_connections = on
log_disconnections = on
log_line_prefix = '%t [%p]: [%r] %u@%d '
log_hostname = on
```

### 6.3 Failed Authentication Alerts

```sql
-- Query to check for brute-force attempts
SELECT
    regexp_replace(message, '.*user="([^"]+)".*', '\1') AS username,
    regexp_replace(message, '.*host="([^"]+)".*', '\1') AS host,
    COUNT(*) AS attempts,
    MIN(log_time) AS first_attempt,
    MAX(log_time) AS last_attempt
FROM pg_log
WHERE message LIKE '%password authentication failed%'
  AND log_time >= NOW() - INTERVAL '1 hour'
GROUP BY 1, 2
HAVING COUNT(*) > 5;
```

---

## 7. Security Incident Response

### 7.1 Break-Glass Procedure

```bash
# 1. Promote read-replica to isolate primary
# 2. Revoke all application credentials
psql -h localhost -U finsight_admin -d finsight \
  -c "ALTER ROLE finsight_app WITH PASSWORD '$(openssl rand -base64 32)';"

# 3. Audit all recent changes
psql -h localhost -U finsight_admin -d finsight \
  -c "SELECT * FROM audit_logs WHERE created_at >= NOW() - INTERVAL '24 hours' ORDER BY created_at DESC;"

# 4. Enable superuser-only access
psql -h localhost -U finsight_admin -d finsight \
  -c "REVOKE CONNECT ON DATABASE finsight FROM PUBLIC;"
```

### 7.2 Readiness Checklist

| Item | Status | Owner |
|------|--------|-------|
| Filesystem encryption confirmed | ☐ | DevOps |
| TLS v1.3 enforced | ☐ | DevOps |
| Certificate rotation schedule active | ☐ | DevOps |
| `finsight_app` DELETE revoked | ☐ | DBA |
| `finsight_reader` read-only verified | ☐ | DBA |
| Vault dynamic credentials integrated | ☐ | Platform |
| pgaudit configured | ☐ | DBA |
| Connection logging enabled | ☐ | DBA |
| Network isolation verified | ☐ | DevOps |
| Break-glass procedure documented | ☐ | Security |
| Password rotation schedule created | ☐ | Security |
