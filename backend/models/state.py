from typing import Annotated, TypedDict
import operator
from pydantic import BaseModel


class Variance(BaseModel):
    account_id: str
    account_name: str
    department: str
    actual_amount: float
    budget_amount: float
    variance_amount: float
    variance_pct: float
    is_material: bool = False
    classification: str | None = None
    confidence_score: float = 0.0


class RootCauseFinding(BaseModel):
    variance_id: str
    summary: str
    evidence: list[dict] = []
    confidence_score: float
    recommended_action: str | None = None
    similar_historical_case: str | None = None


class CommentarySection(BaseModel):
    section_type: str
    content: str
    cited_data_points: list[str] = []


class CommentaryDraft(BaseModel):
    sections: list[CommentarySection]
    generated_at: str
    version: int = 1
    status: str = "draft"


class Scenario(BaseModel):
    name: str
    description: str
    assumptions: dict
    revenue_impact: float
    ebitda_impact: float
    cash_impact: float
    probability_assessment: str


class PipelineState(TypedDict):
    period: str
    entity_id: str
    actuals: dict
    budget: dict
    forecast: dict
    variances: Annotated[list[Variance], operator.add]
    root_causes: Annotated[list[RootCauseFinding], operator.add]
    commentary_draft: CommentaryDraft | None
    scenarios: Annotated[list[Scenario], operator.add]
    review_decisions: Annotated[list[dict], operator.add]
    error: str | None
    current_step: str
