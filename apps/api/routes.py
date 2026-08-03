import csv
import io
import logging
import uuid
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, UploadFile
from sqlalchemy import create_engine

from agents.commentary.commentary_agent import (
    CommentaryRenderInput,
    generate_commentary,
    render_commentary,
)
from agents.driver.root_cause_agent import investigate_root_causes
from agents.variance.variance_agent import variance_node
from apps.api.schemas import (
    ActionCreateRequest,
    ActionItemResponse,
    AssertionResponse,
    BridgeAnalysisResponse,
    BridgeComponentResponse,
    CommentaryResponse,
    CommentarySectionResponse,
    DataQualityCheckResponse,
    DataQualityResponse,
    PipelineExecuteRequest,
    PipelineExecuteResponse,
    PipelineResultResponse,
    PipelineRunRequest,
    PipelineRunResponse,
    PolicyDecisionResponse,
    StatusResponse,
    VarianceResponse,
)
from finance.assertion_pipeline import run_assertion_pipeline
from finance.driver_engine.bridge_analysis import decompose_bridge
from finance.ingestion.ingestion_agent import ingestion_node
from finance.validation.data_quality import assess_batch
from shared.config import get_settings
from shared.models.action import ActionDomain, ActionImpact, ActionItem, create_action
from shared.models.state import PipelineState
from shared.utils.llm_client import LLMClient
from shared.utils.policy import evaluate_from_pipeline_result
from shared.utils.tools.tool_result import ToolResult

router = APIRouter()

_runs: dict[str, dict] = {}

# In-memory store for action items (would be DB-backed in production)
_action_items: dict[str, ActionItem] = {}


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
            "tenant_id": req.tenant_id,
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

        llm_client = LLMClient()

        material = [v for v in state["variances"] if v.is_material]
        findings = investigate_root_causes(material, llm_client=llm_client)
        state["root_causes"] = findings

        draft = generate_commentary(findings, [], llm_client=llm_client)
        state["commentary_draft"] = draft

        variance_data = [
            {
                "account_id": v.account_id,
                "account_name": v.account_name,
                "department": v.department,
                "actual_amount": Decimal(str(v.actual_amount)),
                "budget_amount": Decimal(str(v.budget_amount)),
                "variance_amount": Decimal(str(v.variance_amount)),
                "variance_pct": Decimal(str(v.variance_pct)),
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
            "tenant_id": req.tenant_id,
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
            tenant_id=req.tenant_id,
            actuals_count=len(state["actuals"].get("accounts", [])),
            budget_count=len(state["budget"].get("accounts", [])),
            variances=variance_data,
            material_count=len(material),
            root_causes=root_cause_data,
            commentary_sections=commentary_data,
        )

    _runs[run_id] = {"status": "started", "period": req.period, "tenant_id": req.tenant_id}
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
async def import_csv(file: UploadFile = File(...), tenant_id: str = "CF001"):
    # DEPRECATED: Use POST /api/v1/jobs/submit with pipeline="analytics"
    # and source_type="csv" instead. This endpoint routes through the
    # Compute Runtime for new development.
    logging.warning(
        "DEPRECATED: POST /api/v1/import/csv is deprecated. "
        "Use POST /api/v1/jobs/submit with pipeline='analytics' and "
        "source_type='csv' via the Compute Runtime endpoint."
    )
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

    from shared.models.database import Actual, BudgetLine

    actuals_count = 0
    budget_count = 0
    with Session(engine) as session:
        for row in rows:
            amount = Decimal(row["amount"])
            account_id = row["account_id"]
            period = row["period"]
            department = row.get("department", "Unknown")

            if row.get("type", "actual") == "budget":
                session.add(BudgetLine(
                    id=str(uuid.uuid4())[:8], entity_id=tenant_id,
                    period=period, account_id=account_id,
                    department=department, amount=amount,
                ))
                budget_count += 1
            else:
                session.add(Actual(
                    id=str(uuid.uuid4())[:8], entity_id=tenant_id,
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


# ── New endpoints: truth/render separation API ──────────────────────────────


def _serialize_assertion(a) -> AssertionResponse:
    """Convert an Assertion model to an AssertionResponse."""
    return AssertionResponse(
        id=a.id,
        type=a.type.value if hasattr(a.type, "value") else str(a.type),
        text=a.text,
        value=Decimal(str(a.value)) if a.value is not None else None,
        evidence_ids=a.evidence_ids,
        support_level=a.support_level.value if hasattr(a.support_level, "value") else str(a.support_level),
        confidence=a.confidence,
        metadata=a.metadata or {},
    )


def _run_full_pipeline(period: str, tenant_id: str) -> dict:
    """Execute the full pipeline: ingest → variance → assertions → commentary → policy.

    Returns a dict with all intermediate results for the API response.
    """
    settings = get_settings()
    engine = create_engine(settings.postgres_uri)

    # 1. Ingest
    state: PipelineState = {
        "period": period,
        "tenant_id": tenant_id,
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

    # 2. Variance computation
    var_result = variance_node(state)
    state["variances"] = var_result["variances"]

    # 3. Root cause investigation
    llm_client = LLMClient()
    material = [v for v in state["variances"] if v.is_material]
    findings = investigate_root_causes(material, llm_client=llm_client)
    state["root_causes"] = findings

    # 4. Build assertions from variance data
    variance_dicts = [
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

    # Create a minimal ToolResult for assertion pipeline
    tool_results_for_pipeline = [
        ToolResult(
            data=[],
            row_count=len(state["actuals"].get("accounts", [])),
            coverage_pct=0.8,
            quality_score=0.8,
            freshness_seconds=3600,
            schema_version="1.0",
            source_diversity=1,
            source_type="financial_fact",
            retrieval_scope="factual",
            tenant_id=tenant_id,
            required_filters_present=True,
            insufficient_data=False,
            degraded_mode=None,
            query_fingerprint=None,
        )
    ]

    assertion_result = run_assertion_pipeline(
        variances=variance_dicts,
        tool_results={"gl": tool_results_for_pipeline},
    )

    # 5. Data quality assessment
    quality_report = assess_batch(tool_results_for_pipeline)

    # 6. Evaluate policy
    policy_decision = evaluate_from_pipeline_result(
        assertion_result,
        degraded_modes=assertion_result.degraded_modes,
    )

    # 7. Render commentary via truth/render separation
    render_input = CommentaryRenderInput.from_assertion_list(
        assertions=assertion_result.assertions,
        degraded_modes=assertion_result.degraded_modes or None,
        period=period,
        entity_name=tenant_id,
    )
    commentary_text = render_commentary(render_input, llm_client=llm_client)

    # Parse commentary into sections
    from agents.commentary.commentary_agent import _parse_sections_from_text
    sections = _parse_sections_from_text(commentary_text)
    if not sections:
        sections = []
        from shared.models.state import CommentarySection
        sections.append(CommentarySection(
            section_type="executive_summary",
            content=commentary_text,
        ))

    return {
        "state": state,
        "assertions": assertion_result.assertions,
        "degraded_modes": assertion_result.degraded_modes,
        "quality_report": quality_report,
        "policy_decision": policy_decision,
        "commentary_sections": sections,
        "variance_dicts": variance_dicts,
    }


@router.get("/status", response_model=StatusResponse)
async def get_status():
    """System status and available endpoints."""
    return StatusResponse(
        status="healthy",
        version="1.0.0",
        endpoints=[
            "GET /api/v1/status",
            "GET /api/v1/health",
            "POST /api/v1/pipeline/run",
            "POST /api/v1/pipeline/execute",
            "GET /api/v1/commentary/{period}",
            "GET /api/v1/variances/{period}",
            "GET /api/v1/bridge/{period}/{account_id}",
            "GET /api/v1/data-quality/{period}",
            "GET /api/v1/policy/{period}",
            "GET /api/v1/actions",
            "POST /api/v1/actions",
            "GET /api/v1/actions/{action_id}",
        ],
    )


@router.post("/pipeline/execute", response_model=PipelineExecuteResponse)
async def execute_full_pipeline(req: PipelineExecuteRequest):
    """Full pipeline: ingest → variance → assertions → commentary → policy.

    Returns both raw truth (assertions) and rendered commentary.
    """
    try:
        result = _run_full_pipeline(req.period, req.tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline execution failed: {e}")

    assertions_resp = [_serialize_assertion(a) for a in result["assertions"]]
    commentary_resp = [
        CommentarySectionResponse(
            section_type=s.section_type,
            content=s.content,
            cited_data_points=getattr(s, "cited_data_points", []),
        )
        for s in result["commentary_sections"]
    ]

    dq = result["quality_report"]
    dq_resp = DataQualityResponse(
        overall_score=dq.overall_score,
        passed=dq.passed,
        degraded_modes=dq.degraded_modes,
        checks=[DataQualityCheckResponse(**c.to_dict()) for c in dq.checks],
    )

    pd = result["policy_decision"]
    pd_resp = PolicyDecisionResponse(
        autonomy_level=pd.autonomy_level.value,
        routing_target=pd.routing_target,
        reasons=pd.reasons,
        requires_review=pd.requires_review,
        blocked_actions=pd.blocked_actions,
        confidence=pd.confidence,
    )

    return PipelineExecuteResponse(
        period=req.period,
        tenant_id=req.tenant_id,
        status="completed",
        commentary=commentary_resp,
        assertions=assertions_resp,
        degraded_modes=result["degraded_modes"],
        data_quality=dq_resp,
        routing_decision=pd_resp,
        action_items=[],
    )


@router.get("/commentary/{period}", response_model=CommentaryResponse)
async def get_commentary(period: str, tenant_id: str = "CF001"):
    """Get commentary + assertions for a period (truth/render separation)."""
    try:
        result = _run_full_pipeline(period, tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Commentary generation failed: {e}")

    assertions_resp = [_serialize_assertion(a) for a in result["assertions"]]
    commentary_resp = [
        CommentarySectionResponse(
            section_type=s.section_type,
            content=s.content,
            cited_data_points=getattr(s, "cited_data_points", []),
        )
        for s in result["commentary_sections"]
    ]

    dq = result["quality_report"]
    dq_resp = DataQualityResponse(
        overall_score=dq.overall_score,
        passed=dq.passed,
        degraded_modes=dq.degraded_modes,
        checks=[DataQualityCheckResponse(**c.to_dict()) for c in dq.checks],
    )

    return CommentaryResponse(
        period=period,
        tenant_id=tenant_id,
        commentary=commentary_resp,
        assertions=assertions_resp,
        degraded_modes=result["degraded_modes"],
        data_quality=dq_resp,
    )


@router.get("/variances/{period}", response_model=list[VarianceResponse])
async def get_variances(period: str, tenant_id: str = "CF001"):
    """Get computed variances for a period."""
    settings = get_settings()
    engine = create_engine(settings.postgres_uri)

    state: PipelineState = {
        "period": period,
        "tenant_id": tenant_id,
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

    return [
        VarianceResponse(
            account_id=v.account_id,
            account_name=v.account_name,
            department=v.department,
            actual_amount=Decimal(str(v.actual_amount)),
            budget_amount=Decimal(str(v.budget_amount)),
            variance_amount=Decimal(str(v.variance_amount)),
            variance_pct=Decimal(str(v.variance_pct)),
            is_material=v.is_material,
        )
        for v in var_result["variances"]
    ]


@router.get("/bridge/{period}/{account_id}", response_model=BridgeAnalysisResponse)
async def get_bridge_analysis(period: str, account_id: str, tenant_id: str = "CF001"):
    """Get bridge (variance decomposition) analysis for a specific account."""
    # Fetch variances for the period
    settings = get_settings()
    engine = create_engine(settings.postgres_uri)

    state: PipelineState = {
        "period": period,
        "tenant_id": tenant_id,
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

    # Find the matching variance
    target_variance = None
    for v in var_result["variances"]:
        if v.account_id == account_id:
            target_variance = v
            break

    if target_variance is None:
        raise HTTPException(
            status_code=404,
            detail=f"Account {account_id} not found in period {period}",
        )

    # Determine account type from department or name
    account_type = "cost"
    name_lower = target_variance.account_name.lower()
    if any(w in name_lower for w in ["revenue", "sales", "income"]):
        account_type = "revenue"

    analysis = decompose_bridge(
        account_id=target_variance.account_id,
        account_name=target_variance.account_name,
        current_actual=target_variance.actual_amount,
        prior_actual=target_variance.budget_amount,  # using budget as prior for bridge
        budget=target_variance.budget_amount,
        account_type=account_type,
    )

    return BridgeAnalysisResponse(
        account_id=analysis.account_id,
        account_name=analysis.account_name,
        total_variance=str(analysis.total_variance),
        bridge_type=analysis.bridge_type.value,
        components=[
            BridgeComponentResponse(
                component=c.component.value,
                amount=str(c.amount),
                percentage=str(c.percentage),
                description=c.description,
                confidence=c.confidence,
            )
            for c in analysis.components
        ],
        reconciles=analysis.reconciles,
        confidence=analysis.confidence,
        degraded_modes=analysis.degraded_modes or [],
    )


@router.get("/data-quality/{period}", response_model=DataQualityResponse)
async def get_data_quality(period: str, tenant_id: str = "CF001"):
    """Get data quality assessment for a period."""
    settings = get_settings()
    engine = create_engine(settings.postgres_uri)

    state: PipelineState = {
        "period": period,
        "tenant_id": tenant_id,
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

    # Create tool results for quality assessment
    tool_results = [
        ToolResult(
            data=[],
            row_count=len(state["actuals"].get("accounts", [])),
            coverage_pct=0.8,
            quality_score=0.8,
            freshness_seconds=3600,
            schema_version="1.0",
            source_diversity=1,
            source_type="financial_fact",
            retrieval_scope="factual",
            tenant_id=tenant_id,
            required_filters_present=True,
            insufficient_data=False,
            degraded_mode=None,
            query_fingerprint=None,
        )
    ]

    report = assess_batch(tool_results)

    return DataQualityResponse(
        overall_score=report.overall_score,
        passed=report.passed,
        degraded_modes=report.degraded_modes,
        checks=[DataQualityCheckResponse(**c.to_dict()) for c in report.checks],
    )


@router.get("/policy/{period}", response_model=PolicyDecisionResponse)
async def get_policy_decision(period: str, tenant_id: str = "CF001"):
    """Get policy (autonomy/routing) decision for a period."""
    try:
        result = _run_full_pipeline(period, tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Policy evaluation failed: {e}")

    pd = result["policy_decision"]
    return PolicyDecisionResponse(
        autonomy_level=pd.autonomy_level.value,
        routing_target=pd.routing_target,
        reasons=pd.reasons,
        requires_review=pd.requires_review,
        blocked_actions=pd.blocked_actions,
        confidence=pd.confidence,
    )


@router.get("/actions", response_model=list[ActionItemResponse])
async def list_actions():
    """List all action items."""
    return [
        ActionItemResponse(
            id=a.id,
            action=a.action,
            domain=a.domain.value,
            target=a.target,
            description=a.description,
            status=a.status.value,
            owner=a.owner,
            impact_quantified=a.impact_quantified,
            policy_permitted=a.policy_permitted,
            blocked_reason=a.blocked_reason,
            cited_assertion_ids=a.cited_assertion_ids,
        )
        for a in _action_items.values()
    ]


@router.post("/actions", response_model=ActionItemResponse)
async def create_action_item(req: ActionCreateRequest):
    """Create a new action item with gate enforcement."""
    try:
        domain = ActionDomain(req.domain)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid domain: {req.domain}. Must be one of: {[d.value for d in ActionDomain]}",
        )

    impact = None
    if req.impact_expected_savings is not None or req.impact_expected_revenue is not None:
        impact = ActionImpact(
            expected_savings=Decimal(str(req.impact_expected_savings)) if req.impact_expected_savings is not None else None,
            expected_revenue=Decimal(str(req.impact_expected_revenue)) if req.impact_expected_revenue is not None else None,
        )

    result = create_action(
        action=req.action,
        domain=domain,
        target=req.target,
        description=req.description,
        cited_assertion_ids=req.cited_assertion_ids,
        owner=req.owner,
        impact=impact,
        policy_permitted=req.policy_permitted,
    )

    if not result.created:
        raise HTTPException(status_code=422, detail={"errors": result.errors, "warnings": result.warnings})

    # Store in memory
    if result.action_item:
        _action_items[result.action_item.id] = result.action_item

    a = result.action_item
    return ActionItemResponse(
        id=a.id,
        action=a.action,
        domain=a.domain.value,
        target=a.target,
        description=a.description,
        status=a.status.value,
        owner=a.owner,
        impact_quantified=a.impact_quantified,
        policy_permitted=a.policy_permitted,
        blocked_reason=a.blocked_reason,
        cited_assertion_ids=a.cited_assertion_ids,
    )


@router.get("/actions/{action_id}", response_model=ActionItemResponse)
async def get_action_item(action_id: str):
    """Get a specific action item by ID."""
    if action_id not in _action_items:
        raise HTTPException(status_code=404, detail=f"Action item {action_id} not found")

    a = _action_items[action_id]
    return ActionItemResponse(
        id=a.id,
        action=a.action,
        domain=a.domain.value,
        target=a.target,
        description=a.description,
        status=a.status.value,
        owner=a.owner,
        impact_quantified=a.impact_quantified,
        policy_permitted=a.policy_permitted,
        blocked_reason=a.blocked_reason,
        cited_assertion_ids=a.cited_assertion_ids,
    )


# ── Compute Runtime routes ──────────────────────────────────────────────


from apps.api.schemas import JobStatusResponse, JobSubmitRequest, JobSubmitResponse  # noqa: E402
from python_runtime.dispatcher import Dispatcher  # noqa: E402
from python_runtime.handlers.analytics_handler import AnalyticsHandler  # noqa: E402
from python_runtime.models import Job  # noqa: E402

compute_router = APIRouter(prefix="/api/v1")

_dispatcher = Dispatcher(max_workers=4)
_dispatcher.register("analytics", AnalyticsHandler())


@compute_router.post("/jobs/submit", status_code=202)
async def submit_job(req: JobSubmitRequest) -> JobSubmitResponse:
    job = Job(
        tenant_id=req.tenant_id,
        pipeline=req.pipeline,
        params={"source_type": req.source_type, "source_uri": req.source_uri, **req.params},
    )
    _dispatcher.submit(job)
    return JobSubmitResponse(
        job_id=str(job.id),
        status=job.status.value,
        created_at=job.created_at.isoformat(),
        poll_url=f"/api/v1/jobs/{job.id}/status",
        result_url=f"/api/v1/jobs/{job.id}/result",
    )


@compute_router.get("/jobs/{job_id}/status")
async def get_job_status(job_id: UUID) -> JobStatusResponse:
    job = _dispatcher.get_result(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    artifact = None
    if job.telemetry and job.telemetry.cache_hit:
        artifact = {"from_cache": True}
    return JobStatusResponse(
        job_id=str(job.id),
        status=job.status.value,
        created_at=job.created_at.isoformat() if job.created_at else None,
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        duration_ms=job.telemetry.duration_ms if job.telemetry else None,
        error=job.error.model_dump() if job.error else None,
        artifact=artifact,
    )


@compute_router.get("/jobs/{job_id}/result")
async def get_job_result(job_id: UUID) -> dict:
    job = _dispatcher.get_result(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    if job.status.value != "success":
        raise HTTPException(status_code=400, detail=f"Job not completed: {job.status.value}")
    return {"job_id": str(job.id), "status": job.status.value, "result_ref": job.result_ref}


@compute_router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: UUID) -> dict:
    cancelled = _dispatcher.cancel(job_id)
    if not cancelled:
        raise HTTPException(
            status_code=400,
            detail="Job cannot be cancelled (already running or not found)",
        )
    return {"job_id": str(job_id), "status": "cancelled"}
