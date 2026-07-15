import uuid
import csv
import io
from fastapi import APIRouter, HTTPException, UploadFile, File
from sqlalchemy import create_engine
from backend.api.schemas import PipelineRunRequest, PipelineRunResponse, PipelineResultResponse
from backend.config import get_settings
from backend.agents.ingestion_agent import ingestion_node
from backend.agents.variance_agent import variance_node
from backend.agents.root_cause_agent import investigate_root_causes
from backend.agents.commentary_agent import generate_commentary
from backend.validators.claim_validator import validate_commentary_claims
from backend.models.state import PipelineState

router = APIRouter()

_runs: dict[str, dict] = {}


@router.get("/health")
async def health():
    return {"status": "healthy"}


@router.post("/pipeline/run")
async def trigger_pipeline(req: PipelineRunRequest):
    run_id = str(uuid.uuid4())[:8]

    if req.run_sync:
        settings = get_settings()
        engine = create_engine(settings.postgres_uri)

        state: PipelineState = {
            "period": req.period,
            "entity_id": req.entity_id,
            "actuals": {},
            "budget": {},
            "forecast": {},
            "variances": [],
            "root_causes": [],
            "commentary_draft": None,
            "scenarios": [],
            "review_decisions": [],
            "error": None,
            "current_step": "start",
        }

        ingestion = ingestion_node(state, engine=engine)
        state.update(ingestion)

        var_result = variance_node(state)
        state["variances"] = var_result["variances"]

        material = [v for v in state["variances"] if v.is_material]
        findings = investigate_root_causes(material)
        state["root_causes"] = findings

        draft = generate_commentary(findings, [])
        state["commentary_draft"] = draft

        variance_data = [
            {
                "account_id": v.account_id,
                "account_name": v.account_name,
                "department": v.department,
                "actual_amount": v.actual_amount,
                "budget_amount": v.budget_amount,
                "variance_amount": v.variance_amount,
                "variance_pct": v.variance_pct,
                "is_material": v.is_material,
            }
            for v in state["variances"]
        ]

        root_cause_data = [
            {
                "variance_id": rc.variance_id,
                "summary": rc.summary,
                "confidence_score": rc.confidence_score,
                "recommended_action": rc.recommended_action,
            }
            for rc in findings
        ]

        commentary_data = [
            {"section_type": s.section_type, "content": s.content}
            for s in (draft.sections if draft else [])
        ]

        _runs[run_id] = {
            "status": "completed",
            "period": req.period,
            "entity_id": req.entity_id,
            "result": {
                "variances": variance_data,
                "material_count": len(material),
                "root_causes": root_cause_data,
                "commentary_sections": commentary_data,
                "actuals_count": len(state["actuals"].get("accounts", [])),
                "budget_count": len(state["budget"].get("accounts", [])),
            },
        }

        return PipelineResultResponse(
            run_id=run_id,
            status="completed",
            period=req.period,
            entity_id=req.entity_id,
            actuals_count=len(state["actuals"].get("accounts", [])),
            budget_count=len(state["budget"].get("accounts", [])),
            variances=variance_data,
            material_count=len(material),
            root_causes=root_cause_data,
            commentary_sections=commentary_data,
        )

    _runs[run_id] = {"status": "started", "period": req.period, "entity_id": req.entity_id}
    return PipelineRunResponse(run_id=run_id, status="started", message="Pipeline triggered")


@router.get("/pipeline/{run_id}/status")
async def get_pipeline_status(run_id: str):
    if run_id not in _runs:
        raise HTTPException(status_code=404, detail="Run not found")
    return _runs[run_id]


@router.get("/pipeline/{run_id}/results")
async def get_pipeline_results(run_id: str):
    if run_id not in _runs:
        raise HTTPException(status_code=404, detail="Run not found")
    run = _runs[run_id]
    if run.get("status") != "completed":
        raise HTTPException(status_code=400, detail="Pipeline not completed yet")
    return run.get("result", {})


@router.post("/pipeline/{run_id}/review")
async def submit_review(run_id: str, checkpoint: str, decision: str, notes: str = ""):
    if run_id not in _runs:
        raise HTTPException(status_code=404, detail="Run not found")
    if decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="Decision must be approve or reject")
    run = _runs[run_id]
    reviews = run.setdefault("reviews", [])
    reviews.append({"checkpoint": checkpoint, "decision": decision, "notes": notes})
    return {"status": "reviewed", "checkpoint": checkpoint, "decision": decision}


@router.post("/import/csv")
async def import_csv(file: UploadFile = File(...), entity_id: str = "CF001"):
    content = await file.read()
    text = content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))

    rows = list(reader)
    if not rows:
        raise HTTPException(status_code=400, detail="Empty CSV file")

    required_cols = {"account_id", "period", "amount"}
    if not required_cols.issubset(set(rows[0].keys())):
        raise HTTPException(
            status_code=400,
            detail=f"CSV must have columns: {required_cols}. Found: {set(rows[0].keys())}",
        )

    settings = get_settings()
    engine = create_engine(settings.postgres_uri)
    from sqlalchemy.orm import Session
    from backend.models.database import Actual, BudgetLine

    actuals_count = 0
    budget_count = 0
    with Session(engine) as session:
        for row in rows:
            amount = float(row["amount"])
            account_id = row["account_id"]
            period = row["period"]
            department = row.get("department", "Unknown")

            if row.get("type", "actual") == "budget":
                session.add(BudgetLine(
                    id=str(uuid.uuid4())[:8], entity_id=entity_id,
                    period=period, account_id=account_id,
                    department=department, amount=amount,
                ))
                budget_count += 1
            else:
                session.add(Actual(
                    id=str(uuid.uuid4())[:8], entity_id=entity_id,
                    period=period, account_id=account_id,
                    department=department, amount=amount,
                ))
                actuals_count += 1
        session.commit()

    return {
        "status": "imported",
        "file": file.filename,
        "rows": len(rows),
        "actuals_imported": actuals_count,
        "budget_imported": budget_count,
    }
