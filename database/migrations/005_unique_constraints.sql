-- 005_unique_constraints.sql: Add UNIQUE constraints (PG 15 compatible)
-- No outer BEGIN/COMMIT — each statement is its own implicit transaction

-- gl_accounts — No duplicate account numbers within entity
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_gl_accounts_entity_number') THEN
        ALTER TABLE gl_accounts ADD CONSTRAINT uq_gl_accounts_entity_number UNIQUE (entity_id, account_number);
    END IF;
END $$;

-- trial_balance — One balance per account per period
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_tb_period_account') THEN
        ALTER TABLE trial_balance ADD CONSTRAINT uq_tb_period_account UNIQUE (entity_id, period, account_id);
    END IF;
END $$;

-- budget_lines — Partial unique indexes for nullable department
DROP INDEX IF EXISTS uq_budget_with_dept;
DROP INDEX IF EXISTS uq_budget_without_dept;
CREATE UNIQUE INDEX IF NOT EXISTS uq_budget_with_dept ON budget_lines (entity_id, period, account_id, department) WHERE department IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_budget_without_dept ON budget_lines (entity_id, period, account_id) WHERE department IS NULL;

-- forecast_lines
DROP INDEX IF EXISTS uq_forecast_with_dept;
DROP INDEX IF EXISTS uq_forecast_without_dept;
CREATE UNIQUE INDEX IF NOT EXISTS uq_forecast_with_dept ON forecast_lines (entity_id, period, account_id, department, version) WHERE department IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_forecast_without_dept ON forecast_lines (entity_id, period, account_id, version) WHERE department IS NULL;

-- actuals
DROP INDEX IF EXISTS uq_actuals_with_dept;
DROP INDEX IF EXISTS uq_actuals_without_dept;
CREATE UNIQUE INDEX IF NOT EXISTS uq_actuals_with_dept ON actuals (entity_id, period, account_id, department) WHERE department IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_actuals_without_dept ON actuals (entity_id, period, account_id) WHERE department IS NULL;

-- headcount_data
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_hc_period_dept') THEN
        ALTER TABLE headcount_data ADD CONSTRAINT uq_hc_period_dept UNIQUE (entity_id, period, department);
    END IF;
END $$;

-- vendor_invoices — Duplicate detection (date-only to avoid microsecond mismatch)
DROP INDEX IF EXISTS uq_invoice_dedup;
CREATE UNIQUE INDEX IF NOT EXISTS uq_invoice_dedup
    ON vendor_invoices (entity_id, vendor_name, period, amount, (invoice_date::date));

-- variances
DROP INDEX IF EXISTS uq_variance_with_dept;
DROP INDEX IF EXISTS uq_variance_without_dept;
CREATE UNIQUE INDEX IF NOT EXISTS uq_variance_with_dept ON variances (agent_run_id, account_id, department) WHERE department IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_variance_without_dept ON variances (agent_run_id, account_id) WHERE department IS NULL;

-- root_causes
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_root_cause_variance') THEN
        ALTER TABLE root_causes ADD CONSTRAINT uq_root_cause_variance UNIQUE (variance_id);
    END IF;
END $$;

-- review_decisions
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_review_assertion') THEN
        ALTER TABLE review_decisions ADD CONSTRAINT uq_review_assertion UNIQUE (tenant_id, period, assertion_id);
    END IF;
END $$;

-- commentary_versions
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_commentary_version') THEN
        ALTER TABLE commentary_versions ADD CONSTRAINT uq_commentary_version UNIQUE (tenant_id, period, version);
    END IF;
END $$;

-- assertions_db
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_assertion_id_per_period') THEN
        ALTER TABLE assertions_db ADD CONSTRAINT uq_assertion_id_per_period UNIQUE (tenant_id, period, assertion_id);
    END IF;
END $$;

-- tool_result_cache
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_cache_entry') THEN
        ALTER TABLE tool_result_cache ADD CONSTRAINT uq_cache_entry UNIQUE (tenant_id, tool_name, query_fingerprint);
    END IF;
END $$;
