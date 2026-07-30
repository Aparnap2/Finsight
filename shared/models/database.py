from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.schema import FetchedValue


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
class Base(DeclarativeBase):
    pass


class Entity(Base):
    __tablename__ = "entities"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    currency = Column(String(3), nullable=False, default="USD")
    fiscal_year_start = Column(String(5), nullable=False, default="01")


class GLAccount(Base):
    __tablename__ = "gl_accounts"
    id = Column(String, primary_key=True)
    entity_id = Column(String, ForeignKey("entities.id"), nullable=False)
    account_number = Column(String, nullable=False)
    account_name = Column(String, nullable=False)
    account_type = Column(String, nullable=False)
    department = Column(String)
    region = Column(String)
    product_line = Column(String)


class TrialBalance(Base):
    __tablename__ = "trial_balance"
    id = Column(String, primary_key=True)
    entity_id = Column(String, ForeignKey("entities.id"), nullable=False)
    period = Column(String(7), nullable=False)
    account_id = Column(String, ForeignKey("gl_accounts.id"), nullable=False)
    debit = Column(Numeric(15, 2), default=0)
    credit = Column(Numeric(15, 2), default=0)
    balance = Column(Numeric(15, 2), server_default=FetchedValue())


class BudgetLine(Base):
    __tablename__ = "budget_lines"
    id = Column(String, primary_key=True)
    entity_id = Column(String, ForeignKey("entities.id"), nullable=False)
    period = Column(String(7), nullable=False)
    account_id = Column(String, ForeignKey("gl_accounts.id"), nullable=False)
    department = Column(String)
    amount = Column(Numeric(15, 2), nullable=False)
    notes = Column(Text)


class ForecastLine(Base):
    __tablename__ = "forecast_lines"
    id = Column(String, primary_key=True)
    entity_id = Column(String, ForeignKey("entities.id"), nullable=False)
    period = Column(String(7), nullable=False)
    account_id = Column(String, ForeignKey("gl_accounts.id"), nullable=False)
    department = Column(String)
    amount = Column(Numeric(15, 2), nullable=False)
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=_utcnow)


class Actual(Base):
    __tablename__ = "actuals"
    id = Column(String, primary_key=True)
    entity_id = Column(String, ForeignKey("entities.id"), nullable=False)
    period = Column(String(7), nullable=False)
    account_id = Column(String, ForeignKey("gl_accounts.id"), nullable=False)
    department = Column(String)
    amount = Column(Numeric(15, 2), nullable=False)


class HeadcountData(Base):
    __tablename__ = "headcount_data"
    id = Column(String, primary_key=True)
    entity_id = Column(String, ForeignKey("entities.id"), nullable=False)
    period = Column(String(7), nullable=False)
    department = Column(String, nullable=False)
    headcount = Column(Integer, default=0)
    total_compensation = Column(Numeric(15, 2), default=0)
    new_hires = Column(Integer, default=0)
    departures = Column(Integer, default=0)


class VendorInvoice(Base):
    __tablename__ = "vendor_invoices"
    id = Column(String, primary_key=True)
    entity_id = Column(String, ForeignKey("entities.id"), nullable=False)
    period = Column(String(7), nullable=False)
    vendor_name = Column(String, nullable=False)
    account_id = Column(String, ForeignKey("gl_accounts.id"), nullable=False)
    amount = Column(Numeric(15, 2), nullable=False)
    category = Column(String)
    invoice_date = Column(DateTime, nullable=False)
    status = Column(String(20), nullable=False, default="draft")


class SalesPipeline(Base):
    __tablename__ = "sales_pipeline"
    id = Column(String, primary_key=True)
    entity_id = Column(String, ForeignKey("entities.id"), nullable=False)
    period = Column(String(7), nullable=False)
    deal_name = Column(String, nullable=False)
    stage = Column(String, nullable=False)
    expected_close_date = Column(DateTime, nullable=False)
    amount = Column(Numeric(15, 2), nullable=False)
    region = Column(String)
    product = Column(String)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id = Column(String, primary_key=True)
    pipeline_id = Column(String)
    entity_id = Column(String, ForeignKey("entities.id"), nullable=False)
    period = Column(String(7), nullable=False)
    status = Column(String, nullable=False, default="pending")
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime)


class Variance(Base):
    __tablename__ = "variances"
    id = Column(String, primary_key=True)
    agent_run_id = Column(String, ForeignKey("agent_runs.id"), nullable=False)
    account_id = Column(String, ForeignKey("gl_accounts.id"), nullable=False)
    department = Column(String)
    actual_amount = Column(Numeric(15, 2), nullable=False)
    budget_amount = Column(Numeric(15, 2), nullable=False)
    variance_amount = Column(Numeric(15, 2), server_default=FetchedValue())
    variance_pct = Column(Numeric(8, 4), server_default=FetchedValue())
    is_material = Column(Boolean, nullable=False, default=False)
    classification = Column(String, nullable=False)
    confidence_score = Column(Numeric(5, 4))


class RootCause(Base):
    __tablename__ = "root_causes"
    id = Column(String, primary_key=True)
    variance_id = Column(String, ForeignKey("variances.id"), nullable=False)
    summary = Column(Text, nullable=False)
    evidence_json = Column(JSON)
    confidence_score = Column(Numeric(5, 4))
    recommended_action = Column(Text)
    similar_case_ref = Column(String)


class CommentaryDraft(Base):
    __tablename__ = "commentary_drafts"
    id = Column(String, primary_key=True)
    agent_run_id = Column(String, ForeignKey("agent_runs.id"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    content_json = Column(JSON)
    status = Column(String, nullable=False, default="draft")
    reviewed_by = Column(String)
    reviewed_at = Column(DateTime)


class Scenario(Base):
    __tablename__ = "scenarios"
    id = Column(String, primary_key=True)
    agent_run_id = Column(String, ForeignKey("agent_runs.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text)
    assumptions_json = Column(JSON)
    revenue_impact = Column(Numeric(15, 2))
    ebitda_impact = Column(Numeric(15, 2))
    cash_impact = Column(Numeric(15, 2))
    probability = Column(String)


class ReviewLog(Base):
    __tablename__ = "review_logs"
    id = Column(String, primary_key=True)
    agent_run_id = Column(String, ForeignKey("agent_runs.id"))
    checkpoint = Column(String)
    reviewer = Column(String)
    decision = Column(String)
    notes = Column(Text)
    timestamp = Column(DateTime, default=_utcnow)


# ---------------------------------------------------------------------------
# PRD §7 — New domain model tables
# ---------------------------------------------------------------------------


class ReviewDecision(Base):
    """Human or automated review decision on an assertion."""
    __tablename__ = "review_decisions"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False, index=True)
    period = Column(String(7), nullable=False)
    assertion_id = Column(String, nullable=False)
    decision = Column(String, nullable=False)       # approved | rejected | escalated
    reviewer = Column(String, nullable=False)
    confidence = Column(Numeric(5, 4))
    notes = Column(Text)
    created_at = Column(DateTime, default=_utcnow)


class ActionItemDB(Base):
    """Persisted action item with full gate-enforcement metadata."""
    __tablename__ = "action_items"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False, index=True)
    period = Column(String(7), nullable=False)
    action = Column(String, nullable=False)          # verb: reduce, increase, …
    domain = Column(String, nullable=False)          # cost, revenue, …
    target = Column(String, nullable=False)
    description = Column(Text)
    status = Column(String, default="proposed")
    owner = Column(String)
    impact_json = Column(JSON)
    cited_assertion_ids = Column(JSON)               # list[str]
    blocked_reason = Column(Text)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)


class CommentaryVersion(Base):
    """Versioned commentary draft for a period."""
    __tablename__ = "commentary_versions"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False, index=True)
    period = Column(String(7), nullable=False)
    version = Column(Integer, default=1)
    content = Column(Text)
    status = Column(String, default="draft")
    author = Column(String)
    created_at = Column(DateTime, default=_utcnow)


class AuditLog(Base):
    """Append-only audit trail for pipeline and user events."""
    __tablename__ = "audit_logs"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False, index=True)
    period = Column(String(7), nullable=False)
    event_type = Column(String, nullable=False)
    event_data = Column(JSON)
    user_id = Column(String)
    created_at = Column(DateTime, default=_utcnow)


class PipelineRun(Base):
    """Tracks each end-to-end pipeline execution."""
    __tablename__ = "pipeline_runs"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False, index=True)
    period = Column(String(7), nullable=False)
    status = Column(String, default="pending")
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    result_json = Column(JSON)
    error = Column(Text)


class AssertionDB(Base):
    """Persisted assertion from the assertion pipeline."""
    __tablename__ = "assertions_db"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False, index=True)
    period = Column(String(7), nullable=False)
    assertion_id = Column(String, nullable=False)
    type = Column(String, nullable=False)            # numeric | comparative | causal | …
    text = Column(Text, nullable=False)
    value = Column(Numeric(15, 6))
    support_level = Column(String)                   # verified | probable | weak | …
    confidence = Column(Numeric(5, 4))
    evidence_ids_json = Column(JSON)                 # list[str]
    metadata_json = Column(JSON)
    created_at = Column(DateTime, default=_utcnow)


class ToolResultCache(Base):
    """Cache for external tool / API call results."""
    __tablename__ = "tool_result_cache"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False, index=True)
    period = Column(String(7), nullable=False)
    tool_name = Column(String, nullable=False)
    query_fingerprint = Column(String, nullable=False)
    result_json = Column(JSON)
    created_at = Column(DateTime, default=_utcnow)
    expires_at = Column(DateTime)


class DataQualitySnapshot(Base):
    """Snapshot of data quality metrics for a period."""
    __tablename__ = "data_quality_snapshots"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False, index=True)
    period = Column(String(7), nullable=False)
    report_json = Column(JSON)
    overall_score = Column(Numeric(5, 4))
    created_at = Column(DateTime, default=_utcnow)


class PolicyDecisionLog(Base):
    """Log of autonomy / routing policy decisions."""
    __tablename__ = "policy_decision_logs"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False, index=True)
    period = Column(String(7), nullable=False)
    autonomy_level = Column(String)                  # autonomous | semi_autonomous | …
    routing_target = Column(String)                  # auto_approve | human_review | …
    reasons_json = Column(JSON)                      # list[str]
    confidence = Column(Numeric(5, 4))
    created_at = Column(DateTime, default=_utcnow)


class BridgeAnalysisResult(Base):
    """Result of period-to-period bridge analysis for an account."""
    __tablename__ = "bridge_analysis_results"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False, index=True)
    period = Column(String(7), nullable=False)
    account_id = Column(String, nullable=False)
    bridge_json = Column(JSON)
    reconciles = Column(Boolean, default=False)
    confidence = Column(Numeric(5, 4))
    created_at = Column(DateTime, default=_utcnow)


class VarianceSnapshot(Base):
    """Point-in-time snapshot of a variance for audit / comparison."""
    __tablename__ = "variance_snapshots"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False, index=True)
    period = Column(String(7), nullable=False)
    account_id = Column(String, nullable=False)
    variance_json = Column(JSON)
    is_material = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_utcnow)


class RootCauseFindingDB(Base):
    """Persisted root-cause finding with structured evidence."""
    __tablename__ = "root_cause_findings_db"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False, index=True)
    period = Column(String(7), nullable=False)
    account_id = Column(String, nullable=False)
    finding_json = Column(JSON)
    confidence = Column(Numeric(5, 4))
    created_at = Column(DateTime, default=_utcnow)
