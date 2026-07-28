from enum import Enum
from decimal import Decimal
from typing import Any
from pydantic import BaseModel


class AssertionType(str, Enum):
    NUMERIC = "numeric"
    COMPARATIVE = "comparative"
    CAUSAL = "causal"
    HYPOTHESIS = "hypothesis"
    ACTION = "action"


class SupportLevel(str, Enum):
    VERIFIED = "verified"
    PROBABLE = "probable"
    WEAK = "weak"
    INSUFFICIENT = "insufficient"


class Assertion(BaseModel):
    id: str
    type: AssertionType
    text: str
    value: Decimal | None = None
    evidence_ids: list[str] = []
    support_level: SupportLevel = SupportLevel.INSUFFICIENT
    confidence: float = 0.0
    contradictions: list[str] = []
    missing_evidence: list[str] = []
    max_allowed_action: str = "route_for_review"  # what policy action is allowed
    source: str = ""  # "deterministic" | "llm_analysis" | "human"
    metadata: dict[str, Any] = {}  # extra structured data about the assertion
