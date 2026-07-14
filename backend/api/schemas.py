from pydantic import BaseModel


class PipelineRunRequest(BaseModel):
    period: str
    entity_id: str = "CF001"


class PipelineRunResponse(BaseModel):
    run_id: str
    status: str
    message: str
