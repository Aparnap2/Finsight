import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.models.database import Base
from backend.data.seed import seed_database
from backend.validators.claim_validator import validate_commentary_claims, ValidationResult


@pytest.fixture()
def seeded_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session)
    return engine


def test_validate_empty_commentary():
    result = validate_commentary_claims("", [])
    assert result.is_valid
    assert len(result.claims) == 0


def test_extract_monetary_claims():
    text = "Revenue was $484,464 against budget of $484,464. Costs increased by $58,470."
    result = validate_commentary_claims(text, [])
    assert len(result.claims) >= 2
    amounts = [c.amount for c in result.claims]
    assert 484464.0 in amounts
    assert 58470.0 in amounts


def test_validate_against_facts(seeded_db):
    from sqlalchemy import text as sql_text
    with Session(seeded_db) as session:
        rows = session.execute(sql_text(
            "SELECT g.account_name, a.amount, a.period "
            "FROM actuals a JOIN gl_accounts g ON a.account_id = g.id "
            "WHERE a.period = '2026-06' LIMIT 5"
        )).fetchall()
    facts = [
        {"account_name": r[0], "amount": float(r[1]), "period": r[2]}
        for r in rows
    ]
    commentary = f"Cloud infrastructure was ${facts[0]['amount']:,.2f}."
    result = validate_commentary_claims(commentary, facts)
    assert result.is_valid
    assert len(result.verified_claims) >= 1


def test_validate_hallucinated_number(seeded_db):
    commentary = "Revenue was $999,999,999 which exceeds all expectations."
    result = validate_commentary_claims(commentary, [])
    assert not result.is_valid
    assert len(result.unverified_claims) >= 1


def test_validation_result_structure():
    result = validate_commentary_claims("Total spend was $100,000.", [])
    assert hasattr(result, "is_valid")
    assert hasattr(result, "claims")
    assert hasattr(result, "verified_claims")
    assert hasattr(result, "unverified_claims")
    assert hasattr(result, "errors")


def test_tolerance_5pct():
    facts = [{"account_name": "Test", "amount": 100000.0, "period": "2026-06"}]
    commentary = "The amount was $103,000."
    result = validate_commentary_claims(commentary, facts)
    assert result.is_valid, "3% tolerance should pass"


def test_outside_tolerance():
    facts = [{"account_name": "Test", "amount": 100000.0, "period": "2026-06"}]
    commentary = "The amount was $120,000."
    result = validate_commentary_claims(commentary, facts)
    assert not result.is_valid, "20% should fail"
