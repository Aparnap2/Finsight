from datetime import datetime
from sqlalchemy import (
    Column, String, Float, Integer, Boolean, DateTime, ForeignKey, JSON, Text, Numeric
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Entity(Base):
    __tablename__ = "entities"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    currency = Column(String(3), default="USD")
    fiscal_year_start = Column(String(5), default="01")


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
    balance = Column(Numeric(15, 2), default=0)


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
    created_at = Column(DateTime, default=datetime.utcnow)


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
    invoice_date = Column(DateTime)


class SalesPipeline(Base):
    __tablename__ = "sales_pipeline"
    id = Column(String, primary_key=True)
    entity_id = Column(String, ForeignKey("entities.id"), nullable=False)
    period = Column(String(7), nullable=False)
    deal_name = Column(String, nullable=False)
    stage = Column(String)
    expected_close_date = Column(DateTime)
    amount = Column(Numeric(15, 2), nullable=False)
    region = Column(String)
    product = Column(String)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id = Column(String, primary_key=True)
    pipeline_id = Column(String)
    entity_id = Column(String, ForeignKey("entities.id"))
    period = Column(String(7))
    status = Column(String, default="pending")
    started_at = Column(DateTime)
    completed_at = Column(DateTime)


class Variance(Base):
    __tablename__ = "variances"
    id = Column(String, primary_key=True)
    agent_run_id = Column(String, ForeignKey("agent_runs.id"))
    account_id = Column(String, ForeignKey("gl_accounts.id"))
    department = Column(String)
    actual_amount = Column(Numeric(15, 2))
    budget_amount = Column(Numeric(15, 2))
    variance_amount = Column(Numeric(15, 2))
    variance_pct = Column(Numeric(8, 4))
    is_material = Column(Boolean, default=False)
    classification = Column(String)
    confidence_score = Column(Numeric(5, 4))


class RootCause(Base):
    __tablename__ = "root_causes"
    id = Column(String, primary_key=True)
    variance_id = Column(String, ForeignKey("variances.id"))
    summary = Column(Text)
    evidence_json = Column(JSON)
    confidence_score = Column(Numeric(5, 4))
    recommended_action = Column(Text)
    similar_case_ref = Column(String)


class CommentaryDraft(Base):
    __tablename__ = "commentary_drafts"
    id = Column(String, primary_key=True)
    agent_run_id = Column(String, ForeignKey("agent_runs.id"))
    version = Column(Integer, default=1)
    content_json = Column(JSON)
    status = Column(String, default="draft")
    reviewed_by = Column(String)
    reviewed_at = Column(DateTime)


class Scenario(Base):
    __tablename__ = "scenarios"
    id = Column(String, primary_key=True)
    agent_run_id = Column(String, ForeignKey("agent_runs.id"))
    name = Column(String)
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
    timestamp = Column(DateTime, default=datetime.utcnow)
