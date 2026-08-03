-- 000_init.sql: Create base tables from ORM models
-- This bootstraps the database so enforcement migrations can be applied.
-- Generated from shared/models/database.py

BEGIN;

-- 1. entities — Legal entity / tenant boundary
CREATE TABLE IF NOT EXISTS entities (
    id              VARCHAR PRIMARY KEY,
    name            VARCHAR NOT NULL,
    currency        VARCHAR(3) DEFAULT 'USD',
    fiscal_year_start VARCHAR(5) DEFAULT '01'
);

-- 2. gl_accounts — Chart of accounts
CREATE TABLE IF NOT EXISTS gl_accounts (
    id              VARCHAR PRIMARY KEY,
    entity_id       VARCHAR NOT NULL REFERENCES entities(id),
    account_number  VARCHAR NOT NULL,
    account_name    VARCHAR NOT NULL,
    account_type    VARCHAR NOT NULL,
    department      VARCHAR,
    region          VARCHAR,
    product_line    VARCHAR
);

-- 3. trial_balance — Period-end balances
CREATE TABLE IF NOT EXISTS trial_balance (
    id              VARCHAR PRIMARY KEY,
    entity_id       VARCHAR NOT NULL REFERENCES entities(id),
    period          VARCHAR(7) NOT NULL,
    account_id      VARCHAR NOT NULL REFERENCES gl_accounts(id),
    debit           NUMERIC(15, 2) DEFAULT 0,
    credit          NUMERIC(15, 2) DEFAULT 0,
    balance         NUMERIC(15, 2) DEFAULT 0
);

-- 4. budget_lines — Budget data
CREATE TABLE IF NOT EXISTS budget_lines (
    id              VARCHAR PRIMARY KEY,
    entity_id       VARCHAR NOT NULL REFERENCES entities(id),
    period          VARCHAR(7) NOT NULL,
    account_id      VARCHAR NOT NULL REFERENCES gl_accounts(id),
    department      VARCHAR,
    amount          NUMERIC(15, 2) NOT NULL,
    notes           TEXT
);

-- 5. forecast_lines — Forecast data
CREATE TABLE IF NOT EXISTS forecast_lines (
    id              VARCHAR PRIMARY KEY,
    entity_id       VARCHAR NOT NULL REFERENCES entities(id),
    period          VARCHAR(7) NOT NULL,
    account_id      VARCHAR NOT NULL REFERENCES gl_accounts(id),
    department      VARCHAR,
    amount          NUMERIC(15, 2) NOT NULL,
    version         INTEGER DEFAULT 1,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- 6. actuals — Actual financial data
CREATE TABLE IF NOT EXISTS actuals (
    id              VARCHAR PRIMARY KEY,
    entity_id       VARCHAR NOT NULL REFERENCES entities(id),
    period          VARCHAR(7) NOT NULL,
    account_id      VARCHAR NOT NULL REFERENCES gl_accounts(id),
    department      VARCHAR,
    amount          NUMERIC(15, 2) NOT NULL
);

-- 7. headcount_data — People metrics
CREATE TABLE IF NOT EXISTS headcount_data (
    id                  VARCHAR PRIMARY KEY,
    entity_id           VARCHAR NOT NULL REFERENCES entities(id),
    period              VARCHAR(7) NOT NULL,
    department          VARCHAR NOT NULL,
    headcount           INTEGER DEFAULT 0,
    total_compensation  NUMERIC(15, 2) DEFAULT 0,
    new_hires           INTEGER DEFAULT 0,
    departures          INTEGER DEFAULT 0
);

-- 8. vendor_invoices — AP invoices
CREATE TABLE IF NOT EXISTS vendor_invoices (
    id              VARCHAR PRIMARY KEY,
    entity_id       VARCHAR NOT NULL REFERENCES entities(id),
    period          VARCHAR(7) NOT NULL,
    vendor_name     VARCHAR NOT NULL,
    account_id      VARCHAR NOT NULL REFERENCES gl_accounts(id),
    amount          NUMERIC(15, 2) NOT NULL,
    category        VARCHAR,
    invoice_date    TIMESTAMP
);

-- 9. sales_pipeline — Deal tracking
CREATE TABLE IF NOT EXISTS sales_pipeline (
    id                  VARCHAR PRIMARY KEY,
    entity_id           VARCHAR NOT NULL REFERENCES entities(id),
    period              VARCHAR(7) NOT NULL,
    deal_name           VARCHAR NOT NULL,
    stage               VARCHAR,
    expected_close_date TIMESTAMP,
    amount              NUMERIC(15, 2) NOT NULL,
    region              VARCHAR,
    product             VARCHAR
);

-- 10. agent_runs — AI pipeline execution tracking
CREATE TABLE IF NOT EXISTS agent_runs (
    id              VARCHAR PRIMARY KEY,
    pipeline_id     VARCHAR,
    entity_id       VARCHAR REFERENCES entities(id),
    period          VARCHAR(7),
    status          VARCHAR DEFAULT 'pending',
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP
);

-- 11. variances — Computed variance analysis
CREATE TABLE IF NOT EXISTS variances (
    id              VARCHAR PRIMARY KEY,
    agent_run_id    VARCHAR REFERENCES agent_runs(id),
    account_id      VARCHAR REFERENCES gl_accounts(id),
    department      VARCHAR,
    actual_amount   NUMERIC(15, 2),
    budget_amount   NUMERIC(15, 2),
    variance_amount NUMERIC(15, 2),
    variance_pct    NUMERIC(8, 4),
    is_material     BOOLEAN DEFAULT FALSE,
    classification  VARCHAR,
    confidence_score NUMERIC(5, 4)
);

-- 12. root_causes — Variance root cause analysis
CREATE TABLE IF NOT EXISTS root_causes (
    id                  VARCHAR PRIMARY KEY,
    variance_id         VARCHAR REFERENCES variances(id),
    summary             TEXT,
    evidence_json       JSON,
    confidence_score    NUMERIC(5, 4),
    recommended_action  TEXT,
    similar_case_ref    VARCHAR
);

-- 13. commentary_drafts — AI-generated commentary
CREATE TABLE IF NOT EXISTS commentary_drafts (
    id              VARCHAR PRIMARY KEY,
    agent_run_id    VARCHAR REFERENCES agent_runs(id),
    version         INTEGER DEFAULT 1,
    content_json    JSON,
    status          VARCHAR DEFAULT 'draft',
    reviewed_by     VARCHAR,
    reviewed_at     TIMESTAMP
);

-- 14. scenarios — What-if modeling
CREATE TABLE IF NOT EXISTS scenarios (
    id              VARCHAR PRIMARY KEY,
    agent_run_id    VARCHAR REFERENCES agent_runs(id),
    name            VARCHAR,
    description     TEXT,
    assumptions_json JSON,
    revenue_impact  NUMERIC(15, 2),
    ebitda_impact   NUMERIC(15, 2),
    cash_impact     NUMERIC(15, 2),
    probability     VARCHAR
);

-- 15. review_logs — Human review checkpoint log
CREATE TABLE IF NOT EXISTS review_logs (
    id              VARCHAR PRIMARY KEY,
    agent_run_id    VARCHAR REFERENCES agent_runs(id),
    checkpoint      VARCHAR,
    reviewer        VARCHAR,
    decision        VARCHAR,
    notes           TEXT,
    timestamp       TIMESTAMP DEFAULT NOW()
);

-- 16. review_decisions (PRD §7) — Assertion review decisions
CREATE TABLE IF NOT EXISTS review_decisions (
    id              VARCHAR PRIMARY KEY,
    tenant_id       VARCHAR NOT NULL,
    period          VARCHAR(7) NOT NULL,
    assertion_id    VARCHAR NOT NULL,
    decision        VARCHAR NOT NULL,
    reviewer        VARCHAR NOT NULL,
    confidence      NUMERIC(5, 4),
    notes           TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- 17. action_items (PRD §7) — Gated action items
CREATE TABLE IF NOT EXISTS action_items (
    id                  VARCHAR PRIMARY KEY,
    tenant_id           VARCHAR NOT NULL,
    period              VARCHAR(7) NOT NULL,
    action              VARCHAR NOT NULL,
    domain              VARCHAR NOT NULL,
    target              VARCHAR NOT NULL,
    description         TEXT,
    status              VARCHAR DEFAULT 'proposed',
    owner               VARCHAR,
    impact_json         JSON,
    cited_assertion_ids JSON,
    blocked_reason      TEXT,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);

-- 18. commentary_versions (PRD §7) — Versioned commentary
CREATE TABLE IF NOT EXISTS commentary_versions (
    id              VARCHAR PRIMARY KEY,
    tenant_id       VARCHAR NOT NULL,
    period          VARCHAR(7) NOT NULL,
    version         INTEGER DEFAULT 1,
    content         TEXT,
    status          VARCHAR DEFAULT 'draft',
    author          VARCHAR,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- 19. audit_logs (PRD §7) — Application event log
CREATE TABLE IF NOT EXISTS audit_logs (
    id              VARCHAR PRIMARY KEY,
    tenant_id       VARCHAR NOT NULL,
    period          VARCHAR(7) NOT NULL,
    event_type      VARCHAR NOT NULL,
    event_data      JSON,
    user_id         VARCHAR,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- 20. pipeline_runs (PRD §7) — Pipeline execution tracking
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id              VARCHAR PRIMARY KEY,
    tenant_id       VARCHAR NOT NULL,
    period          VARCHAR(7) NOT NULL,
    status          VARCHAR DEFAULT 'pending',
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    result_json     JSON,
    error           TEXT
);

-- 21. assertions_db (PRD §7) — Persisted assertions
CREATE TABLE IF NOT EXISTS assertions_db (
    id                  VARCHAR PRIMARY KEY,
    tenant_id           VARCHAR NOT NULL,
    period              VARCHAR(7) NOT NULL,
    assertion_id        VARCHAR NOT NULL,
    type                VARCHAR NOT NULL,
    text                TEXT NOT NULL,
    value               NUMERIC(15, 6),
    support_level       VARCHAR,
    confidence          NUMERIC(5, 4),
    evidence_ids_json   JSON,
    metadata_json       JSON,
    created_at          TIMESTAMP DEFAULT NOW()
);

-- 22. tool_result_cache (PRD §7) — External API cache
CREATE TABLE IF NOT EXISTS tool_result_cache (
    id              VARCHAR PRIMARY KEY,
    tenant_id       VARCHAR NOT NULL,
    period          VARCHAR(7) NOT NULL,
    tool_name       VARCHAR NOT NULL,
    query_fingerprint VARCHAR NOT NULL,
    result_json     JSON,
    created_at      TIMESTAMP DEFAULT NOW(),
    expires_at      TIMESTAMP
);

-- 23. data_quality_snapshots (PRD §7)
CREATE TABLE IF NOT EXISTS data_quality_snapshots (
    id              VARCHAR PRIMARY KEY,
    tenant_id       VARCHAR NOT NULL,
    period          VARCHAR(7) NOT NULL,
    report_json     JSON,
    overall_score   NUMERIC(5, 4),
    created_at      TIMESTAMP DEFAULT NOW()
);

-- 24. policy_decision_logs (PRD §7)
CREATE TABLE IF NOT EXISTS policy_decision_logs (
    id              VARCHAR PRIMARY KEY,
    tenant_id       VARCHAR NOT NULL,
    period          VARCHAR(7) NOT NULL,
    autonomy_level  VARCHAR,
    routing_target  VARCHAR,
    reasons_json    JSON,
    confidence      NUMERIC(5, 4),
    created_at      TIMESTAMP DEFAULT NOW()
);

-- 25. bridge_analysis_results (PRD §7)
CREATE TABLE IF NOT EXISTS bridge_analysis_results (
    id              VARCHAR PRIMARY KEY,
    tenant_id       VARCHAR NOT NULL,
    period          VARCHAR(7) NOT NULL,
    account_id      VARCHAR NOT NULL,
    bridge_json     JSON,
    reconciles      BOOLEAN DEFAULT FALSE,
    confidence      NUMERIC(5, 4),
    created_at      TIMESTAMP DEFAULT NOW()
);

-- 26. variance_snapshots (PRD §7)
CREATE TABLE IF NOT EXISTS variance_snapshots (
    id              VARCHAR PRIMARY KEY,
    tenant_id       VARCHAR NOT NULL,
    period          VARCHAR(7) NOT NULL,
    account_id      VARCHAR NOT NULL,
    variance_json   JSON,
    is_material     BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- 27. root_cause_findings_db (PRD §7)
CREATE TABLE IF NOT EXISTS root_cause_findings_db (
    id              VARCHAR PRIMARY KEY,
    tenant_id       VARCHAR NOT NULL,
    period          VARCHAR(7) NOT NULL,
    account_id      VARCHAR NOT NULL,
    finding_json    JSON,
    confidence      NUMERIC(5, 4),
    created_at      TIMESTAMP DEFAULT NOW()
);

COMMIT;
