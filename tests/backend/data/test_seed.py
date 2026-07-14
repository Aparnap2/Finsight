import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session
from backend.models.database import Base, Entity, GLAccount, TrialBalance, BudgetLine, Actual
from backend.data.seed import seed_database


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_seed_creates_entity(db_session):
    seed_database(db_session)
    assert db_session.query(Entity).count() == 1
    assert db_session.query(Entity).first().name == "CloudForge Inc."


def test_seed_creates_gl_accounts(db_session):
    seed_database(db_session)
    count = db_session.query(GLAccount).count()
    assert count >= 15


def test_seed_creates_trial_balance(db_session):
    seed_database(db_session)
    count = db_session.query(TrialBalance).count()
    assert count > 0


def test_seed_creates_actuals(db_session):
    seed_database(db_session)
    count = db_session.query(Actual).count()
    assert count > 0
