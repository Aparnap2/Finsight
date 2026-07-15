from pydantic import BaseModel


class PipelineRunRequest(BaseModel):
    period: str
    entity_id: str = "CF001"
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
    entity_id: str
    actuals_count: int
    budget_count: int
    variances: list[VarianceResponse]
    material_count: int
    root_causes: list[dict]
    commentary_sections: list[dict]
