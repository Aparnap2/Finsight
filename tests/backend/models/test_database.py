from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session
from backend.models.database import Base, Entity, GLAccount, TrialBalance, BudgetLine, Actual


def test_tables_created():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "entities" in tables
    assert "gl_accounts" in tables
    assert "trial_balance" in tables
    assert "budget_lines" in tables
    assert "forecast_lines" in tables
    assert "actuals" in tables
    assert "headcount_data" in tables
    assert "vendor_invoices" in tables
    assert "sales_pipeline" in tables
    assert "agent_runs" in tables
    assert "variances" in tables
    assert "root_causes" in tables
    assert "commentary_drafts" in tables
    assert "scenarios" in tables
    assert "review_logs" in tables


def test_entity_creation():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        entity = Entity(id="CF001", name="CloudForge Inc.", currency="USD", fiscal_year_start="01")
        session.add(entity)
        session.commit()
        assert session.query(Entity).count() == 1
