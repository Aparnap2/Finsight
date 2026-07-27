from pydantic import BaseModel


# ── Existing schemas (kept for backward compatibility) ──────────────────────


class PipelineRunRequest(BaseModel):
    period: str
    tenant_id: str = "CF001"
    run_sync: bool = False


class PipelineRunResponse(BaseModel):
    run_id: str
    status: str
    message: str


class VarianceResponse(BaseModel):
    account_id: str
    account_name: str
    department: str
    actual_amount: float
    budget_amount: float
    variance_amount: float
    variance_pct: float
    is_material: bool


class PipelineResultResponse(BaseModel):
    run_id: str
    status: str
    period: str
    tenant_id: str
    actuals_count: int
    budget_count: int
    variances: list[VarianceResponse]
    material_count: int
    root_causes: list[dict]
    commentary_sections: list[dict]


# ── New schemas for truth/render separation API ─────────────────────────────


class AssertionResponse(BaseModel):
    """Serialized assertion (truth layer)."""
    id: str
    type: str
    text: str
    value: float | None = None
    evidence_ids: list[str] = []
    support_level: str = "insufficient"
    confidence: float = 0.0
    metadata: dict = {}


class CommentarySectionResponse(BaseModel):
    """A single rendered commentary section."""
    section_type: str
    content: str
    cited_data_points: list[str] = []


class DataQualityCheckResponse(BaseModel):
    check: str
    passed: bool
    severity: str = "info"
    detail: str = ""


class DataQualityResponse(BaseModel):
    overall_score: float
    passed: bool
    degraded_modes: list[str] = []
    checks: list[DataQualityCheckResponse] = []


class PolicyDecisionResponse(BaseModel):
    autonomy_level: str
    routing_target: str
    reasons: list[str] = []
    requires_review: bool = False
    blocked_actions: list[str] = []
    confidence: float = 0.0


class ActionItemResponse(BaseModel):
    id: str
    action: str
    domain: str
    target: str
    description: str
    status: str = "proposed"
    owner: str | None = None
    impact_quantified: bool = False
    policy_permitted: bool = False
    blocked_reason: str | None = None
    cited_assertion_ids: list[str] = []


class ActionCreateRequest(BaseModel):
    action: str
    domain: str
    target: str
    description: str
    cited_assertion_ids: list[str] = []
    owner: str | None = None
    impact_expected_savings: float | None = None
    impact_expected_revenue: float | None = None
    policy_permitted: bool = False


class BridgeComponentResponse(BaseModel):
    component: str
    amount: str
    percentage: str
    description: str
    confidence: float


class BridgeAnalysisResponse(BaseModel):
    account_id: str
    account_name: str
    total_variance: str
    bridge_type: str
    components: list[BridgeComponentResponse] = []
    reconciles: bool
    confidence: float
    degraded_modes: list[str] = []


class CommentaryResponse(BaseModel):
    period: str
    tenant_id: str
    commentary: list[CommentarySectionResponse] = []
    assertions: list[AssertionResponse] = []
    degraded_modes: list[str] = []
    data_quality: DataQualityResponse | None = None


class PipelineExecuteRequest(BaseModel):
    """Request body for the full truth/render pipeline."""
    period: str
    tenant_id: str = "CF001"
    force: bool = False


class PipelineExecuteResponse(BaseModel):
    """Full pipeline response with both truth (assertions) and rendered output."""
    period: str
    tenant_id: str
    status: str
    commentary: list[CommentarySectionResponse] = []
    assertions: list[AssertionResponse] = []
    degraded_modes: list[str] = []
    data_quality: DataQualityResponse | None = None
    routing_decision: PolicyDecisionResponse | None = None
    action_items: list[ActionItemResponse] = []


class StatusResponse(BaseModel):
    status: str
    version: str
    endpoints: list[str] = []
