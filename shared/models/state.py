from decimal import Decimal
from typing import Annotated, TypedDict
import operator
from pydantic import BaseModel

from shared.models.assertions import Assertion, AssertionType, SupportLevel


class Variance(BaseModel):
    account_id: str
    account_name: str
    department: str
    actual_amount: Decimal
    budget_amount: Decimal
    variance_amount: Decimal
    variance_pct: Decimal
    is_material: bool = False
    classification: str | None = None
    confidence_score: float = 0.0


class EvidenceItem(BaseModel):
    source_table: str
    record_id: str
    field: str
    value: Decimal
    period: str
    description: str = ""


class RootCauseFinding(BaseModel):
    variance_id: str
    summary: str
    assertions: list[Assertion] = []  # REPLACES free-text summary evidence
    evidence: list[EvidenceItem] = []
    confidence_score: float
    recommended_action: str | None = None
    similar_historical_case: str | None = None
    alternative_hypotheses: list[Assertion] = []
    data_gaps: list[str] = []


class CommentarySection(BaseModel):
    section_type: str
    content: str
    cited_data_points: list[str] = []


class ActionItem(BaseModel):
    description: str
    assigned_to: str | None = None
    due_by: str | None = None
    priority: str = "medium"


class CommentaryDraft(BaseModel):
    sections: list[CommentarySection]
    actions: list[ActionItem] = []
    assertions_used: list[str] = []  # assertion IDs consumed
    generated_at: str
    version: int = 1
    status: str = "draft"
    approval_state: str | None = None


class Scenario(BaseModel):
    name: str
    description: str
    assumptions: dict[str, object]
    revenue_impact: Decimal
    ebitda_impact: Decimal
    cash_impact: Decimal
    probability_assessment: str


class PipelineState(TypedDict):
    period: str
    tenant_id: str
    actuals: dict[str, object]
    budget: dict[str, object]
    forecast: dict[str, object]
    variances: Annotated[list[Variance], operator.add]
    root_causes: Annotated[list[RootCauseFinding], operator.add]
    commentary_draft: CommentaryDraft | None
    scenarios: Annotated[list[Scenario], operator.add]
    review_decisions: Annotated[list[dict[str, object]], operator.add]
    error: str | None
    current_step: str
    # Extended state for PRD §6 states
    degraded_modes: Annotated[list[str], operator.add]
    assertions: Annotated[list[Assertion], operator.add]
    data_quality: dict[str, object] | None
    policy_decision: dict[str, object] | None
