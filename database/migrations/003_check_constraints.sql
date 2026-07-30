-- 003_check_constraints.sql: Add CHECK constraints (PG 15 compatible)
-- No outer BEGIN/COMMIT — each DO block is its own implicit transaction
-- so a single constraint failure doesn't abort everything else

-- Helper: DO block wraps ALTER TABLE ADD CONSTRAINT with IF NOT EXISTS check
-- PG 15 doesn't support ALTER TABLE ... ADD CONSTRAINT IF NOT EXISTS

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_entities_currency') THEN
        ALTER TABLE entities ADD CONSTRAINT chk_entities_currency CHECK (currency ~ '^[A-Z]{3}$');
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_entities_fiscal_year_start') THEN
        ALTER TABLE entities ADD CONSTRAINT chk_entities_fiscal_year_start CHECK (fiscal_year_start ~ '^(0[1-9]|1[0-2])(-(0[1-9]|[12][0-9]|3[01]))?$');
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_gl_accounts_type') THEN
        ALTER TABLE gl_accounts ADD CONSTRAINT chk_gl_accounts_type CHECK (account_type IN ('asset','liability','equity','revenue','expense','contra_asset','contra_liability','contra_equity','contra_revenue','contra_expense'));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_tb_period_format') THEN
        ALTER TABLE trial_balance ADD CONSTRAINT chk_tb_period_format CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$');
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_tb_debit_non_negative') THEN
        ALTER TABLE trial_balance ADD CONSTRAINT chk_tb_debit_non_negative CHECK (debit >= 0);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_tb_credit_non_negative') THEN
        ALTER TABLE trial_balance ADD CONSTRAINT chk_tb_credit_non_negative CHECK (credit >= 0);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_tb_not_both_positive') THEN
        ALTER TABLE trial_balance ADD CONSTRAINT chk_tb_not_both_positive CHECK (debit = 0 OR credit = 0);
    END IF;
END $$;

-- Convert trial_balance.balance to GENERATED ALWAYS
ALTER TABLE trial_balance DROP COLUMN IF EXISTS balance;
ALTER TABLE trial_balance ADD COLUMN balance NUMERIC(15,2) GENERATED ALWAYS AS (debit - credit) STORED;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_budget_period_format') THEN
        ALTER TABLE budget_lines ADD CONSTRAINT chk_budget_period_format CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$');
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_budget_amount_non_zero') THEN
        ALTER TABLE budget_lines ADD CONSTRAINT chk_budget_amount_non_zero CHECK (amount != 0);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_forecast_period_format') THEN
        ALTER TABLE forecast_lines ADD CONSTRAINT chk_forecast_period_format CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$');
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_forecast_amount_non_zero') THEN
        ALTER TABLE forecast_lines ADD CONSTRAINT chk_forecast_amount_non_zero CHECK (amount != 0);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_forecast_version_positive') THEN
        ALTER TABLE forecast_lines ADD CONSTRAINT chk_forecast_version_positive CHECK (version > 0);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_actuals_period_format') THEN
        ALTER TABLE actuals ADD CONSTRAINT chk_actuals_period_format CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$');
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_actuals_amount_non_zero') THEN
        ALTER TABLE actuals ADD CONSTRAINT chk_actuals_amount_non_zero CHECK (amount != 0);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_hc_period_format') THEN
        ALTER TABLE headcount_data ADD CONSTRAINT chk_hc_period_format CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$');
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_hc_headcount_non_negative') THEN
        ALTER TABLE headcount_data ADD CONSTRAINT chk_hc_headcount_non_negative CHECK (headcount >= 0);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_hc_compensation_non_negative') THEN
        ALTER TABLE headcount_data ADD CONSTRAINT chk_hc_compensation_non_negative CHECK (total_compensation >= 0);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_hc_new_hires_non_negative') THEN
        ALTER TABLE headcount_data ADD CONSTRAINT chk_hc_new_hires_non_negative CHECK (new_hires >= 0);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_hc_departures_non_negative') THEN
        ALTER TABLE headcount_data ADD CONSTRAINT chk_hc_departures_non_negative CHECK (departures >= 0);
    END IF;
END $$;

ALTER TABLE vendor_invoices ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'draft';

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_invoice_status') THEN
        ALTER TABLE vendor_invoices ADD CONSTRAINT chk_invoice_status CHECK (status IN ('draft','submitted','approved','paid','cancelled','disputed'));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_invoice_period_format') THEN
        ALTER TABLE vendor_invoices ADD CONSTRAINT chk_invoice_period_format CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$');
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_invoice_amount_positive') THEN
        ALTER TABLE vendor_invoices ADD CONSTRAINT chk_invoice_amount_positive CHECK (amount > 0);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_pipeline_period_format') THEN
        ALTER TABLE sales_pipeline ADD CONSTRAINT chk_pipeline_period_format CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$');
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_pipeline_amount_positive') THEN
        ALTER TABLE sales_pipeline ADD CONSTRAINT chk_pipeline_amount_positive CHECK (amount > 0);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_pipeline_stage') THEN
        ALTER TABLE sales_pipeline ADD CONSTRAINT chk_pipeline_stage CHECK (stage IN ('prospecting','qualification','proposal','negotiation','closed_won','closed_lost'));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_agentrun_period_format') THEN
        ALTER TABLE agent_runs ADD CONSTRAINT chk_agentrun_period_format CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$');
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_agentrun_status') THEN
        ALTER TABLE agent_runs ADD CONSTRAINT chk_agentrun_status CHECK (status IN ('pending','running','completed','failed','cancelled'));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_agentrun_times') THEN
        ALTER TABLE agent_runs ADD CONSTRAINT chk_agentrun_times CHECK (completed_at IS NULL OR completed_at > started_at);
    END IF;
END $$;

-- Convert variances to GENERATED ALWAYS
ALTER TABLE variances DROP COLUMN IF EXISTS variance_amount;
ALTER TABLE variances DROP COLUMN IF EXISTS variance_pct;
ALTER TABLE variances ADD COLUMN variance_amount NUMERIC(15,2) GENERATED ALWAYS AS (actual_amount - budget_amount) STORED;
ALTER TABLE variances ADD COLUMN variance_pct NUMERIC(8,4) GENERATED ALWAYS AS (CASE WHEN budget_amount != 0 THEN (actual_amount - budget_amount) / budget_amount END) STORED;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_var_confidence') THEN
        ALTER TABLE variances ADD CONSTRAINT chk_var_confidence CHECK (confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_var_classification') THEN
        ALTER TABLE variances ADD CONSTRAINT chk_var_classification CHECK (classification IN ('favorable','unfavorable','neutral','critical','non_material'));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_rc_confidence') THEN
        ALTER TABLE root_causes ADD CONSTRAINT chk_rc_confidence CHECK (confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_commentary_status') THEN
        ALTER TABLE commentary_drafts ADD CONSTRAINT chk_commentary_status CHECK (status IN ('draft','reviewed','approved','archived'));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_commentary_version_positive') THEN
        ALTER TABLE commentary_drafts ADD CONSTRAINT chk_commentary_version_positive CHECK (version > 0);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_scenario_probability') THEN
        ALTER TABLE scenarios ADD CONSTRAINT chk_scenario_probability CHECK (probability IN ('low','medium','high','very_high'));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_review_decision') THEN
        ALTER TABLE review_logs ADD CONSTRAINT chk_review_decision CHECK (decision IN ('approved','rejected','escalated','needs_revision'));
    END IF;
END $$;

-- PRD §7 tables
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_review_decision_v2') THEN
        ALTER TABLE review_decisions ADD CONSTRAINT chk_review_decision_v2 CHECK (decision IN ('approved','rejected','escalated'));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_review_confidence') THEN
        ALTER TABLE review_decisions ADD CONSTRAINT chk_review_confidence CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_action_status') THEN
        ALTER TABLE action_items ADD CONSTRAINT chk_action_status CHECK (status IN ('proposed','approved','in_progress','completed','cancelled','blocked'));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_action_verb') THEN
        ALTER TABLE action_items ADD CONSTRAINT chk_action_verb CHECK (action IN ('reduce','increase','optimize','restructure','maintain','investigate'));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_action_domain') THEN
        ALTER TABLE action_items ADD CONSTRAINT chk_action_domain CHECK (domain IN ('cost','revenue','margin','headcount','capex','working_capital'));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_action_updated_after_created') THEN
        ALTER TABLE action_items ADD CONSTRAINT chk_action_updated_after_created CHECK (updated_at >= created_at);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_commentary_version_v2_status') THEN
        ALTER TABLE commentary_versions ADD CONSTRAINT chk_commentary_version_v2_status CHECK (status IN ('draft','submitted','reviewed','approved'));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_commentary_version_v2_positive') THEN
        ALTER TABLE commentary_versions ADD CONSTRAINT chk_commentary_version_v2_positive CHECK (version > 0);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_audit_period_format') THEN
        ALTER TABLE audit_logs ADD CONSTRAINT chk_audit_period_format CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$');
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_audit_event_type') THEN
        ALTER TABLE audit_logs ADD CONSTRAINT chk_audit_event_type CHECK (event_type IN ('pipeline_started','pipeline_completed','pipeline_failed','assertion_created','assertion_validated','action_proposed','action_approved','action_rejected','commentary_submitted','commentary_reviewed','user_login','export_downloaded','config_changed','anomaly_detected','data_quality_alert','row_inserted','row_updated','row_deleted','rls_violation_attempted','admin_cross_tenant_access'));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_pipeline_status') THEN
        ALTER TABLE pipeline_runs ADD CONSTRAINT chk_pipeline_status CHECK (status IN ('pending','running','completed','failed'));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_pipeline_times') THEN
        ALTER TABLE pipeline_runs ADD CONSTRAINT chk_pipeline_times CHECK (completed_at IS NULL OR completed_at > started_at);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_pipelinerun_period_format') THEN
        ALTER TABLE pipeline_runs ADD CONSTRAINT chk_pipelinerun_period_format CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$');
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_assertion_type') THEN
        ALTER TABLE assertions_db ADD CONSTRAINT chk_assertion_type CHECK (type IN ('numeric','comparative','causal','forecast','quality'));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_assertion_support_level') THEN
        ALTER TABLE assertions_db ADD CONSTRAINT chk_assertion_support_level CHECK (support_level IS NULL OR support_level IN ('verified','probable','weak','contested'));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_assertion_confidence') THEN
        ALTER TABLE assertions_db ADD CONSTRAINT chk_assertion_confidence CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_cache_expiry') THEN
        ALTER TABLE tool_result_cache ADD CONSTRAINT chk_cache_expiry CHECK (expires_at > created_at);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_dq_score') THEN
        ALTER TABLE data_quality_snapshots ADD CONSTRAINT chk_dq_score CHECK (overall_score >= 0 AND overall_score <= 1);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_policy_autonomy') THEN
        ALTER TABLE policy_decision_logs ADD CONSTRAINT chk_policy_autonomy CHECK (autonomy_level IN ('autonomous','semi_autonomous','review_required','manual_only'));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_policy_routing') THEN
        ALTER TABLE policy_decision_logs ADD CONSTRAINT chk_policy_routing CHECK (routing_target IN ('auto_approve','human_review','escalate','block'));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_policy_confidence') THEN
        ALTER TABLE policy_decision_logs ADD CONSTRAINT chk_policy_confidence CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_bridge_confidence') THEN
        ALTER TABLE bridge_analysis_results ADD CONSTRAINT chk_bridge_confidence CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_finding_confidence') THEN
        ALTER TABLE root_cause_findings_db ADD CONSTRAINT chk_finding_confidence CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1));
    END IF;
END $$;
