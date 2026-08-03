-- 009_identity.sql: Identity model — Organization → Tenant → User → Role
-- Phase 1 (reduced identity scope) of docs/14-platform/implementation-plan.md.
--
-- Rows in these tables are owned by the platform (not tenant-scoped via RLS yet);
-- RLS policies for identity tables arrive in a later Phase-1 migration. The
-- tenant boundary is captured by tenants.id and the tenant_id FKs on users/roles.
--
-- Seeded deterministically by shared/utils/seed.py (seed_all / seed_tenant).

BEGIN;

-- citext is used for case-insensitive unique codes/emails. 001 only installs
-- pgcrypto + btree_gist, so ensure citext is present (idempotent).
CREATE EXTENSION IF NOT EXISTS citext;

-- ============================================================================
-- 1. organizations — legal entity umbrella (global, not tenant-scoped)
-- ============================================================================
CREATE TABLE IF NOT EXISTS organizations (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    code        citext NOT NULL UNIQUE,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- ============================================================================
-- 2. tenants — the RLS partitioning boundary for all tenant-scoped tables
-- ============================================================================
CREATE TABLE IF NOT EXISTS tenants (
    id                         uuid PRIMARY KEY,
    organization_id            uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name                       text NOT NULL,
    code                       citext NOT NULL UNIQUE,
    currency_code              char(3) NOT NULL CHECK (currency_code ~ '^[A-Z]{3}$'),
    fiscal_year_start_month    integer NOT NULL CHECK (fiscal_year_start_month BETWEEN 1 AND 12),
    default_materiality_amount numeric(20, 2) NOT NULL,
    default_materiality_pct    numeric(5, 2) NOT NULL,
    approval_limits            jsonb,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now()
);

-- ============================================================================
-- 3. users — platform actors scoped to exactly one tenant
-- ============================================================================
CREATE TABLE IF NOT EXISTS users (
    id           uuid PRIMARY KEY,
    tenant_id    uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email        citext NOT NULL,
    display_name text,
    active       boolean NOT NULL DEFAULT true,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, email)
);

-- ============================================================================
-- 4. roles — fixed RBAC role set, defined per tenant
-- ============================================================================
CREATE TABLE IF NOT EXISTS roles (
    id          uuid PRIMARY KEY,
    tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name        text NOT NULL CHECK (name IN ('analyst', 'manager', 'director', 'cfo')),
    description text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);

-- ============================================================================
-- 5. user_roles — many-to-many join (composite PK)
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_roles (
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);

-- ============================================================================
-- 6. Indexes — every FK column plus documented lookup patterns
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_tenants_organization_id ON tenants (organization_id);
CREATE INDEX IF NOT EXISTS idx_users_tenant_id ON users (tenant_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);
CREATE INDEX IF NOT EXISTS idx_roles_tenant_id ON roles (tenant_id);
CREATE INDEX IF NOT EXISTS idx_user_roles_role_id ON user_roles (role_id);

-- ============================================================================
-- 7. updated_at maintenance (fn_update_updated_at defined in 008_state_machines.sql)
-- ============================================================================
CREATE TRIGGER trg_organizations_updated_at
    BEFORE UPDATE ON organizations
    FOR EACH ROW EXECUTE FUNCTION fn_update_updated_at();

CREATE TRIGGER trg_tenants_updated_at
    BEFORE UPDATE ON tenants
    FOR EACH ROW EXECUTE FUNCTION fn_update_updated_at();

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION fn_update_updated_at();

CREATE TRIGGER trg_roles_updated_at
    BEFORE UPDATE ON roles
    FOR EACH ROW EXECUTE FUNCTION fn_update_updated_at();

COMMIT;
