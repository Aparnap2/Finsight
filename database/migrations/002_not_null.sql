-- 002_not_null.sql: Add NOT NULL constraints
-- Based on docs/12-database/constraints.md and docs/12-database/migrations.md

BEGIN;

-- Validate existing data first (safety check)
DO $$
DECLARE
    violations TEXT[];
    v_count INT;
BEGIN
    SELECT COUNT(*) INTO v_count FROM entities WHERE name IS NULL;
    IF v_count > 0 THEN violations := violations || format('entities.name: %s nulls', v_count); END IF;

    SELECT COUNT(*) INTO v_count FROM gl_accounts WHERE entity_id IS NULL;
    IF v_count > 0 THEN violations := violations || format('gl_accounts.entity_id: %s nulls', v_count); END IF;

    SELECT COUNT(*) INTO v_count FROM trial_balance WHERE period IS NULL;
    IF v_count > 0 THEN violations := violations || format('trial_balance.period: %s nulls', v_count); END IF;

    SELECT COUNT(*) INTO v_count FROM budget_lines WHERE amount IS NULL;
    IF v_count > 0 THEN violations := violations || format('budget_lines.amount: %s nulls', v_count); END IF;

    SELECT COUNT(*) INTO v_count FROM forecast_lines WHERE amount IS NULL OR version IS NULL;
    IF v_count > 0 THEN violations := violations || format('forecast_lines.amount/version: %s nulls', v_count); END IF;

    SELECT COUNT(*) INTO v_count FROM actuals WHERE amount IS NULL;
    IF v_count > 0 THEN violations := violations || format('actuals.amount: %s nulls', v_count); END IF;

    SELECT COUNT(*) INTO v_count FROM vendor_invoices WHERE amount IS NULL OR invoice_date IS NULL;
    IF v_count > 0 THEN violations := violations || format('vendor_invoices: %s nulls', v_count); END IF;

    SELECT COUNT(*) INTO v_count FROM sales_pipeline WHERE stage IS NULL OR expected_close_date IS NULL;
    IF v_count > 0 THEN violations := violations || format('sales_pipeline: %s nulls', v_count); END IF;

    SELECT COUNT(*) INTO v_count FROM agent_runs WHERE status IS NULL OR started_at IS NULL;
    IF v_count > 0 THEN violations := violations || format('agent_runs: %s nulls', v_count); END IF;

    SELECT COUNT(*) INTO v_count FROM variances WHERE agent_run_id IS NULL OR account_id IS NULL;
    IF v_count > 0 THEN violations := violations || format('variances: %s nulls', v_count); END IF;

    SELECT COUNT(*) INTO v_count FROM root_causes WHERE variance_id IS NULL OR summary IS NULL;
    IF v_count > 0 THEN violations := violations || format('root_causes: %s nulls', v_count); END IF;

    IF array_length(violations, 1) > 0 THEN
        RAISE EXCEPTION 'NOT NULL violations found: %', array_to_string(violations, '; ');
    ELSE
        RAISE NOTICE 'All NOT NULL checks pass -- proceeding with constraints.';
    END IF;
END $$;

-- Fix default values for nullable columns with defaults
UPDATE trial_balance SET debit = 0 WHERE debit IS NULL;
UPDATE trial_balance SET credit = 0 WHERE credit IS NULL;
UPDATE headcount_data SET headcount = 0 WHERE headcount IS NULL;
UPDATE headcount_data SET total_compensation = 0 WHERE total_compensation IS NULL;
UPDATE headcount_data SET new_hires = 0 WHERE new_hires IS NULL;
UPDATE headcount_data SET departures = 0 WHERE departures IS NULL;

-- Apply NOT NULL constraints — entities
ALTER TABLE entities
    ALTER COLUMN currency SET NOT NULL,
    ALTER COLUMN fiscal_year_start SET NOT NULL;

-- gl_accounts
ALTER TABLE gl_accounts
    ALTER COLUMN account_number SET NOT NULL,
    ALTER COLUMN account_name SET NOT NULL,
    ALTER COLUMN account_type SET NOT NULL;

-- trial_balance
ALTER TABLE trial_balance
    ALTER COLUMN debit SET NOT NULL,
    ALTER COLUMN credit SET NOT NULL;

-- budget_lines (entity_id, period, account_id already NOT NULL from CREATE TABLE)
ALTER TABLE budget_lines
    ALTER COLUMN entity_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN account_id SET NOT NULL;

-- forecast_lines
ALTER TABLE forecast_lines
    ALTER COLUMN entity_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN account_id SET NOT NULL,
    ALTER COLUMN version SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

-- actuals
ALTER TABLE actuals
    ALTER COLUMN entity_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN account_id SET NOT NULL;

-- headcount_data
ALTER TABLE headcount_data
    ALTER COLUMN entity_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN headcount SET NOT NULL,
    ALTER COLUMN total_compensation SET NOT NULL,
    ALTER COLUMN new_hires SET NOT NULL,
    ALTER COLUMN departures SET NOT NULL;

-- vendor_invoices
ALTER TABLE vendor_invoices
    ALTER COLUMN entity_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN vendor_name SET NOT NULL,
    ALTER COLUMN account_id SET NOT NULL,
    ALTER COLUMN invoice_date SET NOT NULL;

-- sales_pipeline
ALTER TABLE sales_pipeline
    ALTER COLUMN entity_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN deal_name SET NOT NULL,
    ALTER COLUMN stage SET NOT NULL,
    ALTER COLUMN expected_close_date SET NOT NULL;

-- agent_runs
ALTER TABLE agent_runs
    ALTER COLUMN entity_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN status SET NOT NULL,
    ALTER COLUMN started_at SET NOT NULL;

-- variances
ALTER TABLE variances
    ALTER COLUMN agent_run_id SET NOT NULL,
    ALTER COLUMN account_id SET NOT NULL,
    ALTER COLUMN actual_amount SET NOT NULL,
    ALTER COLUMN budget_amount SET NOT NULL,
    ALTER COLUMN is_material SET NOT NULL,
    ALTER COLUMN classification SET NOT NULL;

-- root_causes
ALTER TABLE root_causes
    ALTER COLUMN variance_id SET NOT NULL,
    ALTER COLUMN summary SET NOT NULL;

-- commentary_drafts
ALTER TABLE commentary_drafts
    ALTER COLUMN agent_run_id SET NOT NULL,
    ALTER COLUMN version SET NOT NULL,
    ALTER COLUMN status SET NOT NULL;

-- scenarios
ALTER TABLE scenarios
    ALTER COLUMN agent_run_id SET NOT NULL,
    ALTER COLUMN name SET NOT NULL;

-- review_logs
ALTER TABLE review_logs
    ALTER COLUMN agent_run_id SET NOT NULL,
    ALTER COLUMN checkpoint SET NOT NULL,
    ALTER COLUMN reviewer SET NOT NULL,
    ALTER COLUMN decision SET NOT NULL;

-- review_decisions (PRD §7)
ALTER TABLE review_decisions
    ALTER COLUMN decision SET NOT NULL,
    ALTER COLUMN reviewer SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

-- action_items (PRD §7)
ALTER TABLE action_items
    ALTER COLUMN status SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN updated_at SET NOT NULL;

-- commentary_versions (PRD §7)
ALTER TABLE commentary_versions
    ALTER COLUMN version SET NOT NULL,
    ALTER COLUMN status SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

-- audit_logs (PRD §7)
ALTER TABLE audit_logs
    ALTER COLUMN event_type SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

-- pipeline_runs (PRD §7)
ALTER TABLE pipeline_runs
    ALTER COLUMN status SET NOT NULL,
    ALTER COLUMN started_at SET NOT NULL;

-- assertions_db (PRD §7)
ALTER TABLE assertions_db
    ALTER COLUMN type SET NOT NULL,
    ALTER COLUMN text SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

-- tool_result_cache (PRD §7)
ALTER TABLE tool_result_cache
    ALTER COLUMN tool_name SET NOT NULL,
    ALTER COLUMN query_fingerprint SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN expires_at SET NOT NULL;

-- data_quality_snapshots (PRD §7)
ALTER TABLE data_quality_snapshots
    ALTER COLUMN overall_score SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

-- policy_decision_logs (PRD §7)
ALTER TABLE policy_decision_logs
    ALTER COLUMN autonomy_level SET NOT NULL,
    ALTER COLUMN routing_target SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

-- bridge_analysis_results (PRD §7)
ALTER TABLE bridge_analysis_results
    ALTER COLUMN created_at SET NOT NULL;

-- variance_snapshots (PRD §7)
ALTER TABLE variance_snapshots
    ALTER COLUMN is_material SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

-- root_cause_findings_db (PRD §7)
ALTER TABLE root_cause_findings_db
    ALTER COLUMN created_at SET NOT NULL;

COMMIT;
