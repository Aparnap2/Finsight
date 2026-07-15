import re
from pydantic import BaseModel


class Claim(BaseModel):
    amount: float
    text: str
    position: int


class ValidationResult(BaseModel):
    is_valid: bool = True
    claims: list[Claim] = []
    verified_claims: list[Claim] = []
    unverified_claims: list[Claim] = []
    errors: list[str] = []


TOLERANCE_PCT = 5.0


def extract_monetary_claims(text: str) -> list[Claim]:
    pattern = r'\$[\d,]+(?:\.\d{1,2})?'
    claims = []
    for m in re.finditer(pattern, text):
        amount_str = m.group().replace("$", "").replace(",", "")
        try:
            amount = float(amount_str)
        except ValueError:
            continue
        if amount > 0:
            claims.append(Claim(amount=amount, text=m.group(), position=m.start()))
    return claims


def _fact_matches_claim(claim: Claim, facts: list[dict]) -> bool:
    for fact in facts:
        fact_amount = fact.get("amount", 0)
        if fact_amount == 0:
            continue
        pct_diff = abs(claim.amount - fact_amount) / fact_amount * 100
        if pct_diff <= TOLERANCE_PCT:
            return True
    return False


def validate_commentary_claims(commentary: str, facts: list[dict]) -> ValidationResult:
    if not commentary or not commentary.strip():
        return ValidationResult(is_valid=True)

    claims = extract_monetary_claims(commentary)
    verified = []
    unverified = []

    for claim in claims:
        if _fact_matches_claim(claim, facts):
            verified.append(claim)
        else:
            unverified.append(claim)

    is_valid = len(unverified) == 0
    errors = [
        f"Unverified claim: {c.text} (${c.amount:,.2f}) — no matching fact within {TOLERANCE_PCT}% tolerance"
        for c in unverified
    ]

    return ValidationResult(
        is_valid=is_valid,
        claims=claims,
        verified_claims=verified,
        unverified_claims=unverified,
        errors=errors,
    )
