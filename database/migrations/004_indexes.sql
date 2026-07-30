-- 004_indexes.sql: Create performance indexes
-- Based on docs/10-schema/indexes.md and docs/12-database/constraints.md

-- Note: CREATE INDEX CONCURRENTLY cannot run inside a transaction block.
-- For small/fresh databases, regular CREATE INDEX IF NOT EXISTS is safe.

-- ============================================================================
-- actuals — Core variance query covering index
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_actuals_entity_period
    ON actuals (entity_id, period);
CREATE INDEX IF NOT EXISTS idx_actuals_account_period
    ON actuals (account_id, period);
CREATE INDEX IF NOT EXISTS idx_actuals_variance
    ON actuals (entity_id, period, account_id) INCLUDE (amount);

-- ============================================================================
-- trial_balance
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_tb_entity_period
    ON trial_balance (entity_id, period);
CREATE INDEX IF NOT EXISTS idx_tb_account_period
    ON trial_balance (account_id, period);
CREATE INDEX IF NOT EXISTS idx_tb_entity_period_account
    ON trial_balance (entity_id, period, account_id) INCLUDE (balance);
CREATE INDEX IF NOT EXISTS idx_tb_non_zero
    ON trial_balance (entity_id, period)
    WHERE debit != 0 OR credit != 0;

-- ============================================================================
-- budget_lines
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_budget_entity_period
    ON budget_lines (entity_id, period);
CREATE INDEX IF NOT EXISTS idx_budget_entity_period_account
    ON budget_lines (entity_id, period, account_id);

-- ============================================================================
-- forecast_lines
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_forecast_entity_period
    ON forecast_lines (entity_id, period);
CREATE INDEX IF NOT EXISTS idx_forecast_entity_period_account
    ON forecast_lines (entity_id, period, account_id, version);

-- ============================================================================
-- gl_accounts
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_gl_entity
    ON gl_accounts (entity_id);
CREATE INDEX IF NOT EXISTS idx_gl_type
    ON gl_accounts (account_type);

-- ============================================================================
-- headcount_data
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_hc_entity_period
    ON headcount_data (entity_id, period);

-- ============================================================================
-- vendor_invoices
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_invoices_entity_period
    ON vendor_invoices (entity_id, period);
CREATE INDEX IF NOT EXISTS idx_invoices_status
    ON vendor_invoices (status)
    WHERE status IN ('draft', 'submitted', 'disputed');

-- ============================================================================
-- sales_pipeline
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_pipeline_entity_stage
    ON sales_pipeline (entity_id, stage);
CREATE INDEX IF NOT EXISTS idx_pipeline_active
    ON sales_pipeline (entity_id)
    WHERE stage NOT IN ('closed_won', 'closed_lost');

-- ============================================================================
-- agent_runs
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_agent_entity_period
    ON agent_runs (entity_id, period);
CREATE INDEX IF NOT EXISTS idx_agent_active
    ON agent_runs (status)
    WHERE status NOT IN ('completed', 'failed');

-- ============================================================================
-- variances
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_var_material
    ON variances (agent_run_id)
    WHERE is_material = true;

-- ============================================================================
-- root_causes
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_rc_variance
    ON root_causes (variance_id);

-- ============================================================================
-- commentary_drafts
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_commentary_agent_run
    ON commentary_drafts (agent_run_id);

-- ============================================================================
-- scenarios
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_scenarios_agent_run
    ON scenarios (agent_run_id);

-- ============================================================================
-- review_logs
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_review_logs_agent_run
    ON review_logs (agent_run_id);

-- ============================================================================
-- review_decisions (PRD §7)
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_review_decisions_period
    ON review_decisions (tenant_id, period);

-- ============================================================================
-- action_items (PRD §7)
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_action_items_open
    ON action_items (tenant_id, period)
    WHERE status IN ('proposed', 'approved', 'in_progress', 'blocked');

-- ============================================================================
-- commentary_versions (PRD §7)
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_commentary_versions_period
    ON commentary_versions (tenant_id, period);

-- ============================================================================
-- audit_logs (PRD §7) — BRIN for time-series
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_audit_tenant_period
    ON audit_logs (tenant_id, period);
CREATE INDEX IF NOT EXISTS idx_audit_created_brin
    ON audit_logs USING BRIN (created_at) WITH (pages_per_range = 32);
CREATE INDEX IF NOT EXISTS idx_audit_event_type
    ON audit_logs (tenant_id, event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_user
    ON audit_logs (user_id, created_at DESC)
    WHERE user_id IS NOT NULL;

-- ============================================================================
-- pipeline_runs (PRD §7)
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_active
    ON pipeline_runs (tenant_id, period)
    WHERE status IN ('pending', 'running');

-- ============================================================================
-- assertions_db (PRD §7)
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_assertions_type
    ON assertions_db (tenant_id, period, type);
CREATE INDEX IF NOT EXISTS idx_assertions_tenant_assertion
    ON assertions_db (tenant_id, assertion_id);

-- ============================================================================
-- tool_result_cache (PRD §7)
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_cache_expires
    ON tool_result_cache (expires_at);
CREATE INDEX IF NOT EXISTS idx_cache_lookup
    ON tool_result_cache (tool_name, query_fingerprint);

-- ============================================================================
-- data_quality_snapshots (PRD §7)
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_dq_snapshots_period
    ON data_quality_snapshots (tenant_id, period);

-- ============================================================================
-- policy_decision_logs (PRD §7)
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_policy_logs_period
    ON policy_decision_logs (tenant_id, period);

-- ============================================================================
-- bridge_analysis_results (PRD §7)
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_bridge_period
    ON bridge_analysis_results (tenant_id, period);
CREATE INDEX IF NOT EXISTS idx_bridge_account
    ON bridge_analysis_results (tenant_id, account_id, period);

-- ============================================================================
-- variance_snapshots (PRD §7)
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_var_snapshots_material
    ON variance_snapshots (tenant_id, period)
    WHERE is_material = true;
CREATE INDEX IF NOT EXISTS idx_var_snapshots_account
    ON variance_snapshots (tenant_id, account_id);

-- ============================================================================
-- root_cause_findings_db (PRD §7)
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_findings_period
    ON root_cause_findings_db (tenant_id, period);
CREATE INDEX IF NOT EXISTS idx_findings_account
    ON root_cause_findings_db (tenant_id, account_id);
