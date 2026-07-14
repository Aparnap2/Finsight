import uuid
from fastapi import APIRouter, HTTPException
from backend.api.schemas import PipelineRunRequest, PipelineRunResponse

router = APIRouter()

_runs: dict[str, dict] = {}


@router.get("/health")
async def health():
    return {"status": "healthy"}


@router.post("/pipeline/run", response_model=PipelineRunResponse)
async def trigger_pipeline(req: PipelineRunRequest):
    run_id = str(uuid.uuid4())[:8]
    _runs[run_id] = {"status": "started", "period": req.period, "entity_id": req.entity_id}
    return PipelineRunResponse(run_id=run_id, status="started", message="Pipeline triggered")


@router.get("/pipeline/{run_id}/status")
async def get_pipeline_status(run_id: str):
    if run_id not in _runs:
        raise HTTPException(status_code=404, detail="Run not found")
    return _runs[run_id]
