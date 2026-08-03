CREATE OR REPLACE FUNCTION fn_enforce_invoice_status_transition()
RETURNS trigger
LANGUAGE plpgsql AS $body$
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.status IS DISTINCT FROM NEW.status THEN
        IF NOT CASE OLD.status
            WHEN 'draft'     THEN NEW.status IN ('submitted', 'cancelled')
            WHEN 'submitted' THEN NEW.status IN ('approved', 'cancelled', 'disputed')
            WHEN 'approved'  THEN NEW.status IN ('paid', 'cancelled')
            WHEN 'disputed'  THEN NEW.status IN ('cancelled', 'draft')
            WHEN 'paid'      THEN FALSE
            WHEN 'cancelled' THEN FALSE
            ELSE FALSE
        END THEN
            RAISE EXCEPTION 'Invalid invoice status transition: % -> %', OLD.status, NEW.status;
        END IF;
    END IF;
    RETURN NEW;
END;
$body$;

CREATE OR REPLACE FUNCTION fn_enforce_agentrun_status_transition()
RETURNS trigger
LANGUAGE plpgsql AS $body$
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.status IS DISTINCT FROM NEW.status THEN
        IF NOT CASE OLD.status
            WHEN 'pending'  THEN NEW.status IN ('running', 'cancelled')
            WHEN 'running'  THEN NEW.status IN ('completed', 'failed')
            WHEN 'completed' THEN FALSE
            WHEN 'failed'    THEN FALSE
            WHEN 'cancelled' THEN FALSE
            ELSE FALSE
        END THEN
            RAISE EXCEPTION 'Invalid agent_run status transition: % -> %', OLD.status, NEW.status;
        END IF;
    END IF;
    RETURN NEW;
END;
$body$;

CREATE OR REPLACE FUNCTION fn_enforce_pipeline_status_transition()
RETURNS trigger
LANGUAGE plpgsql AS $body$
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.status IS DISTINCT FROM NEW.status THEN
        IF NOT CASE OLD.status
            WHEN 'pending'  THEN NEW.status IN ('running', 'failed')
            WHEN 'running'  THEN NEW.status IN ('completed', 'failed')
            WHEN 'completed' THEN FALSE
            WHEN 'failed'    THEN FALSE
            ELSE FALSE
        END THEN
            RAISE EXCEPTION 'Invalid pipeline status transition: % -> %', OLD.status, NEW.status;
        END IF;
    END IF;
    RETURN NEW;
END;
$body$;

CREATE OR REPLACE FUNCTION fn_enforce_action_status_transition()
RETURNS trigger
LANGUAGE plpgsql AS $body$
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.status IS DISTINCT FROM NEW.status THEN
        IF NOT CASE OLD.status
            WHEN 'proposed'    THEN NEW.status IN ('approved', 'cancelled')
            WHEN 'approved'    THEN NEW.status IN ('in_progress', 'cancelled')
            WHEN 'in_progress' THEN NEW.status IN ('completed', 'cancelled', 'blocked')
            WHEN 'blocked'     THEN NEW.status IN ('in_progress', 'cancelled')
            WHEN 'completed'  THEN FALSE
            WHEN 'cancelled'  THEN FALSE
            ELSE FALSE
        END THEN
            RAISE EXCEPTION 'Invalid action status transition: % -> %', OLD.status, NEW.status;
        END IF;
    END IF;
    RETURN NEW;
END;
$body$;

DROP TRIGGER IF EXISTS trg_enforce_invoice_status ON vendor_invoices;
CREATE TRIGGER trg_enforce_invoice_status
    BEFORE UPDATE ON vendor_invoices
    FOR EACH ROW EXECUTE FUNCTION fn_enforce_invoice_status_transition();

DROP TRIGGER IF EXISTS trg_enforce_agentrun_status ON agent_runs;
CREATE TRIGGER trg_enforce_agentrun_status
    BEFORE UPDATE ON agent_runs
    FOR EACH ROW EXECUTE FUNCTION fn_enforce_agentrun_status_transition();

DROP TRIGGER IF EXISTS trg_enforce_pipeline_status ON pipeline_runs;
CREATE TRIGGER trg_enforce_pipeline_status
    BEFORE UPDATE ON pipeline_runs
    FOR EACH ROW EXECUTE FUNCTION fn_enforce_pipeline_status_transition();

-- Auto-update updated_at on action_items
CREATE OR REPLACE FUNCTION fn_update_updated_at()
RETURNS trigger
LANGUAGE plpgsql AS $body$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$body$;

DROP TRIGGER IF EXISTS trg_enforce_action_status ON action_items;
CREATE TRIGGER trg_enforce_action_status
    BEFORE UPDATE ON action_items
    FOR EACH ROW EXECUTE FUNCTION fn_enforce_action_status_transition();

DROP TRIGGER IF EXISTS trg_action_items_updated_at ON action_items;
CREATE TRIGGER trg_action_items_updated_at
    BEFORE UPDATE ON action_items
    FOR EACH ROW EXECUTE FUNCTION fn_update_updated_at();
