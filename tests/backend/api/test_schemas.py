"""Tests for API schemas (Pydantic request/response models).

Validates:
- PipelineRunRequest accepts valid input
- PipelineRunResponse serializes correctly
- All response models have required fields
- Schema field types and defaults are correct
"""

import pytest
from pydantic import ValidationError
from backend.api.schemas import (
    PipelineRunRequest,
    PipelineRunResponse,
    PipelineResultResponse,
    PipelineExecuteRequest,
    PipelineExecuteResponse,
    CommentaryResponse,
    CommentarySectionResponse,
    AssertionResponse,
    VarianceResponse,
    BridgeAnalysisResponse,
    BridgeComponentResponse,
    DataQualityResponse,
    DataQualityCheckResponse,
    PolicyDecisionResponse,
    ActionItemResponse,
    ActionCreateRequest,
    StatusResponse,
)


# ── PipelineRunRequest ──────────────────────────────────────────────────────


class TestPipelineRunRequest:
    def test_accepts_valid_input(self):
        req = PipelineRunRequest(period="2026-06", tenant_id="CF001")
        assert req.period == "2026-06"
        assert req.tenant_id == "CF001"
        assert req.run_sync is False

    def test_default_tenant_id(self):
        req = PipelineRunRequest(period="2026-06")
        assert req.tenant_id == "CF001"

    def test_run_sync_override(self):
        req = PipelineRunRequest(period="2026-06", run_sync=True)
        assert req.run_sync is True

    def test_missing_period_fails(self):
        with pytest.raises(ValidationError):
            PipelineRunRequest()


# ── PipelineRunResponse (existing) ──────────────────────────────────────────


class TestPipelineRunResponse:
    def test_serializes_correctly(self):
        resp = PipelineRunResponse(run_id="abc123", status="started", message="ok")
        data = resp.model_dump()
        assert data["run_id"] == "abc123"
        assert data["status"] == "started"
        assert data["message"] == "ok"
        assert len(data) == 3


# ── PipelineExecuteRequest / PipelineExecuteResponse ────────────────────────


class TestPipelineExecuteRequest:
    def test_accepts_valid_input(self):
        req = PipelineExecuteRequest(period="2026-06", tenant_id="CF001", force=False)
        assert req.period == "2026-06"
        assert req.tenant_id == "CF001"
        assert req.force is False

    def test_defaults(self):
        req = PipelineExecuteRequest(period="2026-06")
        assert req.tenant_id == "CF001"
        assert req.force is False

    def test_missing_period_fails(self):
        with pytest.raises(ValidationError):
            PipelineExecuteRequest()


class TestPipelineExecuteResponse:
    def test_has_all_required_fields(self):
        resp = PipelineExecuteResponse(
            period="2026-06",
            tenant_id="CF001",
            status="completed",
        )
        data = resp.model_dump()
        assert data["period"] == "2026-06"
        assert data["tenant_id"] == "CF001"
        assert data["status"] == "completed"
        assert data["commentary"] == []
        assert data["assertions"] == []
        assert data["degraded_modes"] == []
        assert data["data_quality"] is None
        assert data["routing_decision"] is None
        assert data["action_items"] == []

    def test_with_nested_models(self):
        resp = PipelineExecuteResponse(
            period="2026-06",
            tenant_id="CF001",
            status="completed",
            commentary=[
                CommentarySectionResponse(section_type="summary", content="text")
            ],
            assertions=[
                AssertionResponse(id="a1", type="numeric", text="test", confidence=0.9)
            ],
            routing_decision=PolicyDecisionResponse(
                autonomy_level="fully_autonomous",
                routing_target="auto_publish",
            ),
        )
        data = resp.model_dump()
        assert len(data["commentary"]) == 1
        assert len(data["assertions"]) == 1
        assert data["routing_decision"]["autonomy_level"] == "fully_autonomous"


# ── CommentaryResponse ──────────────────────────────────────────────────────


class TestCommentaryResponse:
    def test_has_required_fields(self):
        resp = CommentaryResponse(period="2026-06", tenant_id="CF001")
        data = resp.model_dump()
        assert data["period"] == "2026-06"
        assert data["tenant_id"] == "CF001"
        assert data["commentary"] == []
        assert data["assertions"] == []
        assert data["degraded_modes"] == []
        assert data["data_quality"] is None

    def test_with_full_data(self):
        resp = CommentaryResponse(
            period="2026-06",
            tenant_id="CF001",
            commentary=[CommentarySectionResponse(section_type="exec", content="hello")],
            assertions=[AssertionResponse(id="a1", type="numeric", text="t")],
            degraded_modes=["low_coverage"],
            data_quality=DataQualityResponse(overall_score=0.8, passed=True),
        )
        assert len(resp.commentary) == 1
        assert len(resp.assertions) == 1
        assert resp.degraded_modes == ["low_coverage"]


# ── VarianceResponse ────────────────────────────────────────────────────────


class TestVarianceResponse:
    def test_has_all_fields(self):
        v = VarianceResponse(
            account_id="a1",
            account_name="Revenue",
            department="Sales",
            actual_amount=100000.0,
            budget_amount=90000.0,
            variance_amount=10000.0,
            variance_pct=11.11,
            is_material=True,
        )
        data = v.model_dump()
        assert data["account_id"] == "a1"
        assert data["is_material"] is True
        assert data["variance_amount"] == 10000.0


# ── BridgeAnalysisResponse ─────────────────────────────────────────────────


class TestBridgeAnalysisResponse:
    def test_has_required_fields(self):
        resp = BridgeAnalysisResponse(
            account_id="a1",
            account_name="Revenue",
            total_variance="10000",
            bridge_type="revenue",
            reconciles=True,
            confidence=0.85,
        )
        data = resp.model_dump()
        assert data["account_id"] == "a1"
        assert data["bridge_type"] == "revenue"
        assert data["reconciles"] is True
        assert data["components"] == []

    def test_with_components(self):
        resp = BridgeAnalysisResponse(
            account_id="a1",
            account_name="Revenue",
            total_variance="10000",
            bridge_type="revenue",
            components=[
                BridgeComponentResponse(
                    component="price",
                    amount="6000",
                    percentage="60.0",
                    description="Price effect",
                    confidence=0.85,
                )
            ],
            reconciles=True,
            confidence=0.85,
        )
        assert len(resp.components) == 1
        assert resp.components[0].component == "price"


# ── DataQualityResponse ────────────────────────────────────────────────────


class TestDataQualityResponse:
    def test_has_required_fields(self):
        resp = DataQualityResponse(overall_score=0.85, passed=True)
        data = resp.model_dump()
        assert data["overall_score"] == 0.85
        assert data["passed"] is True
        assert data["degraded_modes"] == []
        assert data["checks"] == []

    def test_with_checks(self):
        resp = DataQualityResponse(
            overall_score=0.7,
            passed=True,
            checks=[
                DataQualityCheckResponse(
                    check="coverage", passed=True, severity="info", detail="ok"
                )
            ],
        )
        assert len(resp.checks) == 1
        assert resp.checks[0].check == "coverage"


# ── PolicyDecisionResponse ─────────────────────────────────────────────────


class TestPolicyDecisionResponse:
    def test_has_required_fields(self):
        resp = PolicyDecisionResponse(
            autonomy_level="fully_autonomous",
            routing_target="auto_publish",
        )
        data = resp.model_dump()
        assert data["autonomy_level"] == "fully_autonomous"
        assert data["routing_target"] == "auto_publish"
        assert data["reasons"] == []
        assert data["requires_review"] is False
        assert data["blocked_actions"] == []
        assert data["confidence"] == 0.0

    def test_with_full_data(self):
        resp = PolicyDecisionResponse(
            autonomy_level="analyst_in_the_loop",
            routing_target="review",
            reasons=["Low confidence"],
            requires_review=True,
            blocked_actions=["action blocked"],
            confidence=0.55,
        )
        assert resp.requires_review is True
        assert len(resp.blocked_actions) == 1


# ── ActionItemResponse / ActionCreateRequest ────────────────────────────────


class TestActionItemResponse:
    def test_has_required_fields(self):
        resp = ActionItemResponse(
            id="act_1",
            action="reduce",
            domain="cost",
            target="travel",
            description="Reduce travel costs",
        )
        data = resp.model_dump()
        assert data["id"] == "act_1"
        assert data["action"] == "reduce"
        assert data["domain"] == "cost"
        assert data["status"] == "proposed"
        assert data["owner"] is None
        assert data["impact_quantified"] is False
        assert data["policy_permitted"] is False
        assert data["blocked_reason"] is None
        assert data["cited_assertion_ids"] == []


class TestActionCreateRequest:
    def test_has_required_fields(self):
        req = ActionCreateRequest(
            action="reduce",
            domain="cost",
            target="travel",
            description="Reduce travel",
        )
        data = req.model_dump()
        assert data["action"] == "reduce"
        assert data["domain"] == "cost"
        assert data["cited_assertion_ids"] == []
        assert data["owner"] is None
        assert data["policy_permitted"] is False

    def test_with_impact(self):
        req = ActionCreateRequest(
            action="reduce",
            domain="cost",
            target="travel",
            description="Reduce travel",
            impact_expected_savings=50000.0,
            impact_expected_revenue=None,
        )
        assert req.impact_expected_savings == 50000.0


# ── StatusResponse ──────────────────────────────────────────────────────────


class TestStatusResponse:
    def test_has_required_fields(self):
        resp = StatusResponse(status="healthy", version="1.0.0")
        data = resp.model_dump()
        assert data["status"] == "healthy"
        assert data["version"] == "1.0.0"
        assert data["endpoints"] == []

    def test_with_endpoints(self):
        resp = StatusResponse(
            status="healthy",
            version="1.0.0",
            endpoints=["GET /api/v1/status"],
        )
        assert len(resp.endpoints) == 1


# ── AssertionResponse ──────────────────────────────────────────────────────


class TestAssertionResponse:
    def test_has_required_fields(self):
        resp = AssertionResponse(id="a1", type="numeric", text="test assertion")
        data = resp.model_dump()
        assert data["id"] == "a1"
        assert data["type"] == "numeric"
        assert data["text"] == "test assertion"
        assert data["value"] is None
        assert data["confidence"] == 0.0
        assert data["support_level"] == "insufficient"
        assert data["evidence_ids"] == []
        assert data["metadata"] == {}


# ── Cross-model serialization ──────────────────────────────────────────────


class TestCrossModelSerialization:
    def test_nested_serialization_roundtrip(self):
        """All models should serialize to dict and back without data loss."""
        original = PipelineExecuteResponse(
            period="2026-06",
            tenant_id="CF001",
            status="completed",
            commentary=[
                CommentarySectionResponse(section_type="exec", content="hello world")
            ],
            assertions=[
                AssertionResponse(
                    id="a1",
                    type="numeric",
                    text="Revenue up 10%",
                    value=100000.0,
                    confidence=0.92,
                    support_level="verified",
                )
            ],
            degraded_modes=["low_coverage"],
            data_quality=DataQualityResponse(
                overall_score=0.75,
                passed=True,
                checks=[
                    DataQualityCheckResponse(
                        check="coverage", passed=True, severity="info"
                    )
                ],
            ),
            routing_decision=PolicyDecisionResponse(
                autonomy_level="analyst_in_the_loop",
                routing_target="review",
                reasons=["Causal claims present"],
                requires_review=True,
                confidence=0.65,
            ),
            action_items=[
                ActionItemResponse(
                    id="act_1",
                    action="reduce",
                    domain="cost",
                    target="travel",
                    description="Cut travel",
                )
            ],
        )

        data = original.model_dump()
        restored = PipelineExecuteResponse(**data)
        assert restored.period == original.period
        assert len(restored.commentary) == len(original.commentary)
        assert len(restored.assertions) == len(original.assertions)
        assert restored.routing_decision.autonomy_level == "analyst_in_the_loop"
        assert len(restored.action_items) == 1
