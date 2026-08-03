-- 006_rls.sql: Enable Row-Level Security and create tenant isolation policies
-- Based on docs/12-database/rls.md

-- ============================================================================
-- Step 1: Enable RLS on all tenant-scoped tables
-- ============================================================================

-- Legacy tables (entity_id boundary)
ALTER TABLE entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE gl_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE trial_balance ENABLE ROW LEVEL SECURITY;
ALTER TABLE budget_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE forecast_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE actuals ENABLE ROW LEVEL SECURITY;
ALTER TABLE headcount_data ENABLE ROW LEVEL SECURITY;
ALTER TABLE vendor_invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE sales_pipeline ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE variances ENABLE ROW LEVEL SECURITY;
ALTER TABLE root_causes ENABLE ROW LEVEL SECURITY;
ALTER TABLE commentary_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE scenarios ENABLE ROW LEVEL SECURITY;
ALTER TABLE review_logs ENABLE ROW LEVEL SECURITY;

-- PRD §7 tables (tenant_id boundary)
ALTER TABLE review_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE action_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE commentary_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE assertions_db ENABLE ROW LEVEL SECURITY;
ALTER TABLE tool_result_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_quality_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE policy_decision_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE bridge_analysis_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE variance_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE root_cause_findings_db ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- Step 2: Create tenant isolation policies
-- ============================================================================

-- 2a: Legacy tables — direct entity_id comparison
CREATE POLICY p_tenant_isolation_entities ON entities
    FOR ALL
    USING (id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_gl_accounts ON gl_accounts
    FOR ALL
    USING (entity_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_trial_balance ON trial_balance
    FOR ALL
    USING (entity_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_budget_lines ON budget_lines
    FOR ALL
    USING (entity_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_forecast_lines ON forecast_lines
    FOR ALL
    USING (entity_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_actuals ON actuals
    FOR ALL
    USING (entity_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_headcount ON headcount_data
    FOR ALL
    USING (entity_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_invoices ON vendor_invoices
    FOR ALL
    USING (entity_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_pipeline ON sales_pipeline
    FOR ALL
    USING (entity_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_agent_runs ON agent_runs
    FOR ALL
    USING (entity_id = current_setting('app.tenant_id')::text);

-- 2b: Legacy tables — JOIN through agent_runs.entity_id
CREATE POLICY p_tenant_isolation_variances ON variances
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM agent_runs ar
            WHERE ar.id = variances.agent_run_id
              AND ar.entity_id = current_setting('app.tenant_id')::text
        )
    );

CREATE POLICY p_tenant_isolation_root_causes ON root_causes
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM variances v
            JOIN agent_runs ar ON ar.id = v.agent_run_id
            WHERE v.id = root_causes.variance_id
              AND ar.entity_id = current_setting('app.tenant_id')::text
        )
    );

CREATE POLICY p_tenant_isolation_commentary ON commentary_drafts
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM agent_runs ar
            WHERE ar.id = commentary_drafts.agent_run_id
              AND ar.entity_id = current_setting('app.tenant_id')::text
        )
    );

CREATE POLICY p_tenant_isolation_scenarios ON scenarios
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM agent_runs ar
            WHERE ar.id = scenarios.agent_run_id
              AND ar.entity_id = current_setting('app.tenant_id')::text
        )
    );

CREATE POLICY p_tenant_isolation_review_logs ON review_logs
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM agent_runs ar
            WHERE ar.id = review_logs.agent_run_id
              AND ar.entity_id = current_setting('app.tenant_id')::text
        )
    );

-- 2c: PRD §7 tables — direct tenant_id comparison
CREATE POLICY p_tenant_isolation_review_decisions ON review_decisions
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_action_items ON action_items
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_commentary_versions ON commentary_versions
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_audit_logs ON audit_logs
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_pipeline_runs ON pipeline_runs
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_assertions ON assertions_db
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_cache ON tool_result_cache
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_dq_snapshots ON data_quality_snapshots
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_policy_logs ON policy_decision_logs
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_bridge ON bridge_analysis_results
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_var_snapshots ON variance_snapshots
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_findings ON root_cause_findings_db
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::text);
